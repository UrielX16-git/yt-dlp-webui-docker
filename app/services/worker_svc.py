"""
Worker daemon que procesa jobs de descarga de la cola de forma secuencial.
Se ejecuta como proceso separado en background.
"""
import asyncio
import logging
import signal
import sys
import os
import shutil
import time
from .queue_svc import QueueService
from .history_svc import HistoryService
from . import ytdlp_svc

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

logger = logging.getLogger(__name__)


class Worker:
    """Worker para procesar jobs de descarga de la cola."""
    
    def __init__(self):
        self.queue = QueueService()
        self.running = True
        logger.info("[WORKER] Worker inicializado")
    
    def handle_shutdown(self, signum, frame):
        """Maneja señales de shutdown gracefully."""
        logger.info("[WORKER] Recibida señal de shutdown, terminando...")
        self.running = False
    
    async def process_job(self, job_id: str):
        """
        Procesa un job de descarga de la cola.
        
        Args:
            job_id: ID del job a procesar
        """
        try:
            job_data = self.queue.get_job_status(job_id)
            if not job_data:
                logger.error(f"[WORKER] Job no encontrado: {job_id}")
                return
            
            logger.info("=" * 80)
            logger.info(f"[WORKER] Iniciando job: {job_id}")
            logger.info(f"[WORKER] Tipo: {job_data['type']}")
            logger.info(f"[WORKER] URL: {job_data['url']}")
            logger.info(f"[WORKER] Prioridad: {job_data['priority']}")
            logger.info("=" * 80)
            
            self.queue.update_job_status(job_id, "downloading", progress=0)
            
            job_type = job_data["type"]
            url = job_data["url"]
            params = job_data["metadata"]["parameters"]
            
            # Progress callback para actualizar estado
            def progress_hook(d):
                # Verificar si se solicitó cancelación
                current_job = self.queue.get_job_status(job_id)
                if current_job and current_job.get('cancel_requested'):
                    raise Exception("DownloadCancelled")
                
                if d['status'] == 'downloading':
                    try:
                        p = d.get('_percent_str', '0%').replace('%', '')
                        progress = float(p)
                        speed = d.get('_speed_str', 'N/A')
                        eta = d.get('_eta_str', 'N/A')
                        
                        # Actualizar estado en Valkey
                        self.queue.update_job_status(
                            job_id,
                            "downloading",
                            progress=progress,
                            speed=speed,
                            eta=eta
                        )
                        
                        # Info de playlist
                        info = d.get('info_dict', {})
                        if 'playlist_index' in info and 'playlist_count' in info:
                            self.queue.update_job_status(
                                job_id,
                                "downloading",
                                playlist_index=info['playlist_index'],
                                playlist_count=info['playlist_count']
                            )
                    except Exception as e:
                        logger.warning(f"[WORKER] Error actualizando progreso: {e}")
                        
                elif d['status'] == 'finished':
                    self.queue.update_job_status(job_id, "processing", progress=100)
            
            # Ejecutar descarga
            result = None
            try:
                if job_type == "download_video":
                    result = ytdlp_svc.download_media(
                        url=url,
                        format_type='video',
                        quality=params.get('quality', 'best'),
                        subtitles=params.get('subtitles', False),
                        subtitle_lang=params.get('subtitle_lang'),
                        download_playlist=params.get('download_playlist', False),
                        max_items=params.get('max_items', -1),
                        custom_output_dir=params.get('custom_output_dir'),
                        progress_callback=progress_hook
                    )
                
                elif job_type == "download_audio":
                    result = ytdlp_svc.download_media(
                        url=url,
                        format_type='audio',
                        quality=params.get('quality', 'best'),
                        subtitles=params.get('subtitles', False),
                        subtitle_lang=params.get('subtitle_lang'),
                        download_playlist=params.get('download_playlist', False),
                        max_items=params.get('max_items', -1),
                        custom_output_dir=params.get('custom_output_dir'),
                        progress_callback=progress_hook
                    )
                
                elif job_type == "playlist_batch":
                    # Los playlist_batch no se procesan, solo rastrean
                    logger.info(f"[WORKER] playlist_batch job {job_id} - skipping (solo tracker)")
                    return
                
                else:
                    raise ValueError(f"Tipo de job no soportado: {job_type}")
            
            except Exception as download_error:
                # Si es cancelación, re-lanzar para que sea manejada abajo
                if "DownloadCancelled" in str(download_error):
                    raise
                # Si yt-dlp falla, también re-lanzar
                raise
            
            # Validar que result no sea None (solo si no hubo excepción)
            if result is None:
                raise Exception("La descarga falló sin retornar resultado")
            
            # Marcar hijo como completado
            output_file = result.get('filename')
            
            self.queue.update_job_status(
                job_id,
                "completed",
                progress=100,
                output_file=output_file,
                is_playlist=result.get('is_playlist', False)
            )
            
            logger.info(f"[WORKER] Job completado exitosamente: {job_id}")
            
            # Guardar en historial
            try:
                history_svc = HistoryService()
                info = result.get('info', {})
                # Asegurar formato
                info['format_type'] = result.get('format_type', 'video')
                history_svc.add_entry(info)
            except Exception as hist_err:
                logger.error(f"[WORKER] Error guardando historial: {hist_err}")
            
            # Si este job tiene un parent, actualizar progreso del padre
            parent_job_id = job_data['metadata'].get('parent_job_id')
            if parent_job_id:
                logger.info(f"[WORKER] Actualizando progreso del padre: {parent_job_id}")
                self.queue.check_update_parent_progress(parent_job_id)
                
                # Verificar si el padre está listo para ZIP
                parent_data = self.queue.get_job_status(parent_job_id)
                if parent_data and parent_data['status'] == 'ready_for_zip':
                    logger.info(f"[WORKER] Padre {parent_job_id} listo, creando ZIP...")
                    self._create_playlist_zip(parent_job_id)
            
            logger.info("=" * 80)
            
        except Exception as e:
            if "DownloadCancelled" in str(e):
                self.queue.update_job_status(
                    job_id,
                    "cancelled",
                    error="Cancelado por usuario"
                )
                logger.info(f"[WORKER] Tarea {job_id} cancelada por usuario")
            else:
                logger.error("=" * 80)
                logger.error(f"[WORKER] Error procesando job {job_id}: {str(e)}")
                logger.error("=" * 80)
                
                self.queue.update_job_status(
                    job_id,
                    "failed",
                    error=str(e)
                )
    
    def _create_playlist_zip(self, parent_job_id: str):
        """
        Crea un archivo ZIP para una playlist completada.
        
        Args:
            parent_job_id: ID del trabajo padre de la playlist
        """
        try:
            parent_data = self.queue.get_job_status(parent_job_id)
            if not parent_data:
                logger.error(f"[WORKER] Parent job no encontrado: {parent_job_id}")
                return
            
            playlist_folder = parent_data['metadata']['parameters'].get('playlist_folder')
            if not playlist_folder:
                logger.error(f"[WORKER] No se encontró playlist_folder en parent {parent_job_id}")
                return
            
            folder_path = os.path.join('/app/downloads', playlist_folder)
            
            if not os.path.isdir(folder_path):
                logger.error(f"[WORKER] Carpeta no existe: {folder_path}")
                self.queue.update_job_status(
                    parent_job_id,
                    "failed",
                    error="Carpeta de playlist no encontrada"
                )
                return
            
            logger.info(f"[WORKER] Comprimiendo playlist: {playlist_folder}")
            
            # Crear ZIP
            zip_path = shutil.make_archive(
                os.path.join('/app/downloads', playlist_folder),
                'zip',
                folder_path
            )
            
            zip_filename = os.path.basename(zip_path)
            logger.info(f"[WORKER] ZIP creado: {zip_filename}")
            
            # Marcar parent como completado
            self.queue.update_job_status(
                parent_job_id,
                "completed",
                progress=100,
                output_file=zip_filename
            )
            
            logger.info(f"[WORKER] Playlist {parent_job_id} completada con ZIP")
            
        except Exception as e:
            logger.error(f"[WORKER] Error creando ZIP para {parent_job_id}: {str(e)}")
            self.queue.update_job_status(
                parent_job_id,
                "failed",
                error=f"Error creando ZIP: {str(e)}"
            )
    
    
    async def run(self):
        """Loop principal del worker."""
        signal.signal(signal.SIGTERM, self.handle_shutdown)
        signal.signal(signal.SIGINT, self.handle_shutdown)
        
        logger.info("=" * 80)
        logger.info("[WORKER] Worker iniciado - esperando jobs en la cola...")
        logger.info("=" * 80)
        
        while self.running:
            try:
                # Obtener siguiente job de la cola (con prioridad)
                job_id = self.queue.get_next_job()
                
                if job_id:
                    await self.process_job(job_id)
                else:
                    # No hay jobs, esperar un segundo
                    await asyncio.sleep(1)
                
            except Exception as e:
                logger.error(f"[WORKER] Error en loop principal: {str(e)}")
                await asyncio.sleep(5)
        
        logger.info("[WORKER] Worker detenido")


