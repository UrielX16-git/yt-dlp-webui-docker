#!/bin/sh
set -e

if [ "$YTDLP_AUTO_UPDATE" = "true" ] || [ "$YTDLP_AUTO_UPDATE" = "1" ]; then
    echo "[ENTRYPOINT] Verificando actualización de yt-dlp al iniciar..."
    pip install --no-cache-dir -U --pre "yt-dlp[default]" || echo "[ENTRYPOINT] Advertencia: No se pudo actualizar yt-dlp en el arranque."
    echo "[ENTRYPOINT] Versión actual de yt-dlp: $(yt-dlp --version)"
fi

exec "$@"
