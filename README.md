# yt-dlp WebUI

Descargador de videos y audios usando yt-dlp con interfaz web moderna, arquitectura de microservicios y sistema avanzado de gestión de playlists.

## 🚀 Características Principales

### Arquitectura y Sistema de Cola

- **Arquitectura de Microservicios**: API separada, Worker dedicado, Frontend independiente
- **Sistema de Cola**: Procesamiento asíncrono con Valkey (compatible con Redis)
- **Prioridades**: Sistema de cola con prioridades (info > descargas > playlists)
- **API REST**: FastAPI con documentación automática en `/docs`

### Descargas

- **Múltiples Formatos**: Soporte para video (4K, 1080p, 720p) y audio (MP3)
- **Subtítulos**: Descarga de subtítulos con selección de idioma
- **Cookies**: Soporte para autenticación de YouTube via cookies

### Sistema de Playlists Avanzado ⭐

- **Descomposición de Playlists**: Cada video se procesa como un trabajo individual en la cola
- **Estado Granular**: Seguimiento en tiempo real del progreso de cada video en la playlist
- **Límite Configurable**: Opción de descargar solo N videos de una playlist
- **Organización Automática**: Cada playlist se descarga en su propia carpeta
- **Compresión ZIP**: Generación automática de archivo ZIP al completar la playlist
- **Visualización Detallada**: UI muestra estado individual de cada video (⏳ descargando, ✅ completado, ❌ fallido)

### Utilidades

- **Búsqueda de Archivos**: Endpoint para localizar archivos descargados (incluso con nombres sanitizados)
- **Auto-limpieza**: Limpieza automática de archivos cada 10 minutos (TTL: 4 horas)
- **Interfaz Moderna**: UI responsive con actualizaciones en tiempo real

## 📋 Requisitos

- Docker
- Docker Compose

## 🏗️ Arquitectura

```
┌─────────────┐
│   Frontend  │ nginx (puerto 5000)
│   (Nginx)   │
└──────┬──────┘
       │ Proxy
       ▼
┌─────────────┐     ┌──────────┐
│     API     │────▶│  Valkey  │
│  (FastAPI)  │     │  (Cola)  │
└──────┬──────┘     └────┬─────┘
       │                 │
       │                 │
       ▼                 ▼
┌─────────────┐     ┌──────────┐
│  /downloads │◀────│  Worker  │
│  (Volume)   │     │ (yt-dlp) │
└─────────────┘     └──────────┘
```

### Flujo de Playlist

```
Usuario solicita playlist
         │
         ▼
    API explota playlist
    (1 Parent Job + N Child Jobs)
         │
         ▼
┌────────────────────────┐
│   Cola de Prioridades  │
│  ┌──────────────────┐  │
│  │ Parent (tracker) │  │
│  ├──────────────────┤  │
│  │ Child Job 1      │  │
│  │ Child Job 2      │  │
│  │ Child Job 3      │  │
│  └──────────────────┘  │
└────────────────────────┘
         │
         ▼
Worker procesa 1 por 1
         │
         ▼
Último hijo completa
         │
         ▼
Worker crea ZIP automático
         │
         ▼
Parent marcado como "completed"
```

### Servicios

1. **Frontend** (puerto 5000): Nginx sirviendo archivos estáticos y proxy a API
2. **API** (puerto 8001): FastAPI manejando solicitudes y gestión de cola
3. **Worker**: Proceso background que ejecuta yt-dlp para descargas
4. **Valkey**: Sistema de cola compatible con Redis

## 🚀 Inicio Rápido

1. **Clonar el repositorio**

```bash
git clone <repo-url>
cd yt_dlp-webui-docker
```

1. **Iniciar los servicios**

```bash
docker-compose up --build
```

1. **Acceder a la interfaz web**

```
http://localhost:5000
```

1. **Acceder a la documentación de la API**

```
http://localhost:8001/docs
```

## 📡 API Endpoints

### Descargas

- `POST /descarga/info` - Obtener información del video
- `POST /descarga/playlist-info` - Obtener información de playlist sin descargar (⭐ nuevo)
- `POST /descarga/iniciar` - Iniciar descarga (retorna task_id)
- `POST /descarga/cancel` - Cancelar descarga
- `GET /descarga/status/{task_id}` - Estado de descarga (⭐ ajustado para playlists)
- `POST /descarga/search` - Buscar archivo en descargas por nombre (⭐ nuevo)
- `GET /descarga/historial` - Listar archivos descargados
- `GET /descarga/archivo/{filename}` - Descargar archivo
- `DELETE /descarga/archivo/eliminar/{filename}` - Eliminar archivo
- `GET /descarga/view/{filename}` - Ver archivo (streaming)

