# yt-dlp WebUI 2.0 - Arquitectura de Microservicios

Descargador de videos y audios usando yt-dlp con interfaz web moderna y arquitectura de microservicios.

## 🚀 Características

- **Arquitectura de Microservicios**: API separada, Worker dedicado, Frontend independiente
- **Sistema de Cola**: Procesamiento asíncrono con Valkey (compatible con Redis)
- **Prioridades**: Sistema de cola con prioridades (info > descargas > playlists)
- **API REST**: FastAPI con documentación automática en `/docs`
- **Interfaz Moderna**: UI responsive con actualizaciones en tiempo real
- **Múltiples Formatos**: Soporte para video (4K, 1080p, 720p) y audio (MP3)
- **Subtítulos**: Descarga de subtítulos con selección de idioma
- **Playlists**: Soporte para descarga de playlists completas
- **Cookies**: Soporte para autenticación de YouTube via cookies
- **Auto-limpieza**: Limpieza automática de archivos cada 10 minutos (TTL: 4 horas)

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

### Servicios

1. **Frontend** (puerto 5000): Nginx sirviendo archivos estáticos y proxy a API
2. **API** (puerto 8000): FastAPI manejando solicitudes y gestión de cola
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
http://localhost:5000/docs
```

## 📡 API Endpoints

### Descargas

- `POST /descarga/info` - Obtener información del video
- `POST /descarga/iniciar` - Iniciar descarga (retorna task_id)
- `POST /descarga/cancel` - Cancelar descarga
- `GET /descarga/status/{task_id}` - Estado de descarga
- `GET /descarga/historial` - Listar archivos descargados
- `GET /descarga/archivo/{filename}` - Descargar archivo
- `DELETE /descarga/archivo/eliminar/{filename}` - Eliminar archivo
- `GET /descarga/view/{filename}` - Ver archivo (streaming)

### Cookies

- `GET /cookies/status` - Estado de cookies
- `POST /cookies/upload` - Subir archivo de cookies (formato Netscape)

## 🍪 Uso de Cookies (YouTube)

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
- API directa: `8000` (opcional, para debugging)

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
│       ├── queue_svc.py     # Gestión de cola Valkey
│       ├── ytdlp_svc.py     # Lógica de yt-dlp
│       └── worker_svc.py    # Worker background
├── static/
│   ├── style.css
│   ├── web.js
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
docker-compose up --build
```

## 🧹 Mantenimiento

- **Auto-limpieza**: Los archivos descargados se eliminan automáticamente después de 4 horas
- **Frecuencia**: El worker ejecuta limpieza cada 10 minutos
- **Manual**: Puedes eliminar archivos individualmente desde la interfaz web

## 📝 Notas

- Los archivos descargados se guardan en `./downloads` (volumen Docker)
- Las cookies se guardan en el contenedor de la API (no persistente, resubir después de rebuild)
- El sistema usa **Valkey** en lugar de Redis (fork open-source compatible)

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

## 📜 Licencia

MIT

## 🙏 Créditos

- [yt-dlp](https://github.com/yt-dlp/yt-dlp) - Descargador de videos
- [FastAPI](https://fastapi.tiangolo.com/) - Framework de API
- [Valkey](https://valkey.io/) - Sistema de cola
