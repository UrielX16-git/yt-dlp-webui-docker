FROM node:22-alpine

WORKDIR /app

# Instalar dependencias
COPY package*.json ./
RUN npm ci

# Copiar configuración y código fuente
COPY tsconfig.json ./
COPY src/ ./src/
COPY agent_prompt.md ./

# Compilar TypeScript
RUN npm run build

EXPOSE 8080

CMD ["npm", "start"]