### Cookies

- `GET /cookies/status` - Estado de cookies
- `POST /cookies/upload` - Subir archivo de cookies (formato Netscape)

## Ejemplo de Uso - Playlist

### 1. Obtener información de playlist (opcional)

```bash
curl -X POST "http://localhost:8001/descarga/playlist-info" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://www.youtube.com/playlist?list=...",
    "max_items": 5
  }'
```

**Respuesta:**

```json
{
  "playlist_title": "Mi Playlist",
  "total_videos": 50,
  "returned_videos": 5,
  "videos": [
    {
      "index": 1,
      "url": "https://www.youtube.com/watch?v=...",
      "title": "Video 1",
      "duration": "10:35"
    }
  ]
}
```

### 2. Iniciar descarga de playlist

```bash
curl -X POST "http://localhost:8001/descarga/iniciar" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://www.youtube.com/playlist?list=...",
    "format": "video",
    "quality": "1080p",
    "download_playlist": true,
    "max_items": 5
  }'
```

**Respuesta:**

```json
{
  "task_id": "parent-job-uuid"
}
```

### 3. Consultar estado granular

```bash
curl "http://localhost:8001/descarga/status/parent-job-uuid"
```

**Respuesta:**

```json
{
  "id": "parent-job-uuid",
  "type": "playlist",
  "status": "processing",
  "progress": 66.7,
  "playlist_title": "Mi Playlist",
  "playlist_folder": "Mi_Playlist",
  "total_count": 3,
  "completed_count": 2,
  "failed_count": 0,
  "items": [
    {
      "id": "child-1",
      "title": "Video 1",
      "index": 1,
      "status": "completed",
      "progress": 100,
      "filename": "Video_1.mp4"
    },
    {
      "id": "child-2",
      "title": "Video 2",
      "index": 2,
      "status": "completed",
      "progress": 100,
      "filename": "Video_2.mp4"
    },
    {
      "id": "child-3",
      "title": "Video 3",
      "index": 3,
      "status": "downloading",
      "progress": 50,
      "speed": "2.3 MiB/s",
      "eta": "00:45"
    }
  ]
}
```

### 4. Resultado final

Al completar, encontrarás:

- **Carpeta**: `downloads/Mi_Playlist/` con todos los videos individuales
- **ZIP**: `downloads/Mi_Playlist.zip` para descarga rápida del conjunto completo

### 5. Buscar archivo descargado

```bash
curl -X POST "http://localhost:5000/descarga/search" \
  -H "Content-Type: application/json" \
  -d '{
    "filename": "OLIVER TREE & LITTLE BIG - TURN IT UP (FEAT. TOMMY CASH)"
  }'
```

**Respuesta:**

```json
{
  "found": true,
  "path": "MiPlaylist/OLIVER_TREE_LITTLE_BIG_-_TURN_IT_UP_FEAT._TOMMY_CASH.mp4",
  "filename": "OLIVER_TREE_LITTLE_BIG_-_TURN_IT_UP_FEAT._TOMMY_CASH.mp4",
  "full_path": "/app/downloads/MiPlaylist/OLIVER_TREE_LITTLE_BIG_-_TURN_IT_UP_FEAT._TOMMY_CASH.mp4"
}
```

## �🍪 Uso de Cookies (YouTube)

Para descargar videos privados o con restricciones de edad de YouTube:

1. Instalar extensión de navegador para exportar cookies (ej: "Get cookies.txt")
2. Exportar cookies de YouTube en formato Netscape
3. En la interfaz web, hacer clic en el icono de cookie (arriba a la derecha)
4. Subir el archivo `.txt`

## 🔧 Configuración

### Variables de Entorno

Editar `docker-compose.yml`:

```yaml
environment:
  - VALKEY_HOST=valkey
  - VALKEY_PORT=6379
```

### Puertos

- Frontend: `5000` (modificar en docker-compose.yml)
- API directa: `8001` (opcional, para debugging)

