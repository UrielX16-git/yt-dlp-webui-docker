# yt-dlp MCP Server (Model Context Protocol)

Servicio MCP especializado para que **Agentes de Inteligencia Artificial** (n8n, Claude Desktop, Cursor, Antigravity, OpenCode, CrewAI, AutoGen, etc.) puedan buscar, inspeccionar y gestionar descargas multimedia usando `yt-dlp` a través de la arquitectura de colas asíncronas de este repositorio.

Basado en los patrones de diseño probados en `hyperframes-mcp`.

---

## Características Principales

1. **Transporte Dual**:
   - **Streamable HTTP** (`POST /mcp`, `GET /mcp`, `DELETE /mcp`): Compatible nativamente con nodos **MCP Tool** de **n8n**.
   - **Server-Sent Events (SSE)** (`GET /sse`, `POST /message`): Compatible con clientes modernos de escritorio (Claude Desktop, Cursor, extensiones IDE).
2. **Endpoint de Prompt del Sistema (`GET /prompt`)**:
   - Expone [`agent_prompt.md`](./agent_prompt.md) para que orquestadores como n8n puedan precargar dinámicamente el comportamiento, reglas de anti-polling y buenas prácticas del agente.
3. **Manejo de Errores Resiliente**:
   - Errores recuperables retornan mensajes detallados en lugar de romper abruptamente el flujo del agente, permitiendo auto-corrección ("self-healing").
4. **Patrón Asíncrono Anti-Bloqueo**:
   - Las descargas se delegan al sistema de colas (Valkey + Worker) retornando un `taskId` de forma instantánea.

---

## Herramientas Disponibles (Tools)

| Herramienta | Descripción | Parámetros Clave |
| :--- | :--- | :--- |
| `ytdlp_search` | Busca videos en YouTube por palabras clave. | `query` (str), `limit` (int, default: 5) |
| `ytdlp_get_info` | Obtiene metadatos completos sin descargar (duración, calidades, canal). | `url` (str) |
| `ytdlp_playlist_info` | Inspecciona listas de reproducción y lista sus elementos. | `url` (str), `maxItems` (int) |
| `ytdlp_download_async` | Encola la descarga de video o extracción de audio. Retorna `taskId`. | `url`, `format` (`video`\|`audio`), `quality`, `subtitles`, `group` |
| `ytdlp_check_status` | Consulta el progreso (%), velocidad, ETA o archivo resultante (con enlaces `download_url` y `stream_url`). | `taskId` (str) |
| `ytdlp_get_download_link` | Obtiene directamente los enlaces de descarga directa y streaming/reproducción en navegador. | `taskId` o `filename`, `group` |
| `ytdlp_cancel` | Cancela una tarea pendiente o en ejecución. | `taskId` (str) |
| `ytdlp_list_history` | Lista archivos descargados, sus enlaces directos y tiempo restante antes de expirar (TTL). | `group` (str, default: 'default') |
| `ytdlp_search_file` | Busca si un archivo específico ya está disponible en local y retorna sus links. | `filename` (str) |
| `ytdlp_queue_stats` | Consulta el estado general de la cola (pendientes, en proceso, etc.). | N/A |

---

## Conexión con Clientes IA

### 1. Conexión en n8n
- En tu flujo de n8n, agrega el nodo **MCP Tool** (o nodo HTTP).
- Método de transporte: **Streamable HTTP**.
- URL del servidor: `http://yt-dlp-mcp:8080/mcp` (si n8n está en la red docker `multimedia-net`) o `http://localhost:8085/mcp`.
- Header: `mcp-session-id`.

### 2. Claude Desktop (`claude_desktop_config.json`)
```json
{
  "mcpServers": {
    "yt-dlp": {
      "command": "npx",
      "args": ["-y", "tsx", "J:/Apps/HerramientasAndChill/yt-dlp/yt-dlp-webui-docker/mcp/src/server.ts"]
    }
  }
}
```
O usando la URL SSE cuando el contenedor esté corriendo:
```json
{
  "mcpServers": {
    "yt-dlp": {
      "serverUrl": "http://localhost:8085/sse"
    }
  }
}
```

### 3. Cursor / OpenCode / Antigravity
Configurado automáticamente en [`.agents/mcp_config.json`](../.agents/mcp_config.json):
```json
{
  "mcpServers": {
    "yt-dlp-mcp": {
      "serverUrl": "http://localhost:8085/mcp"
    }
  }
}
```

---

## Ejecución

### Mediante Docker Compose (Recomendado)
El servicio ya está integrado en [`docker-compose.yml`](../docker-compose.yml):
```bash
docker compose up -d --build mcp-server
```

### En Desarrollo Local
Asegúrate de que la API de `yt-dlp` esté corriendo en el puerto 8001:
```bash
cd mcp
npm install
npm run dev
```
