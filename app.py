from flask import Flask, render_template, request, jsonify, send_from_directory
import yt_dlp
import os
import logging
import threading
import uuid
import time
import datetime
import shutil

app = Flask(__name__)

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DOWNLOAD_FOLDER = '/app/downloads'
COOKIES_FILE = '/app/cookies.txt'
EXPIRATION_TIME = 4 * 3600  # 4 horas en segundos

if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)

# Estado de las descargas
download_status = {}

def cleanup_loop():
    """Hilo que revisa y borra archivos expirados"""
    while True:
        try:
            now = time.time()
            for f in os.listdir(DOWNLOAD_FOLDER):
                path = os.path.join(DOWNLOAD_FOLDER, f)
                if os.path.exists(path):
                    stat = os.stat(path)
                    # Usamos mtime (modificación) para saber la "edad"
                    age = now - stat.st_mtime
                    if age > EXPIRATION_TIME:
                        try:
                            if os.path.isfile(path):
                                os.remove(path)
                            elif os.path.isdir(path):
                                shutil.rmtree(path)
                            logger.info(f"Elemento expirado eliminado: {f}")
                        except Exception as e:
                            logger.error(f"Error eliminando {f}: {e}")
        except Exception as e:
            logger.error(f"Error en ciclo de limpieza: {e}")
        
        time.sleep(600) # Revisar cada 10 minutos

# Iniciar hilo de limpieza
cleanup_thread = threading.Thread(target=cleanup_loop, daemon=True)
cleanup_thread.start()

def format_duration(seconds):
    if not seconds: return "00:00"
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{int(h):02d}:{int(m):02d}:{int(s):02d}"
    return f"{int(m):02d}:{int(s):02d}"

def progress_hook(d, task_id):
    task = download_status.get(task_id)
    if task and task.get('cancel_requested'):
        raise Exception("DownloadCancelled")

    if d['status'] == 'downloading':
        try:
            p = d.get('_percent_str', '0%').replace('%', '')
            task['progress'] = float(p)
            task['status'] = 'downloading'
            task['speed'] = d.get('_speed_str', 'N/A')
            task['eta'] = d.get('_eta_str', 'N/A')
            
            # Playlist info
            info = d.get('info_dict', {})
            if 'playlist_index' in info and 'playlist_count' in info:
                task['playlist_index'] = info['playlist_index']
                task['playlist_count'] = info['playlist_count']
        except:
            pass
    elif d['status'] == 'finished':
        task['progress'] = 100
        task['status'] = 'processing'