### Límites de Recursos

Ajustar en `docker-compose.yml` si es necesario:

```yaml
deploy:
  resources:
    limits:
      cpus: '4.0'
      memory: 4G
```

## 📁 Estructura del Proyecto

```
yt_dlp-webui-docker/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI app
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── downloads.py     # Endpoints de descarga
│   │   └── cookies.py       # Endpoints de cookies
│   └── services/
│       ├── __init__.py
│       ├── queue_svc.py     # Gestión de cola Valkey (parent-child tracking)
│       ├── ytdlp_svc.py     # Lógica de yt-dlp
│       └── worker_svc.py    # Worker background + cleanup
├── static/
│   ├── style.css
│   ├── web.js               # Frontend con soporte de playlist granular
│   └── icon.webp
├── templates/
│   └── index.html
├── frontend/
│   └── nginx.conf
├── docker-compose.yml
├── Dockerfile
└── requirements.txt
```

## 🛠️ Desarrollo

### Logs

Ver logs de un servicio específico:

```bash
docker-compose logs -f api
docker-compose logs -f worker
docker-compose logs -f valkey
```

### Reiniciar servicios

```bash
docker-compose restart api
docker-compose restart worker
```

### Reconstruir

```bash
docker-compose down
docker-compose build
docker-compose up -d
```

## 🧹 Mantenimiento

- **Auto-limpieza**: Los archivos descargados se eliminan automáticamente después de 4 horas
- **Frecuencia**: El worker ejecuta limpieza cada 10 minutos
- **Log Inteligente**: Los errores de limpieza se agrupan para evitar spam en logs
- **Manual**: Puedes eliminar archivos individualmente desde la interfaz web

## 📝 Notas Técnicas

### Playlists

- Cada video de una playlist se descarga como un **trabajo independiente** en la cola
- El sistema crea un **Parent Job** (solo tracking) y múltiples **Child Jobs** (descargas reales)
- Al completar todos los videos, el Worker crea automáticamente un ZIP
- Los archivos individuales permanecen en la carpeta para acceso directo
- Ambos (carpeta + ZIP) se eliminan juntos según el TTL

### Persistencia

- Los archivos descargados se guardan en `./downloads` (volumen Docker persistente)
- Las cookies se guardan en el contenedor de la API (no persistente, resubir después de rebuild)
- El sistema usa **Valkey** en lugar de Redis (fork open-source compatible)
- Los jobs en Valkey expiran automáticamente (completados: 4h, fallidos: 1h)

## 🐛 Troubleshooting

### Worker no procesa descargas

```bash
docker-compose logs worker
docker-compose restart worker
```

### Error de conexión a Valkey

```bash
docker-compose logs valkey
docker-compose restart valkey
```

### Frontend no carga

```bash
docker-compose logs frontend
# Verificar que nginx.conf está correctamente montado
```

### Playlists no se descargan correctamente

```bash
# Ver logs detallados del worker
docker-compose logs -f worker

# Verificar que el parent job existe
curl http://localhost:5000/descarga/status/{parent_job_id}

# Verificar child jobs individuales
curl http://localhost:5000/descarga/status/{child_job_id}
```

## 🔄 Changelog - Versión 2.0

### Sistema de Playlists Mejorado

- ✨ Explosión de playlists en trabajos individuales
- ✨ Estado granular por video
- ✨ Endpoint `/descarga/playlist-info` para previsualización
- ✨ Compresión ZIP automática
- ✨ Visualización mejorada en UI con iconos de estado

### Nuevas Funcionalidades

- ✨ Endpoint `/descarga/search` para búsqueda de archivos
- ✨ Soporte para `custom_output_dir` en descargas
- ✨ Sistema de parent-child jobs en cola

### Mejoras de Infraestructura

- 🐛 Fix: Log spam en cleanup eliminado (errores agrupados)
- 🐛 Fix: Manejo robusto de archivos expirados
- ⚡ Performance: Polling optimizado (5s → 2s)
- ⚡ Performance: Cleanup más eficiente con manejo de race conditions

## 📜 Licencia

MIT

## 🙏 Créditos

- [yt-dlp](https://github.com/yt-dlp/yt-dlp) - Descargador de videos
- [FastAPI](https://fastapi.tiangolo.com/) - Framework de API
- [Valkey](https://valkey.io/) - Sistema de cola
