FROM python:3.11-slim

# Instalar FFmpeg y Node.js (requeridos por yt-dlp)
# FFmpeg: para merge de audio/video
# Node.js: para resolver desafíos de firma de YouTube
RUN apt-get update && \
    apt-get install -y ffmpeg nodejs npm && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copiar requirements e instalar dependencias
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir -U --pre "yt-dlp[default]"

# Copiar código de la aplicación
COPY app ./app
COPY static ./static
COPY templates ./templates

# Crear directorio de descargas
RUN mkdir -p /app/downloads

# Puerto de la API
EXPOSE 80

# Comando por defecto: API
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "80"]