async def cleanup_task():
    """Tarea de limpieza automática que se ejecuta cada hora."""
    from datetime import datetime
    
    logger.info("[CLEANUP] Iniciando tarea de limpieza automática (ejecución cada 10 minutos)")
    
    # Esperar 5 minutos antes de la primera limpieza
    await asyncio.sleep(300)
    
    DOWNLOAD_FOLDER = '/app/downloads'
    EXPIRATION_TIME = 4 * 3600  # 4 horas
    
    while True:
        try:
            logger.info("[CLEANUP] Ejecutando limpieza programada...")
            
            now = time.time()
            files_deleted = 0
            space_freed = 0
            
            error_count = 0
            errors = []
            
            for f in os.listdir(DOWNLOAD_FOLDER):
                path = os.path.join(DOWNLOAD_FOLDER, f)
                if os.path.exists(path):
                    try:
                        stat = os.stat(path)
                        age = now - stat.st_mtime
                        
                        if age > EXPIRATION_TIME:
                            try:
                                if os.path.isfile(path):
                                    size = os.path.getsize(path)
                                    os.remove(path)
                                    space_freed += size
                                    files_deleted += 1
                                elif os.path.isdir(path):
                                    # Calcular tamaño de carpeta
                                    for dirpath, dirnames, filenames in os.walk(path):
                                        for fname in filenames:
                                            fp = os.path.join(dirpath, fname)
                                            space_freed += os.path.getsize(fp)
                                    
                                    shutil.rmtree(path)
                                    files_deleted += 1
                                
                                logger.info(f"[CLEANUP] Elemento expirado eliminado: {f}")
                            except Exception as e:
                                error_count += 1
                                errors.append(f"{f}: {str(e)}")
                    except Exception as stat_err:
                         # Error obteniendo stats (file not found race condition)
                         continue

            if error_count > 0:
                logger.warning(f"[CLEANUP] Se encontraron {error_count} errores al eliminar archivos.")
                for err in errors[:3]:
                    logger.warning(f"[CLEANUP] Detalle error: {err}")
            
            logger.info(
                f"[CLEANUP] Limpieza completada - "
                f"Archivos eliminados: {files_deleted}, "
                f"Espacio liberado: {space_freed / (1024 * 1024):.2f} MB"
            )
            
        except Exception as e:
            logger.error(f"[CLEANUP] Error en tarea de limpieza: {str(e)}")
        
        # Esperar 10 minutos antes de la siguiente limpieza
        await asyncio.sleep(600)


if __name__ == "__main__":
    import asyncio
    
    # Asegurar que los directorios existen
    os.makedirs("/app/downloads", exist_ok=True)
    
    async def main():
        """Ejecuta worker y tarea de limpieza en paralelo."""
        worker = Worker()
        
        # Ejecutar worker y cleanup en paralelo
        await asyncio.gather(
            worker.run(),
            cleanup_task()
        )
    
    asyncio.run(main())
