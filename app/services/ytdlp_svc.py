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


class YtDlpLogger:
    """Logger que canaliza mensajes de yt-dlp al logger de Python."""
    def debug(self, msg: str):
        # Evitar inundar los logs con debug excesivo
        pass

    def info(self, msg: str):
        logger.info(f"[yt-dlp] {msg}")

    def warning(self, msg: str):
        logger.warning(f"[yt-dlp] {msg}")

    def error(self, msg: str):
        logger.error(f"[yt-dlp] {msg}")


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
    """
    import re
    
    # Twitch Dashboard to Public Video
    twitch_dash_regex = r'dashboard\.twitch\.tv/u/[^/]+/content/video-producer/edit/(\d+)'
    match = re.search(twitch_dash_regex, url)
    if match:
        video_id = match.group(1)
        processed = f'https://www.twitch.tv/videos/{video_id}'
        logger.info(f"URL procesada: Twitch Dashboard → {processed}")
        return processed
    
    return url


def _get_base_ydl_opts(extra_opts: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Retorna la configuración base moderna y optimizada para YoutubeDL."""
    opts = {
        'logger': YtDlpLogger(),
        'quiet': False,
        'no_warnings': False,
        'js_runtimes': {
            'deno': {}
        },
        # Aceleración de descargas multi-fragmento (DASH/HLS)
        'concurrent_fragment_downloads': 4,
        'buffersize': 1024 * 1024,
        'http_chunk_size': 10485760,
    }
    if extra_opts:
        opts.update(extra_opts)
    return opts


def get_video_info(url: str) -> Dict[str, Any]:
    """
    Obtiene información del video sin descargarlo.
    
    Args:
        url: URL del video
        
    Returns:
        Diccionario con metadata del video
    """
    url = process_url(url)
    
    ydl_opts = _get_base_ydl_opts({
        'noplaylist': True,
        'extract_flat': False,
    })
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                raise ValueError("No se pudo extraer información del video")
            
            # Extraer idiomas de subtítulos disponibles
            subtitles = set()
            if 'subtitles' in info and info['subtitles']:
                subtitles.update(info['subtitles'].keys())
            if 'automatic_captions' in info and info['automatic_captions']:
                subtitles.update(info['automatic_captions'].keys())
            
            sorted_subs = sorted(list(subtitles))
            
            return {
                'title': info.get('title'),
                'thumbnail': info.get('thumbnail'),
                'duration': format_duration(info.get('duration')),
                'uploader': info.get('uploader') or info.get('channel'),
                'view_count': info.get('view_count'),
                'subtitles': sorted_subs
            }
            
    except yt_dlp.utils.DownloadError as e:
        error_msg = str(e)
        logger.error(f"Error en get_video_info: {error_msg}")
        if "Sign in to confirm your age" in error_msg:
            raise ValueError("Error: El video tiene restricción de edad en YouTube.")
        elif "Requested format is not available" in error_msg:
            raise ValueError("Error: El formato solicitado no está disponible.")
        elif "Private video" in error_msg:
            raise ValueError("Error: Este video es privado.")
        elif "Video unavailable" in error_msg:
            raise ValueError("Error: Video no disponible o bloqueado en esta región.")
        else:
            raise ValueError(f"Error al obtener info: {error_msg}")


