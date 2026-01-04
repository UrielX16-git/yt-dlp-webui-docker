"""
Servicio de yt-dlp para manejar descargas de video/audio.
Encapsula toda la lógica de yt-dlp.
"""
import yt_dlp
import os
import logging
from typing import Dict, Any, Callable, Optional

logger = logging.getLogger(__name__)

DOWNLOAD_FOLDER = '/app/downloads'
COOKIES_FILE = '/app/cookies.txt'


def format_duration(seconds):
    """Formatea duración en segundos a HH:MM:SS o MM:SS."""
    if not seconds:
        return "00:00"
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{int(h):02d}:{int(m):02d}:{int(s):02d}"
    return f"{int(m):02d}:{int(s):02d}"


def process_url(url: str) -> str:
    """
    Procesa y normaliza URLs antes de pasarlas a yt-dlp.
    
    Transformaciones soportadas:
    - Twitch Dashboard → Twitch Public Video URL
    
    Args:
        url: URL original
        
    Returns:
        URL procesada/normalizada
    """
    import re
    
    # Twitch Dashboard to Public Video
    # https://dashboard.twitch.tv/u/usuariocualquiera/content/video-producer/edit/2625520227
    # https://www.twitch.tv/videos/2625520227
    twitch_dash_regex = r'dashboard\.twitch\.tv/u/[^/]+/content/video-producer/edit/(\d+)'
    match = re.search(twitch_dash_regex, url)
    if match:
        video_id = match.group(1)
        processed = f'https://www.twitch.tv/videos/{video_id}'
        logger.info(f"URL procesada: Twitch Dashboard → {processed}")
        return processed
    
    return url


def get_video_info(url: str) -> Dict[str, Any]:
    """
    Obtiene información del video sin descargarlo.
    
    Args:
        url: URL del video
        
    Returns:
        Diccionario con metadata del video
    """
    # Procesar URL antes de usarla
    url = process_url(url)
    
    ydl_opts = {'noplaylist': True}
    
    # Usar cookies si es YouTube y existe el archivo
    is_youtube = 'youtube.com' in url or 'youtu.be' in url
    if is_youtube and os.path.exists(COOKIES_FILE):
        ydl_opts['cookiefile'] = COOKIES_FILE
        logger.info(f"Usando cookies para info de: {url}")
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        
        # Extraer idiomas de subtítulos disponibles
        subtitles = set()
        if 'subtitles' in info:
            subtitles.update(info['subtitles'].keys())
        if 'automatic_captions' in info:
            subtitles.update(info['automatic_captions'].keys())
        
        sorted_subs = sorted(list(subtitles))
        
    return {
        'title': info.get('title'),
        'thumbnail': info.get('thumbnail'),
        'duration': format_duration(info.get('duration')),
        'uploader': info.get('uploader'),
        'view_count': info.get('view_count'),
        'subtitles': sorted_subs
    }


def get_playlist_info(url: str, max_items: int = -1) -> Dict[str, Any]:
    """
    Obtiene información de una playlist sin descargarla.
    
    Args:
        url: URL de la playlist
        max_items: Límite de items a retornar (-1 o 0 = todos, >0 = límite)
        
    Returns:
        Diccionario con metadata de la playlist y lista de videos
    """
    # Procesar URL antes de usarla
    url = process_url(url)
    
    ydl_opts = {
        'extract_flat': True,  # Solo extraer metadata, no descargar
        'quiet': True,
        'no_warnings': True
    }
    
    # Usar cookies si es YouTube y existe el archivo
    is_youtube = 'youtube.com' in url or 'youtu.be' in url
    if is_youtube and os.path.exists(COOKIES_FILE):
        ydl_opts['cookiefile'] = COOKIES_FILE
        logger.info(f"Usando cookies para info de playlist: {url}")
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        
        # Verificar que sea una playlist
        if info.get('_type') != 'playlist':
            raise ValueError('La URL no corresponde a una playlist')
        
        # Extraer información de los videos
        entries = info.get('entries', [])
        
        # Aplicar límite si se especifica
        if max_items > 0:
            entries = entries[:max_items]
        
        videos = []
        for idx, entry in enumerate(entries, 1):
            if entry:  # Algunos entries pueden ser None si hay errores
                videos.append({
                    'index': idx,
                    'url': entry.get('url') or f"https://www.youtube.com/watch?v={entry.get('id')}",
                    'title': entry.get('title', 'Sin título'),
                    'duration': format_duration(entry.get('duration')),
                    'thumbnail': entry.get('thumbnail'),
                    'uploader': entry.get('uploader') or entry.get('channel'),
                })
        
        return {
            'playlist_title': info.get('title'),
            'playlist_uploader': info.get('uploader') or info.get('channel'),
            'total_videos': len(info.get('entries', [])),
            'returned_videos': len(videos),
            'videos': videos
        }



