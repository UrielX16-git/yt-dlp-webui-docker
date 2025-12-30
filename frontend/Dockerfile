FROM nginx:alpine

# Copiar archivos estáticos
COPY static /usr/share/nginx/html/static
COPY templates/index.html /usr/share/nginx/html/index.html

# Copiar configuración de nginx
COPY frontend/nginx.conf /etc/nginx/nginx.conf

EXPOSE 80