def get_playlist_info(url: str, max_items: int = -1) -> Dict[str, Any]:
    """
    Obtiene información de una playlist sin descargarla.
    
    Args:
        url: URL de la playlist
        max_items: Límite de items a retornar (-1 o 0 = todos, >0 = límite)
        
    Returns:
        Diccionario con metadata de la playlist y lista de videos
    """
    url = process_url(url)
    
    ydl_opts = _get_base_ydl_opts({
        'extract_flat': True,
    })
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                raise ValueError('No se pudo obtener información de la URL')
            
            # Verificar que sea una playlist o canal
            if info.get('_type') not in ('playlist', 'multi_video'):
                raise ValueError('La URL no corresponde a una playlist o lista de reproducción')
            
            entries = info.get('entries', []) or []
            if max_items > 0:
                entries = entries[:max_items]
            
            videos = []
            for idx, entry in enumerate(entries, 1):
                if entry:
                    video_id = entry.get('id')
                    video_url = entry.get('url') or (f"https://www.youtube.com/watch?v={video_id}" if video_id else None)
                    if not video_url and entry.get('webpage_url'):
                        video_url = entry.get('webpage_url')
                    
                    videos.append({
                        'index': idx,
                        'url': video_url,
                        'title': entry.get('title', 'Sin título'),
                        'duration': format_duration(entry.get('duration')),
                        'thumbnail': entry.get('thumbnail'),
                        'uploader': entry.get('uploader') or entry.get('channel'),
                    })
            
            return {
                'playlist_title': info.get('title', 'Playlist'),
                'playlist_uploader': info.get('uploader') or info.get('channel'),
                'total_videos': len(info.get('entries', [])),
                'returned_videos': len(videos),
                'videos': videos
            }
    except yt_dlp.utils.DownloadError as e:
        error_msg = str(e)
        logger.error(f"Error en get_playlist_info: {error_msg}")
        if "Sign in to confirm your age" in error_msg:
            raise ValueError("Error: Playlist o videos con restricción de edad.")
        else:
            raise ValueError(f"Error al obtener playlist: {error_msg}")


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
    url = process_url(url)
    
    os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)
    
    # Configurar template de salida
    if custom_output_dir:
        os.makedirs(custom_output_dir, exist_ok=True)
        output_template = f'{custom_output_dir}/%(title)s.%(ext)s'
    elif download_playlist:
        output_template = f'{DOWNLOAD_FOLDER}/%(playlist_title)s/%(title)s.%(ext)s'
    else:
        output_template = f'{DOWNLOAD_FOLDER}/%(title)s.%(ext)s'
    
    ydl_opts = _get_base_ydl_opts({
        'outtmpl': output_template,
        'noplaylist': not download_playlist,
        'ignoreerrors': False if not download_playlist else True,
        'restrictfilenames': True,
        'writethumbnail': True,
        'add_metadata': True,
    })

    # Aplicar límite de items si es playlist y max_items > 0
    if download_playlist and max_items > 0:
        ydl_opts['playlistend'] = max_items
    
    # Progress hook
    if progress_callback:
        ydl_opts['progress_hooks'] = [progress_callback]
    
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
        postprocessors = ydl_opts.get('postprocessors', [])
        postprocessors.extend([
            {
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            },
            {
                'key': 'EmbedThumbnail',
                'already_have_thumbnail': False,
            },
            {
                'key': 'FFmpegMetadata',
                'add_metadata': True,
            }
        ])
        
        ydl_opts.update({
            'format': 'bestaudio/best',
            'format_sort': ['abr', 'acodec:mp3:m4a:opus'],
            'postprocessors': postprocessors,
        })
    else:  # video
        # Priorizar resolución pedida, luego fps, y preferir H.264/VP9 y AAC/Opus en MP4
        format_sort = ['res', 'fps', 'vcodec:h264:vp9', 'acodec:m4a:opus']
        
        if quality == '4k':
            fmt = 'bv*[height<=2160]+ba/b[height<=2160]/bv*+ba/b'
        elif quality == '1080p':
            fmt = 'bv*[height<=1080]+ba/b[height<=1080]/b[height<=1080]/bv*+ba/b'
        elif quality == '720p':
            fmt = 'bv*[height<=720]+ba/b[height<=720]/b[height<=720]/bv*+ba/b'
        else:
            fmt = 'bv*+ba/b'
        
        current_postprocessors = ydl_opts.get('postprocessors', [])
        current_postprocessors.extend([
            {
                'key': 'EmbedThumbnail',
                'already_have_thumbnail': False,
            },
            {
                'key': 'FFmpegMetadata',
                'add_metadata': True,
            }
        ])
        
        ydl_opts.update({
            'format': fmt,
            'format_sort': format_sort,
            'merge_output_format': 'mp4',
            'postprocessors': current_postprocessors
        })
    
    # Ejecutar descarga
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if not info:
                raise ValueError("No se pudo obtener el contenido del video")
            
            result = {
                'is_playlist': download_playlist and info.get('_type') == 'playlist',
                'filename': None,
                'playlist_folder': None,
                'files': [],
                'info': info,
                'format_type': format_type
            }
            
            if result['is_playlist']:
                playlist_title = info.get('playlist_title') or info.get('title', 'playlist')
                from yt_dlp.utils import sanitize_filename
                sanitized_playlist_name = sanitize_filename(playlist_title, restricted=True)
                result['playlist_folder'] = sanitized_playlist_name
                result['filename'] = None
            else:
                filename = None
                # Obtener la ruta real final producida por yt-dlp
                requested = info.get('requested_downloads')
                if requested and isinstance(requested, list) and len(requested) > 0:
                    filepath = requested[0].get('filepath')
                    if filepath and os.path.exists(filepath):
                        filename = os.path.basename(filepath)
                
                if not filename:
                    temp_path = ydl.prepare_filename(info)
                    sanitized_base = os.path.splitext(os.path.basename(temp_path))[0]
                    ext = 'mp3' if format_type == 'audio' else 'mp4'
                    filename = f"{sanitized_base}.{ext}"
                
                result['filename'] = filename
            
            return result
            
    except yt_dlp.utils.DownloadError as e:
        error_msg = str(e)
        logger.error(f"Error en download_media: {error_msg}")
        if "Sign in to confirm your age" in error_msg:
            raise ValueError("Descarga fallida: El video requiere confirmación de edad.")
        elif "Requested format is not available" in error_msg:
            raise ValueError("Descarga fallida: El formato solicitado no está disponible.")
        else:
            raise ValueError(f"Descarga fallida: {error_msg}")


def search_videos(query: str, max_results: int = 5) -> Dict[str, Any]:
    """
    Busca videos en YouTube usando yt-dlp.
    
    Args:
        query: Término de búsqueda
        max_results: Número máximo de resultados (default: 5)
        
    Returns:
        Diccionario con lista de videos encontrados
    """
    if not query or not query.strip():
        raise ValueError('El término de búsqueda no puede estar vacío')
    
    if max_results < 1 or max_results > 20:
        raise ValueError('max_results debe estar entre 1 y 20')
    
    search_url = f'ytsearch{max_results}:{query}'
    
    ydl_opts = _get_base_ydl_opts({
        'extract_flat': True,
    })
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(search_url, download=False)
        entries = info.get('entries', []) or []
        
        results = []
        for entry in entries:
            if entry:
                video_id = entry.get('id')
                results.append({
                    'title': entry.get('title', 'Sin título'),
                    'url': entry.get('url') or (f'https://www.youtube.com/watch?v={video_id}' if video_id else ''),
                    'id': video_id,
                    'duration': format_duration(entry.get('duration')),
                    'thumbnail': entry.get('thumbnail') or (entry.get('thumbnails', [{}])[0].get('url') if entry.get('thumbnails') else None),
                    'uploader': entry.get('uploader') or entry.get('channel'),
                    'view_count': entry.get('view_count'),
                    'upload_date': entry.get('upload_date')
                })
        
        logger.info(f"Búsqueda '{query}': {len(results)} resultados")
        
        return {
            'query': query,
            'results': results,
            'count': len(results)
        }
