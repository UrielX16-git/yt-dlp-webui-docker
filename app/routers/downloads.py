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
from ..services import ytdlp_svc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/descarga", tags=["Descargas"])

DOWNLOAD_FOLDER = '/app/downloads'
EXPIRATION_TIME = 4 * 3600  # 4 horas


# Modelos Pydantic
class VideoInfoRequest(BaseModel):
    url: str


class DownloadRequest(BaseModel):
    url: str
    format: str = 'video'  # 'video' or 'audio'
    quality: str = 'best'  # '4k', '1080p', '720p', 'best'
    subtitles: bool = False
    subtitle_lang: Optional[str] = None
    download_playlist: bool = False


class CancelRequest(BaseModel):
    task_id: str


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
            priority = QueueService.PRIORITY_LOW
        
        # Crear job
        job_id = queue.create_job(
            job_type=job_type,
            url=processed_url,
            parameters={
                'quality': request.quality,
                'subtitles': request.subtitles,
                'subtitle_lang': request.subtitle_lang,
                'download_playlist': request.download_playlist
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
        
        # Adaptar formato para compatibilidad con frontend
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