def download_media(
    url: str,
    format_type: str,  # 'video' or 'audio'
    quality: str,  # '4k', '1080p', '720p', 'best'
    subtitles: bool = False,
    subtitle_lang: Optional[str] = None,
    download_playlist: bool = False,
    max_items: int = -1,
    custom_output_dir: Optional[str] = None,
    progress_callback: Optional[Callable] = None
) -> Dict[str, Any]:
    """
    Descarga video o audio usando yt-dlp.
    
    Args:
        url: URL del video/audio
        format_type: 'video' o 'audio'
        quality: Calidad deseada
        subtitles: Si descargar subtítulos
        subtitle_lang: Idioma de subtítulos ('all' o código de idioma)
        download_playlist: Si descargar playlist completa
        progress_callback: Función callback para progreso
        
    Returns:
        Diccionario con información del resultado
    """
    # Procesar URL antes de usarla
    url = process_url(url)
    
    os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)
    
    # Configurar template de salida
    if custom_output_dir:
        # Usar directorio personalizado (para videos individuales de playlist)
        os.makedirs(custom_output_dir, exist_ok=True)
        output_template = f'{custom_output_dir}/%(title)s.%(ext)s'
    elif download_playlist:
        # Para playlists: Crear subcarpeta
        output_template = f'{DOWNLOAD_FOLDER}/%(playlist_title)s/%(title)s.%(ext)s'
    else:
        # Para videos individuales: descarga directa
        output_template = f'{DOWNLOAD_FOLDER}/%(title)s.%(ext)s'
    
    ydl_opts = {
        'outtmpl': output_template,
        'noplaylist': not download_playlist,
        'ignoreerrors': True,
        'no_warnings': True,
        'restrictfilenames': True,
    }
    
    # Aplicar límite de items si es playlist y max_items > 0
    if download_playlist and max_items > 0:
        ydl_opts['playlistend'] = max_items
    
    # Progress hook
    if progress_callback:
        ydl_opts['progress_hooks'] = [progress_callback]
    
    # Usar cookies para YouTube
    is_youtube = 'youtube.com' in url or 'youtu.be' in url
    if is_youtube and os.path.exists(COOKIES_FILE):
        ydl_opts['cookiefile'] = COOKIES_FILE
        logger.info(f"Usando cookies para: {url}")
    
    # Configurar subtítulos
    if subtitles:
        subs_opts = {
            'writesubtitles': True,
            'writeautomaticsub': True,
            'postprocessors': [{
                'key': 'FFmpegSubtitlesConvertor',
                'format': 'srt',
            }],
        }
        
        if subtitle_lang and subtitle_lang != 'all':
            subs_opts['subtitleslangs'] = [subtitle_lang]
        else:
            subs_opts['subtitleslangs'] = ['all', '-live_chat']
        
        ydl_opts.update(subs_opts)
    
    # Configurar formato según tipo
    if format_type == 'audio':
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
    else:  # video
        if quality == '4k':
            fmt = 'bestvideo+bestaudio/best'
        elif quality == '1080p':
            fmt = 'bestvideo[height<=1080]+bestaudio/best[height<=1080]/best[height<=1080]/best'
        elif quality == '720p':
            fmt = 'bestvideo[height<=720]+bestaudio/best[height<=720]/best[height<=720]/best'
        else:
            fmt = 'bestvideo+bestaudio/best'
        
        current_postprocessors = ydl_opts.get('postprocessors', [])
        
        ydl_opts.update({
            'format': fmt,
            'merge_output_format': 'mp4',
            'postprocessors': current_postprocessors
        })
    
    # Ejecutar descarga
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        
        result = {
            'is_playlist': download_playlist and info.get('_type') == 'playlist',
            'filename': None,
            'playlist_folder': None,
            'files': []
        }
        
        if result['is_playlist']:
            # Para playlists, retornar el nombre de la carpeta
            playlist_title = info.get('playlist_title') or info.get('title', 'playlist')
            # Sanitizar el nombre (yt-dlp ya lo hace con restrictfilenames)
            from yt_dlp.utils import sanitize_filename
            sanitized_playlist_name = sanitize_filename(playlist_title, restricted=True)
            result['playlist_folder'] = sanitized_playlist_name
            result['filename'] = None
        else:
            # Para videos individuales
            temp_path = ydl.prepare_filename(info)
            sanitized_base = os.path.splitext(os.path.basename(temp_path))[0]
            
            if format_type == 'audio':
                filename = f"{sanitized_base}.mp3"
            else:
                filename = f"{sanitized_base}.mp4"
            
            result['filename'] = filename
        
        return result


def check_cookies_exist() -> bool:
    """Verifica si existe el archivo de cookies."""
    return os.path.exists(COOKIES_FILE)


def save_cookies(content: bytes) -> None:
    """
    Guarda archivo de cookies.
    
    Args:
        content: Contenido del archivo de cookies
        
    Raises:
        ValueError: Si el formato no es válido
    """
    # Validar formato Netscape
    text = content.decode('utf-8', errors='ignore')
    if not text.startswith('# Netscape HTTP Cookie File') and not text.startswith('# HTTP Cookie File'):
        raise ValueError('El archivo no tiene formato Netscape/Mozilla válido')
    
    with open(COOKIES_FILE, 'wb') as f:
        f.write(content)
    
    logger.info("Cookies guardadas correctamente")
