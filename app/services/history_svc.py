"""
Servicio para gestionar el historial de descargas y generar recomendaciones.
Utiliza un archivo JSON simple almacenado en la carpeta de descargas.
"""
import json
import os
import logging
import time
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

DOWNLOAD_FOLDER = '/app/downloads'

class HistoryService:
    def __init__(self, group: str = 'default'):
        """
        Initialize HistoryService for a specific group.
        
        Args:
            group: Group name (default: "default")
        """
        self.group = group
        self.group_folder = os.path.join(DOWNLOAD_FOLDER, group)
        self.history_file = os.path.join(self.group_folder, 'history.json')
        
        # Ensure group folder exists
        os.makedirs(self.group_folder, exist_ok=True)

    def _load_history(self) -> List[Dict]:
        """Carga el historial desde el archivo JSON."""
        if not os.path.exists(self.history_file):
            return []
        
        try:
            with open(self.history_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error cargando historial: {e}")
            return []

    def _save_history(self, history: List[Dict]):
        """Guarda el historial en el archivo JSON."""
        try:
            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump(history, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Error guardando historial: {e}")

    def add_entry(self, video_data: Dict[str, Any]):
        """
        Añade una nueva entrada al historial.
        
        Args:
            video_data: Diccionario con metadatos del video (id, title, uploader, etc.)
        """
        try:
            history = self._load_history()
            
            # Crear entrada simplificada
            entry = {
                'id': video_data.get('id'),
                'title': video_data.get('title'),
                'uploader': video_data.get('uploader') or video_data.get('channel') or 'Desconocido',
                'timestamp': time.time(),
                'format': video_data.get('format_type', 'unknown')
            }
            
            # Evitar duplicados recientes (mismo ID en las últimas 24h)
            is_duplicate = False
            now = time.time()
            for item in history:
                if item.get('id') == entry['id'] and (now - item.get('timestamp', 0)) < 86400:
                    is_duplicate = True
                    break
            
            if not is_duplicate:
                history.append(entry)
                
                # Mantener tamaño razonable (ej. últimos 50 items)
                if len(history) > 50:
                    history = history[-50:]
                
                self._save_history(history)
                logger.info(f"Añadida entrada al historial: {entry['title']}")
                
        except Exception as e:
            logger.error(f"Error añadiendo entrada al historial: {e}")

    def get_recommendation_query(self) -> Optional[str]:
        """
        Analiza el historial y genera una query de búsqueda para recomendaciones.
        Solo considera descargas de audio.
        
        Returns:
            String de búsqueda o None si no hay suficiente historial de audio.
        """
        import random
        
        history = self._load_history()
        
        if not history:
            return None
        
        # Analizar últimos 10 items, solo audio
        recent_items = history[-10:]
        audio_items = [item for item in recent_items if item.get('format') == 'audio']
        
        if not audio_items:
            return None
        
        # Selección aleatoria de uploader (con pesos por repetición)
        uploaders = [item['uploader'] for item in audio_items if item.get('uploader')]
        if uploaders:
            # Selección aleatoria - artistas repetidos tienen más probabilidad
            chosen_uploader = random.choice(uploaders)
            logger.info(f"Recomendación aleatoria basada en historial de audio: {chosen_uploader}")
            return f"{chosen_uploader} music"
            
        return None