def run_download_thread(task_id, url, format_type, quality, subtitles, subtitle_lang=None, download_playlist=False):
    task = download_status[task_id]
    task['status'] = 'starting'
    
    output_template = f'{DOWNLOAD_FOLDER}/%(title)s.%(ext)s'
    if download_playlist:
        # Force playlist mode if user requested it
        task['is_playlist'] = True

    ydl_opts = {
        'outtmpl': output_template,
        'noplaylist': not download_playlist,
        'ignoreerrors': True,
        'no_warnings': True,
        'restrictfilenames': True,
        'progress_hooks': [lambda d: progress_hook(d, task_id)],
    }

    # Usar cookies solo si es YouTube y el archivo existe
    # Mejorar detección de URLs de YouTube
    is_youtube = 'youtube.com' in url or 'youtu.be' in url
    if is_youtube:
        if os.path.exists(COOKIES_FILE):
            ydl_opts['cookiefile'] = COOKIES_FILE
            logger.info(f"Usando cookies para: {url} (Archivo: {COOKIES_FILE})")
        else:
            logger.warning(f"URL de YouTube detectada pero no hay cookies: {url}")

    if subtitles:
        # Configuración base de subtítulos
        subs_opts = {
            'writesubtitles': True,
            'writeautomaticsub': True,
            'postprocessors': [{
                'key': 'FFmpegSubtitlesConvertor',
                'format': 'srt',
            }],
        }
        
        # Configurar idiomas
        if subtitle_lang and subtitle_lang != 'all':
            subs_opts['subtitleslangs'] = [subtitle_lang]
        else:
            # Si es 'all' o no se especifica, intentamos bajar todos o mantenemos un default amplio
            # 'all' en yt-dlp se puede lograr con regex '.*' o simplemente no filtrando si se usa --all-subs
            # Pero aquí usamos la API. ['all'] suele funcionar como alias de todos.
            subs_opts['subtitleslangs'] = ['all', '-live_chat'] 

        ydl_opts.update(subs_opts)

    if format_type == 'audio':
        # Si hay subtítulos en audio (raro pero posible), mantenemos el postprocesador de subs
        # pero necesitamos añadir el de audio.
        postprocessors = []
        if subtitles:
            postprocessors.append({
                'key': 'FFmpegSubtitlesConvertor',
                'format': 'srt',
            })
        
        postprocessors.append({
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        })

        ydl_opts.update({
            'format': 'bestaudio/best',
            'postprocessors': postprocessors,
        })
    else:
        # Añadimos '/best' al final de todo como red de seguridad absoluta
        if quality == '4k':
            fmt = 'bestvideo+bestaudio/best'
        elif quality == '1080p':
            fmt = 'bestvideo[height<=1080]+bestaudio/best[height<=1080]/best[height<=1080]/best'
        elif quality == '720p':
            fmt = 'bestvideo[height<=720]+bestaudio/best[height<=720]/best[height<=720]/best'
        else:
            fmt = 'bestvideo+bestaudio/best'

        # Si hay subtítulos, ya tenemos el postprocessor de subs en ydl_opts si se activó arriba?
        # No, 'postprocessors' en update sobrescribe. Hay que tener cuidado.
        
        current_postprocessors = ydl_opts.get('postprocessors', [])
        
        ydl_opts.update({
            'format': fmt,
            'merge_output_format': 'mp4',
            'postprocessors': current_postprocessors
        })

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            
            # Obtenemos el nombre de archivo sanitizado que yt-dlp generó
            if task.get('is_playlist'):
                 task['filename'] = None # No hay un solo archivo para descargar
            else:
                temp_path = ydl.prepare_filename(info)
                sanitized_base = os.path.splitext(os.path.basename(temp_path))[0]
                
                if format_type == 'audio':
                    filename = f"{sanitized_base}.mp3"
                else:
                    filename = f"{sanitized_base}.mp4"
                task['filename'] = filename

            task['status'] = 'completed'
            task['progress'] = 100
            
    except Exception as e:
        if "DownloadCancelled" in str(e):
            task['status'] = 'cancelled'
            logger.info(f"Tarea {task_id} cancelada por usuario")
        else:
            logger.error(f"Error en tarea {task_id}: {str(e)}")
            task['status'] = 'error'
            task['error'] = str(e)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/info', methods=['POST'])
