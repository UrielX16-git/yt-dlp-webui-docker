"""
Router para endpoints relacionados con cookies.
"""
from fastapi import APIRouter, HTTPException, UploadFile, File
import logging

from ..services import ytdlp_svc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cookies", tags=["Cookies"])


@router.get("/status")
async def get_cookies_status():
    """
    Verifica si existe un archivo de cookies cargado.
    
    Returns:
        Estado de las cookies
    """
    exists = ytdlp_svc.check_cookies_exist()
    return {"exists": exists}


@router.post("/upload")
async def upload_cookies(file: UploadFile = File(...)):
    """
    Sube un archivo de cookies en formato Netscape.
    
    Args:
        file: Archivo de cookies
        
    Returns:
        Mensaje de confirmación
    """
    try:
        if not file.filename:
            raise HTTPException(status_code=400, detail="Nombre de archivo vacío")
        
        # Leer contenido
        content = await file.read()
        
        # Guardar usando el servicio (valida formato)
        ytdlp_svc.save_cookies(content)
        
        logger.info("Cookies cargadas exitosamente")
        return {"message": "Cookies subidas correctamente"}
        
    except ValueError as e:
        # Error de validación
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error subiendo cookies: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
