"""
Router para endpoints de descarga de videos/audios.
"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, List
import os
import logging
import datetime
import time
import shutil

from ..services.queue_svc import QueueService
from ..services.history_svc import HistoryService
from ..services import ytdlp_svc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/descarga", tags=["Descargas"])

DOWNLOAD_FOLDER = '/app/downloads'
EXPIRATION_TIME = 4 * 3600  # 4 horas


# Modelos Pydantic
class VideoInfoRequest(BaseModel):
    url: str


class PlaylistInfoRequest(BaseModel):
    url: str
    max_items: int = -1  # -1 or 0 = todos, >0 = limit



class DownloadRequest(BaseModel):
    url: str
    format: str = 'video'  # 'video' or 'audio'
    quality: str = 'best'  # '4k', '1080p', '720p', 'best'
    subtitles: bool = False
    subtitle_lang: Optional[str] = None
    download_playlist: bool = False
    max_items: int = -1  # -1 or 0 = todos, >0 = limit


class CancelRequest(BaseModel):
    task_id: str


class SearchFileRequest(BaseModel):
    filename: str  # Nombre del archivo (puede ser sanitizado o no)



@router.post("/info")
async def get_video_info(request: VideoInfoRequest):
    """
    Obtiene información del video sin descargarlo.
    
    Args:
        request: URL del video
        
    Returns:
        Metadata del video (título, thumbnail, duración, etc.)
    """
    try:
        logger.info(f"Obteniendo info de: {request.url}")
        info = ytdlp_svc.get_video_info(request.url)
        return info
    except Exception as e:
        logger.error(f"Error obteniendo info: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/playlist-info")
async def get_playlist_info(request: PlaylistInfoRequest):
    """
    Obtiene información de una playlist sin descargarla.
    
    Args:
        request: URL de la playlist y límite opcional de items
        
    Returns:
        Metadata de la playlist y lista de videos con sus URLs individuales
    """
    try:
        logger.info(f"Obteniendo info de playlist: {request.url} (max_items: {request.max_items})")
        info = ytdlp_svc.get_playlist_info(request.url, request.max_items)
        return info
    except ValueError as e:
        logger.error(f"Error: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error obteniendo info de playlist: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/search-youtube")
async def search_youtube(query: str, limit: int = 5):
    """
    Busca videos en YouTube y retorna sus URLs y metadata.
    
    Args:
        query: Término de búsqueda
        limit: Número máximo de resultados (1-20, default: 5)
        
    Returns:
        Lista de videos encontrados con URLs, títulos, thumbnails, etc.
    """
    try:
        if not query or not query.strip():
            raise HTTPException(status_code=400, detail="El parámetro 'query' no puede estar vacío")
        
        logger.info(f"Búsqueda en YouTube: '{query}' (limit: {limit})")
        results = ytdlp_svc.search_videos(query, limit)
        return results
    except ValueError as e:
        logger.error(f"Error de validación: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error en búsqueda de YouTube: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))



@router.post("/iniciar")
async def start_download(request: DownloadRequest):
    """
    Inicia una descarga (encolándola).
    
    Args:
        request: Parámetros de descarga
        
    Returns:
        Task ID para consultar el estado
    """
    try:
        # Procesar URL antes de encolar
        processed_url = ytdlp_svc.process_url(request.url)
        
        queue = QueueService()
        
        # Determinar tipo de job
        if request.format == 'audio':
            job_type = 'download_audio'
            priority = QueueService.PRIORITY_NORMAL
        else:
            job_type = 'download_video'
            priority = QueueService.PRIORITY_NORMAL
        
        # Si es playlist, prioridad baja
        if request.download_playlist:
            # PLAYLIST EXPLOSION: Crear trabajos individuales para cada video
            logger.info(f"Explosión de playlist iniciada para: {processed_url}")
            
            # Obtener info de la playlist
            playlist_info = ytdlp_svc.get_playlist_info(processed_url, request.max_items)
            
            # Crear trabajo padre (no se procesa, solo rastrea)
            from yt_dlp.utils import sanitize_filename
            playlist_folder_name = sanitize_filename(playlist_info['playlist_title'], restricted=True)
            
            parent_job_id = queue.create_job(
                job_type='playlist_batch',
                url=processed_url,
                parameters={
                    'playlist_title': playlist_info['playlist_title'],
                    'playlist_folder': playlist_folder_name,
                    'format': request.format,
                    'total_videos': playlist_info['returned_videos']
                },
                priority=QueueService.PRIORITY_LOW
            )
            
            # Crear trabajos hijos para cada video
            playlist_output_dir = f'/app/downloads/{playlist_folder_name}'
            
            for video in playlist_info['videos']:
                child_params = {
                    'quality': request.quality,
                    'subtitles': request.subtitles,
                    'subtitle_lang': request.subtitle_lang,
                    'download_playlist': False,  # Es un video individual
                    'max_items': -1,
                    'custom_output_dir': playlist_output_dir,
                    'video_title': video['title'],  # Para status granular
                    'video_index': video['index']
                }
                
                queue.create_job(
                    job_type=job_type,
                    url=video['url'],
                    parameters=child_params,
                    priority=QueueService.PRIORITY_LOW,
                    parent_job_id=parent_job_id
                )
            
            logger.info(f"Playlist explotada: {parent_job_id} con {len(playlist_info['videos'])} videos")
            return {"task_id": parent_job_id}
        
        # Descarga normal (video/audio individual)
        # Crear job
        job_id = queue.create_job(
            job_type=job_type,
            url=processed_url,
            parameters={
                'quality': request.quality,
                'subtitles': request.subtitles,
                'subtitle_lang': request.subtitle_lang,
                'download_playlist': request.download_playlist,
                'max_items': request.max_items
            },
            priority=priority
        )
        
        logger.info(f"Descarga encolada: {job_id}")
        return {"task_id": job_id}
        
    except Exception as e:
        logger.error(f"Error iniciando descarga: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cancel")
async def cancel_download(request: CancelRequest):
    """
    Cancela una descarga.
    
    Args:
        request: Task ID a cancelar
        
    Returns:
        Mensaje de confirmación
    """
    try:
        queue = QueueService()
        success = queue.cancel_job(request.task_id)
        
        if success:
            return {"message": "Cancelación solicitada"}
        else:
            raise HTTPException(status_code=404, detail="Tarea no encontrada o no se puede cancelar")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error cancelando descarga: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status/{task_id}")
async def get_download_status(task_id: str):
    """
    Obtiene el estado de una descarga.
    
    Args:
        task_id: ID del trabajo
        
    Returns:
        Estado actual del trabajo
    """
    try:
        queue = QueueService()
        status = queue.get_job_status(task_id)
        
        if not status:
            raise HTTPException(status_code=404, detail="Tarea no encontrada")
        
        # Si es un playlist_batch, retornar status granular
        if status.get("type") == "playlist_batch":
            children = queue.get_child_jobs(task_id)
            
            items = []
            for child in children:
                params = child.get('metadata', {}).get('parameters', {})
                items.append({
                    "id": child['id'],
                    "title": params.get('video_title', 'Video'),
                    "index": params.get('video_index', 0),
                    "url": child.get('url', ''),
                    "status": child['status'],
                    "progress": child.get('progress', 0),
                    "speed": child.get('speed'),
                    "eta": child.get('eta'),
                    "filename": child.get('output_file'),
                    "error": child.get('error')
                })
            
            # Ordenar por índice
            items.sort(key=lambda x: x.get('index', 0))
            
            return {
                "id": task_id,
                "type": "playlist",
                "status": status["status"],
                "progress": status.get("progress", 0),
                "filename": status.get("output_file"),  # El ZIP cuando esté listo
                "playlist_folder": status['metadata']['parameters'].get('playlist_folder'),
                "playlist_title": status['metadata']['parameters'].get('playlist_title'),
                "total_count": status['metadata'].get('total_count', 0),
                "completed_count": status['metadata'].get('completed_count', 0),
                "failed_count": status['metadata'].get('failed_count', 0),
                "items": items
            }
        
        # Para trabajos individuales, mantener formato original
        return {
            "status": status["status"],
            "progress": status.get("progress", 0),
            "speed": status.get("speed"),
            "eta": status.get("eta"),
            "filename": status.get("output_file"),
            "is_playlist": status.get("is_playlist", False),
            "playlist_index": status.get("playlist_index"),
            "playlist_count": status.get("playlist_count"),
            "error": status.get("error")
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error obteniendo estado: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/suggestions")
async def get_suggestions(limit: int = 5):
    """
    Obtiene sugerencias de descarga basadas en el historial.
    Filtra videos ya descargados para evitar repeticiones.
    
    Args:
        limit: Número de sugerencias
        
    Returns:
        Lista de videos sugeridos y la razón (query)
    """
    try:
        history_svc = HistoryService()
        query = history_svc.get_recommendation_query()
        
        if not query:
            # Fallback si no hay historial suficiente
            return {
                "reason": "no_history",
                "query": None,
                "results": []
            }
            
        logger.info(f"Buscando sugerencias para: {query}")
        
        search_results = ytdlp_svc.search_videos(query, limit * 2)
        
        # Filtrar videos ya descargados
        from yt_dlp.utils import sanitize_filename
        filtered_results = []
        
        for video in search_results['results']:
            title = video.get('title', '')
            if not title:
                continue
                
            # Sanitizar título como lo hace yt-dlp
            sanitized_title = sanitize_filename(title, restricted=True)
            
            # Buscar si existe archivo con ese título en downloads
            file_exists = False
            for root, dirs, files in os.walk(DOWNLOAD_FOLDER):
                for filename in files:
                    file_base = os.path.splitext(filename)[0]
                    
                    # Comparar título sanitizado con nombre de archivo
                    if sanitized_title.lower() == file_base.lower():
                        file_exists = True
                        logger.debug(f"Video ya descargado (omitido): {title}")
                        break
                
                if file_exists:
                    break
            
            # Solo añadir si NO existe
            if not file_exists:
                filtered_results.append(video)
                
                # Detenerse si ya tenemos suficientes
                if len(filtered_results) >= limit:
                    break
        
        logger.info(f"Sugerencias filtradas: {len(filtered_results)} de {len(search_results['results'])} originales")
        
        return {
            "reason": f"Based on your history: {query}",
            "query": query,
            "results": filtered_results
        }
        
    except Exception as e:
        logger.error(f"Error obteniendo sugerencias: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/search")
async def search_file(request: SearchFileRequest):
    """
    Busca un archivo en el directorio de descargas (incluyendo subcarpetas).
    
    Args:
        request: Nombre del archivo a buscar (puede ser sanitizado o no)
        
    Returns:
        Ruta relativa del archivo encontrado o error 404
    """
    try:
        from yt_dlp.utils import sanitize_filename
        
        search_term = request.filename.strip()
        
        # Sanitizar el término de búsqueda (como lo haría yt-dlp)
        sanitized_search = sanitize_filename(search_term, restricted=True)
        
        # Remover extensión del término de búsqueda si existe
        search_base = os.path.splitext(search_term)[0]
        sanitized_base = os.path.splitext(sanitized_search)[0]
        
        logger.info(f"Buscando archivo: '{search_term}' (sanitizado: '{sanitized_search}')")
        
        # Buscar recursivamente en downloads
        for root, dirs, files in os.walk(DOWNLOAD_FOLDER):
            for filename in files:
                file_base = os.path.splitext(filename)[0]
                
                # Comparar con múltiples variantes
                if (search_term.lower() in filename.lower() or
                    sanitized_search.lower() in filename.lower() or
                    search_base.lower() == file_base.lower() or
                    sanitized_base.lower() == file_base.lower()):
                    
                    # Obtener ruta relativa desde DOWNLOAD_FOLDER
                    full_path = os.path.join(root, filename)
                    relative_path = os.path.relpath(full_path, DOWNLOAD_FOLDER)
                    
                    logger.info(f"Archivo encontrado: {relative_path}")
                    
                    return {
                        "found": True,
                        "path": relative_path,
                        "filename": filename,
                        "full_path": full_path
                    }
        
        logger.warning(f"Archivo no encontrado: '{search_term}'")
        raise HTTPException(status_code=404, detail=f"Archivo no encontrado: {search_term}")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error buscando archivo: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/historial")
async def get_history():
    """
    Lista todos los archivos descargados disponibles.
    
    Returns:
        Lista de archivos con metadata
    """
    try:
        files = []
        now = time.time()
        
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
        return files
        
    except Exception as e:
        logger.error(f"Error leyendo historial: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/archivo/{filename:path}")
async def download_file(filename: str):
    """
    Descarga un archivo.
    
    Args:
        filename: Nombre del archivo
        
    Returns:
        Archivo para descarga
    """
    try:
        path = os.path.join(DOWNLOAD_FOLDER, filename)
        
        if not os.path.exists(path):
            raise HTTPException(status_code=404, detail="Archivo no encontrado")
        
        # Touch para actualizar timestamp (evitar expiración)
        os.utime(path, None)
        
        return FileResponse(
            path=path,
            filename=os.path.basename(path),
            media_type='application/octet-stream'
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error descargando archivo: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/archivo/eliminar/{filename:path}")
async def delete_file(filename: str):
    """
    Elimina un archivo o carpeta.
    
    Args:
        filename: Nombre del archivo/carpeta
        
    Returns:
        Mensaje de confirmación
    """
    try:
        path = os.path.join(DOWNLOAD_FOLDER, filename)
        
        if not os.path.exists(path):
            raise HTTPException(status_code=404, detail="Elemento no encontrado")
        
        if os.path.isfile(path):
            os.remove(path)
        elif os.path.isdir(path):
            shutil.rmtree(path)
        
        return {"message": "Elemento eliminado"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error eliminando elemento: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/view/{filename:path}")
async def view_file(filename: str):
    """
    Visualiza un archivo (para videos/audio).
    
    Args:
        filename: Nombre del archivo
        
    Returns:
        Archivo para visualización en navegador
    """
    try:
        path = os.path.join(DOWNLOAD_FOLDER, filename)
        
        if not os.path.exists(path):
            raise HTTPException(status_code=404, detail="Archivo no encontrado")
        
        # Touch para actualizar timestamp
        os.utime(path, None)
        
        # Determinar media_type según extensión
        ext = os.path.splitext(filename)[1].lower()
        media_type_map = {
            '.mp4': 'video/mp4',
            '.webm': 'video/webm',
            '.mkv': 'video/x-matroska',
            '.mp3': 'audio/mpeg',
            '.m4a': 'audio/mp4',
            '.wav': 'audio/wav',
            '.ogg': 'audio/ogg'
        }
        media_type = media_type_map.get(ext, 'application/octet-stream')
        
        # NO incluir filename para que se abra inline en el navegador
        return FileResponse(
            path=path,
            media_type=media_type
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error visualizando archivo: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
