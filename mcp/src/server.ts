import express from "express";
import path from "node:path";
import fs from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { randomUUID } from "node:crypto";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { SSEServerTransport } from "@modelcontextprotocol/sdk/server/sse.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";

import { YtDlpClient } from "./client.js";
import { registerYtDlpTools } from "./tools/ytdlp.js";

const app = express();
const PORT = process.env.PORT || 8080;
const client = new YtDlpClient();

app.use(express.json({ limit: "10mb" }));

// Configurar CORS para integraciones web y clientes MCP
app.use((req, res, next) => {
  res.header("Access-Control-Allow-Origin", "*");
  res.header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, DELETE");
  res.header("Access-Control-Allow-Headers", "Content-Type, mcp-session-id");
  if (req.method === "OPTIONS") {
    return res.sendStatus(200);
  }
  next();
});

function createMcpServer(): McpServer {
  const mcpServer = new McpServer({
    name: "yt-dlp-agent-mcp",
    version: "1.0.0",
  });
  registerYtDlpTools(mcpServer, client);
  return mcpServer;
}

// ==========================================
// 1. Transporte SSE (Claude Desktop, Cursor, Antigravity)
// ==========================================
const sseTransports = new Map<string, SSEServerTransport>();

app.get("/sse", async (req, res) => {
  try {
    const transport = new SSEServerTransport("/message", res);
    const mcpServer = createMcpServer();
    await mcpServer.connect(transport);

    sseTransports.set(transport.sessionId, transport);
    console.log(`[MCP-SSE] Conexión establecida. SessionID: ${transport.sessionId}`);

    transport.onclose = () => {
      sseTransports.delete(transport.sessionId);
      console.log(`[MCP-SSE] Conexión cerrada para sesión ${transport.sessionId}`);
    };
  } catch (err) {
    console.error("[MCP-SSE] Error en GET /sse:", err);
  }
});

app.post("/message", async (req, res) => {
  try {
    const sessionId = req.query.sessionId as string;
    if (!sessionId) {
      return res.status(400).send("Falta sessionId en query parameter");
    }
    const transport = sseTransports.get(sessionId);
    if (!transport) {
      return res.status(404).send("Sesión no encontrada");
    }
    await transport.handlePostMessage(req, res);
  } catch (err) {
    console.error("[MCP-SSE] Error en /message:", err);
  }
});

// ==========================================
// 2. Transporte Streamable HTTP (n8n MCP Agent Node)
// ==========================================
const streamableTransports = new Map<string, StreamableHTTPServerTransport>();

app.post("/mcp", async (req, res) => {
  try {
    const sessionId = req.headers["mcp-session-id"] as string | undefined;
    let transport: StreamableHTTPServerTransport;

    if (sessionId && streamableTransports.has(sessionId)) {
      transport = streamableTransports.get(sessionId)!;
    } else {
      transport = new StreamableHTTPServerTransport({
        sessionIdGenerator: () => randomUUID(),
        onsessioninitialized: (newSessionId) => {
          streamableTransports.set(newSessionId, transport);
          console.log(`[MCP-Streamable] Nueva sesión: ${newSessionId}`);
        },
      });

      const mcpServer = createMcpServer();
      await mcpServer.connect(transport);

      transport.onclose = () => {
        const sid = [...streamableTransports.entries()].find(([, t]) => t === transport)?.[0];
        if (sid) {
          streamableTransports.delete(sid);
          console.log(`[MCP-Streamable] Sesión cerrada: ${sid}`);
        }
      };
    }

    await transport.handleRequest(req, res, req.body);
  } catch (err) {
    console.error("[MCP-Streamable] Error en POST /mcp:", err);
    if (!res.headersSent) {
      res.status(500).json({ error: "Error interno MCP" });
    }
  }
});

app.get("/mcp", async (req, res) => {
  const sessionId = req.headers["mcp-session-id"] as string;
  const transport = streamableTransports.get(sessionId);
  if (!transport) {
    res.status(400).json({ error: "Sesión no encontrada. Envía primero POST /mcp" });
    return;
  }
  await transport.handleRequest(req, res);
});

app.delete("/mcp", async (req, res) => {
  const sessionId = req.headers["mcp-session-id"] as string;
  const transport = streamableTransports.get(sessionId);
  if (transport) {
    await transport.handleRequest(req, res);
    streamableTransports.delete(sessionId);
  } else {
    res.status(404).json({ error: "Sesión no encontrada" });
  }
});

// ==========================================
// 3. Health & System Prompt Endpoint
// ==========================================
app.get("/health", async (req, res) => {
  try {
    const apiHealth = await client.checkHealth().catch((e) => ({ status: "api_down", error: e.message }));
    res.json({
      status: "ok",
      mcp: "online",
      api: apiHealth,
    });
  } catch (err: any) {
    res.status(500).json({ status: "error", error: err.message });
  }
});

app.get("/prompt", async (req, res) => {
  const __dirname = path.dirname(fileURLToPath(import.meta.url));
  const projectRoot = path.join(__dirname, "..");
  const promptPath = path.join(projectRoot, "agent_prompt.md");

  try {
    const content = await fs.readFile(promptPath, "utf-8");
    res.type("text/plain").send(content);
  } catch (err: any) {
    console.error("Error al leer el prompt del agente:", err);
    res.status(500).send(`Prompt no encontrado en: ${promptPath}\nError: ${err.message}`);
  }
});

app.listen(PORT, () => {
  console.log(`====================================================`);
  console.log(`[HTTP] Servidor MCP de yt-dlp activo en http://0.0.0.0:${PORT}`);
  console.log(`[HTTP] SSE Endpoint: http://localhost:${PORT}/sse`);
  console.log(`[HTTP] Streamable HTTP Endpoint (n8n): http://localhost:${PORT}/mcp`);
  console.log(`[HTTP] Agent Prompt Endpoint: http://localhost:${PORT}/prompt`);
  console.log(`====================================================`);
});
