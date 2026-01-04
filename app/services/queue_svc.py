"""
Servicio de gestión de cola usando Valkey para yt-dlp.
Maneja creación, actualización y consulta de jobs de descarga.
"""
import json
import uuid
import os
from datetime import datetime
from typing import Dict, List, Optional, Any
import valkey
import logging

logger = logging.getLogger(__name__)


class QueueService:
    """Servicio para gestionar cola de descargas con Valkey."""
    
    # Prioridades: menor número = mayor prioridad
    PRIORITY_HIGH = 10    # Metadatos, info
    PRIORITY_NORMAL = 50  # Descargas normales
    PRIORITY_LOW = 100    # Descargas de playlist completas
    
    def __init__(self, host: str = None, port: int = 6379, db: int = 0):
        """
        Inicializa conexión con Valkey.
        
        Args:
            host: Host de Valkey (default: variable de entorno VALKEY_HOST o 'valkey')
            port: Puerto de Valkey
            db: Base de datos de Valkey
        """
        if host is None:
            host = os.getenv('VALKEY_HOST', 'valkey')
        
        self.redis = valkey.Redis(
            host=host, 
            port=port, 
            db=db, 
            decode_responses=True
        )
        logger.info(f"[QUEUE] Conectado a Valkey en {host}:{port}")
    
    def create_job(
        self, 
        job_type: str,  # 'download_video', 'download_audio', 'playlist_batch'
        url: str,
        parameters: Dict[str, Any],
        priority: int = PRIORITY_NORMAL,
        parent_job_id: Optional[str] = None
    ) -> str:
        """
        Crea un nuevo job y lo agrega a la cola con prioridad.
        
        Args:
            job_type: Tipo de operación (download_video, download_audio, etc.)
            url: URL del video/audio a descargar
            parameters: Parámetros adicionales (quality, subtitles, etc.)
            priority: Prioridad del job (menor = mayor prioridad)
            
        Returns:
            ID del job creado
        """
        job_id = str(uuid.uuid4())
        
        job_data = {
            "id": job_id,
            "status": "pending",
            "type": job_type,
            "priority": priority,
            "created_at": datetime.utcnow().isoformat(),
            "started_at": None,
            "completed_at": None,
            "progress": 0,
            "speed": None,
            "eta": None,
            "url": url,
            "output_file": None,
            "output_files": [],  # Para playlists
            "error": None,
            "is_playlist": False,
            "playlist_index": None,
            "playlist_count": None,
            "metadata": {
                "parameters": parameters,
                "parent_job_id": parent_job_id
            }
        }
        
        # Guardar job en Valkey
        self.redis.set(f"job:{job_id}", json.dumps(job_data))
        
        # Agregar a índice de pendientes con timestamp
        self.redis.zadd("pending_jobs", {job_id: datetime.utcnow().timestamp()})
        
        # Agregar a cola con prioridad (ZSET ordenado por prioridad + timestamp)
        score = priority * 1000000 + datetime.utcnow().timestamp()
        self.redis.zadd("job_queue", {job_id: score})
        
        # Si tiene parent, agregar a la lista de hijos del padre
        if parent_job_id:
            self.redis.sadd(f"parent:{parent_job_id}:children", job_id)
        
        logger.info(
            f"[QUEUE] Job creado: {job_id} - {job_type} "
            f"(prioridad: {priority}, parent: {parent_job_id}, url: {url[:50]}...)"
        )
        return job_id
    
    def get_next_job(self, timeout: int = 0) -> Optional[str]:
        """
        Obtiene el siguiente job de la cola según prioridad.
        
        Args:
            timeout: Tiempo de espera en segundos (0 = no bloqueante)
            
        Returns:
            ID del job o None si no hay jobs
        """
        result = self.redis.zpopmin("job_queue", count=1)
        
        if result:
            job_id, score = result[0]
            logger.info(f"[QUEUE] Job obtenido de la cola: {job_id}")
            return job_id
        
        return None
    
    def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """
        Obtiene el estado actual de un job.
        
        Args:
            job_id: ID del job
            
        Returns:
            Datos del job o None si no existe
        """
        job_data = self.redis.get(f"job:{job_id}")
        if not job_data:
            return None
        return json.loads(job_data)
    
    def update_job_status(
        self, 
        job_id: str, 
        status: str,
        progress: Optional[float] = None,
        speed: Optional[str] = None,
        eta: Optional[str] = None,
        output_file: Optional[str] = None,
        error: Optional[str] = None,
        is_playlist: Optional[bool] = None,
        playlist_index: Optional[int] = None,
        playlist_count: Optional[int] = None
    ):
        """
        Actualiza el estado de un job.
        
        Args:
            job_id: ID del job
            status: Nuevo estado (pending, downloading, processing, completed, failed, cancelled)
            progress: Progreso 0-100
            speed: Velocidad de descarga
            eta: Tiempo estimado de finalización
            output_file: Ruta del archivo de salida (si completó)
            error: Mensaje de error (si falló)
            is_playlist: Si es una playlist
            playlist_index: Índice actual en playlist
            playlist_count: Total de videos en playlist
        """
        job_data = self.get_job_status(job_id)
        if not job_data:
            logger.warning(f"[QUEUE] Job no encontrado para actualizar: {job_id}")
            return
        
        job_data["status"] = status
        
        if progress is not None:
            job_data["progress"] = progress
        
        if speed is not None:
            job_data["speed"] = speed
            
        if eta is not None:
            job_data["eta"] = eta
        
        if is_playlist is not None:
            job_data["is_playlist"] = is_playlist
            
        if playlist_index is not None:
            job_data["playlist_index"] = playlist_index
            
        if playlist_count is not None:
            job_data["playlist_count"] = playlist_count
        
        if status == "downloading" and not job_data["started_at"]:
            job_data["started_at"] = datetime.utcnow().isoformat()
            self.redis.zrem("pending_jobs", job_id)
            self.redis.sadd("processing_jobs", job_id)
            logger.info(f"[QUEUE] Job iniciado: {job_id}")
        
        if status in ["completed", "failed", "cancelled"]:
            job_data["completed_at"] = datetime.utcnow().isoformat()
            job_data["progress"] = 100 if status == "completed" else job_data["progress"]
            
            self.redis.srem("processing_jobs", job_id)
            
            if status == "completed":
                job_data["output_file"] = output_file
                # TTL de 4 horas para jobs completados (igual que los archivos)
                self.redis.zadd("completed_jobs", {job_id: datetime.utcnow().timestamp()})
                self.redis.expire(f"job:{job_id}", 14400)  # 4 horas
                logger.info(f"[QUEUE] Job completado: {job_id}")
            else:
                job_data["error"] = error
                # TTL de 1 hora para jobs fallidos/cancelados
                self.redis.zadd("failed_jobs", {job_id: datetime.utcnow().timestamp()})
                self.redis.expire(f"job:{job_id}", 3600)  # 1 hora
                logger.error(f"[QUEUE] Job fallido/cancelado: {job_id} - {error}")
        
        self.redis.set(f"job:{job_id}", json.dumps(job_data))
    
    def cancel_job(self, job_id: str) -> bool:
        """
        Marca un job para cancelación.
        
        Args:
            job_id: ID del job a cancelar
            
        Returns:
            True si se marcó para cancelar, False si no se pudo
        """
        job_data = self.get_job_status(job_id)
        
        if not job_data:
            return False
        
        if job_data["status"] in ["completed", "failed", "cancelled"]:
            logger.warning(f"[QUEUE] Job ya finalizado, no se puede cancelar: {job_id}")
            return False
        
        if job_data["status"] == "pending":
            # Remover de la cola
            self.redis.zrem("job_queue", job_id)
            self.redis.zrem("pending_jobs", job_id)
            
            # Marcar como cancelado
            self.update_job_status(job_id, "cancelled", error="Cancelado por usuario")
            logger.info(f"[QUEUE] Job cancelado (pending): {job_id}")
            return True
        
        if job_data["status"] in ["downloading", "processing"]:
            # Solo marcar flag de cancelación, el worker lo detectará
            job_data["cancel_requested"] = True
            self.redis.set(f"job:{job_id}", json.dumps(job_data))
            logger.info(f"[QUEUE] Cancelación solicitada para job en proceso: {job_id}")
            return True
        
        return False
    
    def get_queue_stats(self) -> Dict[str, Any]:
        """
        Obtiene estadísticas de la cola.
        
        Returns:
            Diccionario con estadísticas
        """
        return {
            "pending": self.redis.zcard("job_queue"),
            "processing": self.redis.scard("processing_jobs"),
            "completed_4h": self.redis.zcard("completed_jobs"),
            "failed_1h": self.redis.zcard("failed_jobs")
        }
    
    def get_queue_jobs(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Lista jobs pendientes en la cola ordenados por prioridad.
        
        Args:
            limit: Número máximo de jobs a retornar
            
        Returns:
            Lista de jobs con sus datos
        """
        job_ids_with_scores = self.redis.zrange("job_queue", 0, limit - 1, withscores=True)
        
        jobs = []
        for job_id, score in job_ids_with_scores:
            job_data = self.get_job_status(job_id)
            if job_data:
                job_data["queue_position"] = len(jobs) + 1
                jobs.append(job_data)
        
        return jobs
    
    def get_child_jobs(self, parent_job_id: str) -> List[Dict[str, Any]]:
        """
        Obtiene todos los trabajos hijos de un trabajo padre.
        
        Args:
            parent_job_id: ID del trabajo padre
            
        Returns:
            Lista de datos de trabajos hijos
        """
        child_ids = self.redis.smembers(f"parent:{parent_job_id}:children")
        
        children = []
        for child_id in child_ids:
            child_data = self.get_job_status(child_id)
            if child_data:
                children.append(child_data)
        
        return children
    
    def check_update_parent_progress(self, parent_job_id: str):
        """
        Verifica y actualiza el progreso del trabajo padre basado en sus hijos.
        Si todos los hijos están completos, marca al padre como completo.
        
        Args:
            parent_job_id: ID del trabajo padre
        """
        parent_data = self.get_job_status(parent_job_id)
        if not parent_data:
            logger.warning(f"[QUEUE] Parent job no encontrado: {parent_job_id}")
            return
        
        children = self.get_child_jobs(parent_job_id)
        
        if not children:
            logger.warning(f"[QUEUE] Parent {parent_job_id} no tiene hijos")
            return
        
        # Calcular estadísticas
        total = len(children)
        completed = sum(1 for c in children if c['status'] == 'completed')
        failed = sum(1 for c in children if c['status'] == 'failed')
        cancelled = sum(1 for c in children if c['status'] == 'cancelled')
        
        # Calcular progreso promedio
        total_progress = sum(c.get('progress', 0) for c in children)
        average_progress = total_progress / total if total > 0 else 0
        
        # Actualizar padre
        parent_data['progress'] = average_progress
        parent_data['metadata']['completed_count'] = completed
        parent_data['metadata']['failed_count'] = failed
        parent_data['metadata']['cancelled_count'] = cancelled
        parent_data['metadata']['total_count'] = total
        
        # Si todos terminaron (exitosos o no)
        if completed + failed + cancelled == total:
            if failed == 0 and cancelled == 0:
                # Todos exitosos
                parent_data['status'] = 'ready_for_zip'
                parent_data['progress'] = 100
                logger.info(f"[QUEUE] Parent {parent_job_id} listo para ZIP")
            else:
                # Algunos fallaron
                parent_data['status'] = 'completed_with_errors'
                parent_data['error'] = f"{failed} fallidos, {cancelled} cancelados"
                logger.warning(f"[QUEUE] Parent {parent_job_id} completado con errores")
        else:
            parent_data['status'] = 'processing'
        
        self.redis.set(f"job:{parent_job_id}", json.dumps(parent_data))
        logger.info(
            f"[QUEUE] Parent {parent_job_id} actualizado: {completed}/{total} completados, "
            f"progreso: {average_progress:.1f}%"
        )
