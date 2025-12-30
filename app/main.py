"""
API REST para descarga de videos/audios usando yt-dlp.
Arquitectura de microservicios con cola de procesamiento.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routers import downloads, cookies
import os
import logging

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

logger = logging.getLogger(__name__)

logger.info("=" * 60)
logger.info("Iniciando API de Descarga yt-dlp con Cola")
logger.info("Sistema de cola: Valkey + Worker asíncrono")
logger.info("=" * 60)

# Inicializar FastAPI
app = FastAPI(
    title="API de Descarga yt-dlp",
    description="API REST para descarga de videos y audios usando yt-dlp con sistema de cola",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Configurar CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Registrar routers
app.include_router(downloads.router)
app.include_router(cookies.router)


@app.get("/")
async def root():
    """Endpoint raíz con información de la API."""
    logger.info("Solicitud recibida en endpoint raíz /")
    return {
        "message": "API de Descarga yt-dlp con Cola",
        "version": "2.0.0",
        "status": "online",
        "features": {
            "queue_system": "Valkey + Worker asíncrono",
            "priority_queue": "Habilitado (high/normal/low)",
            "auto_cleanup": "Archivos descargados limpios automáticamente (TTL: 4 horas)",
            "cleanup_frequency": "Cada 10 minutos",
            "async_downloads": "Sistema de cola con respuesta instantánea"
        },
        "workflow": {
            "1_get_info": "POST /descarga/info → metadata del video",
            "2_start": "POST /descarga/iniciar → {task_id} (respuesta instantánea)",
            "3_check_status": "GET /descarga/status/{task_id} → polling cada 500ms",
            "4_download": "GET /descarga/archivo/{filename} → descargar resultado"
        },
        "endpoints": {
            "descarga": {
                "/descarga/info": "[POST] Obtener información del video",
                "/descarga/iniciar": "[POST] Iniciar descarga (retorna task_id)",
                "/descarga/cancel": "[POST] Cancelar descarga",
                "/descarga/status/{task_id}": "[GET] Estado de descarga",
                "/descarga/historial": "[GET] Listar archivos descargados",
                "/descarga/archivo/{filename}": "[GET] Descargar archivo",
                "/descarga/archivo/eliminar/{filename}": "[DELETE] Eliminar archivo",
                "/descarga/view/{filename}": "[GET] Ver archivo (streaming)"
            },
            "cookies": {
                "/cookies/status": "[GET] Estado de cookies",
                "/cookies/upload": "[POST] Subir archivo de cookies (Netscape)"
            }
        },
        "docs": "/docs",
        "redoc": "/redoc"
    }


@app.get("/health")
async def health_check():
    """Endpoint de salud para monitoreo."""
    logger.debug("Health check solicitado")
    return {"status": "healthy"}