def get_info():
    data = request.get_json()
    url = data.get('url')
    if not url: return jsonify({'error': 'URL requerida'}), 400

    try:
        ydl_opts = {'noplaylist': True}
        
        # Usar cookies solo si es YouTube y el archivo existe
        is_youtube = 'youtube.com' in url or 'youtu.be' in url
        if is_youtube:
            if os.path.exists(COOKIES_FILE):
                ydl_opts['cookiefile'] = COOKIES_FILE
                logger.info(f"Usando cookies para info de: {url}")

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            # Extraer idiomas disponibles
            subtitles = set()
            if 'subtitles' in info:
                subtitles.update(info['subtitles'].keys())
            if 'automatic_captions' in info:
                subtitles.update(info['automatic_captions'].keys())
            
            # Ordenar alfabéticamente
            sorted_subs = sorted(list(subtitles))

        return jsonify({
            'title': info.get('title'),
            'thumbnail': info.get('thumbnail'),
            'duration': format_duration(info.get('duration')),
            'uploader': info.get('uploader'),
            'view_count': info.get('view_count'),
            'subtitles': sorted_subs
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/download', methods=['POST'])
def start_download():
    data = request.get_json()
    url = data.get('url')
    format_type = data.get('format', 'video')
    quality = data.get('quality', 'best')
    subtitles = data.get('subtitles', False)
    subtitle_lang = data.get('subtitle_lang', None)
    download_playlist = data.get('download_playlist', False)

    task_id = str(uuid.uuid4())
    download_status[task_id] = {
        'status': 'pending',
        'progress': 0,
        'cancel_requested': False,
        'is_playlist': False
    }
    
    thread = threading.Thread(target=run_download_thread, args=(task_id, url, format_type, quality, subtitles, subtitle_lang, download_playlist))
    thread.start()
    
    return jsonify({'task_id': task_id})

@app.route('/api/cancel', methods=['POST'])
def cancel_download():
    data = request.get_json()
    task_id = data.get('task_id')
    if task_id in download_status:
        download_status[task_id]['cancel_requested'] = True
        return jsonify({'message': 'Cancelación solicitada'})
    return jsonify({'error': 'Tarea no encontrada'}), 404

@app.route('/api/status/<task_id>')
def get_status(task_id):
    return jsonify(download_status.get(task_id, {'error': 'Not found'}))

@app.route('/api/history')
def get_history():
    files = []
    now = time.time()
    try:
        for f in os.listdir(DOWNLOAD_FOLDER):
            path = os.path.join(DOWNLOAD_FOLDER, f)
            
            if os.path.isfile(path):
                stat = os.stat(path)
                age = now - stat.st_mtime
                remaining = max(0, EXPIRATION_TIME - age)
                
                files.append({
                    'name': f,
                    'type': 'file',
                    'size': stat.st_size,
                    'date': datetime.datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
                    'remaining_seconds': int(remaining),
                    'expires_at': stat.st_mtime + EXPIRATION_TIME
                })
            elif os.path.isdir(path):
                # Es una carpeta (playlist)
                stat = os.stat(path)
                age = now - stat.st_mtime
                remaining = max(0, EXPIRATION_TIME - age)
                
                # Calcular tamaño total
                total_size = 0
                for dirpath, dirnames, filenames in os.walk(path):
                    for f_sub in filenames:
                        fp = os.path.join(dirpath, f_sub)
                        total_size += os.path.getsize(fp)

                files.append({
                    'name': f,
                    'type': 'playlist',
                    'size': total_size,
                    'date': datetime.datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
                    'remaining_seconds': int(remaining),
                    'expires_at': stat.st_mtime + EXPIRATION_TIME
                })

        files.sort(key=lambda x: x['date'], reverse=True)
    except Exception as e:
        logger.error(f"Error leyendo historial: {e}")
    return jsonify(files)

@app.route('/api/files/<path:filename>', methods=['DELETE'])
def delete_file(filename):
    try:
        path = os.path.join(DOWNLOAD_FOLDER, filename)
        if os.path.isfile(path):
            os.remove(path)
        elif os.path.isdir(path):
            shutil.rmtree(path)
        return jsonify({'message': 'Elemento eliminado'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/view/<path:filename>')
def view_file(filename):
    try:
        path = os.path.join(DOWNLOAD_FOLDER, filename)
        if os.path.exists(path):
            os.utime(path, None) # Touch
    except:
        pass
    return send_from_directory(DOWNLOAD_FOLDER, filename, as_attachment=False, conditional=True)

@app.route('/downloads/<path:filename>')
def download_file(filename):
    try:
        path = os.path.join(DOWNLOAD_FOLDER, filename)
        if os.path.exists(path):
            os.utime(path, None) # Touch
    except:
        pass
    return send_from_directory(DOWNLOAD_FOLDER, filename, as_attachment=True)

@app.route('/api/upload-cookies', methods=['POST'])
def upload_cookies():
    if 'file' not in request.files:
        return jsonify({'error': 'No se envió ningún archivo'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'Nombre de archivo vacío'}), 400
        
    try:
        # Validar formato Netscape
        content = file.read().decode('utf-8', errors='ignore')
        if not content.startswith('# Netscape HTTP Cookie File') and not content.startswith('# HTTP Cookie File'):
             return jsonify({'error': 'El archivo no tiene formato Netscape/Mozilla válido (debe empezar con # Netscape HTTP Cookie File)'}), 400
        
        # Reset file pointer
        file.seek(0)
        file.save(COOKIES_FILE)
        return jsonify({'message': 'Cookies subidas correctamente'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/cookies-status')
def cookies_status():
    exists = os.path.exists(COOKIES_FILE)
    return jsonify({'exists': exists})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
