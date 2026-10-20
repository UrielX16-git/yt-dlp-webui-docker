import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { YtDlpClient } from "../client.js";

/**
 * Registra todas las herramientas MCP enfocadas en Agentes IA para yt-dlp.
 */
export function registerYtDlpTools(mcpServer: McpServer, client: YtDlpClient) {
  // 1. ytdlp_search
  mcpServer.registerTool(
    "ytdlp_search",
    {
      description: "Searches YouTube videos by keywords. Use this when the user mentions video or audio titles instead of a direct URL.",
      inputSchema: {
        query: z.string().describe("Search term or keywords (e.g., 'ambient study music', 'tutorial docker')"),
        limit: z.number().int().min(1).max(20).optional().describe("Maximum number of results to return (default: 5, max: 20)"),
      },
    },
    async ({ query, limit = 5 }) => {
      try {
        const results = await client.searchYouTube(query, limit);
        return {
          content: [
            {
              type: "text",
              text: JSON.stringify(results, null, 2),
            },
          ],
        };
      } catch (err: any) {
        return {
          isError: false,
          content: [
            {
              type: "text",
              text: `Search failed for query "${query}": ${err.message}. Please refine your search term.`,
            },
          ],
        };
      }
    }
  );

  // 2. ytdlp_get_info
  mcpServer.registerTool(
    "ytdlp_get_info",
    {
      description: "Fetches detailed metadata of a video (title, channel, duration, available qualities, subtitles, formats) WITHOUT downloading it. Recommended before starting a download.",
      inputSchema: {
        url: z.string().url().describe("The video URL (YouTube, Vimeo, Twitter, etc.)"),
      },
    },
    async ({ url }) => {
      try {
        const info = await client.getVideoInfo(url);
        return {
          content: [
            {
              type: "text",
              text: JSON.stringify(info, null, 2),
            },
          ],
        };
      } catch (err: any) {
        return {
          isError: false,
          content: [
            {
              type: "text",
              text: `Unable to get video info for "${url}": ${err.message}. Verify that the URL is public and valid.`,
            },
          ],
        };
      }
    }
  );

  // 3. ytdlp_playlist_info
  mcpServer.registerTool(
    "ytdlp_playlist_info",
    {
      description: "Inspects a playlist URL to get the playlist title, total item count, and individual video items with their indices and titles.",
      inputSchema: {
        url: z.string().url().describe("The playlist URL"),
        maxItems: z.number().int().optional().describe("Optional limit of items to inspect (-1 for all, default: -1)"),
      },
    },
    async ({ url, maxItems = -1 }) => {
      try {
        const info = await client.getPlaylistInfo(url, maxItems);
        return {
          content: [
            {
              type: "text",
              text: JSON.stringify(info, null, 2),
            },
          ],
        };
      } catch (err: any) {
        return {
          isError: false,
          content: [
            {
              type: "text",
              text: `Unable to inspect playlist "${url}": ${err.message}`,
            },
          ],
        };
      }
    }
  );

  // 4. ytdlp_download_async
  mcpServer.registerTool(
    "ytdlp_download_async",
    {
      description: "Asynchronously queues a video or audio download job. Returns immediately with a taskId. DO NOT poll in a tight loop; return the taskId to the user.",
      inputSchema: {
        url: z.string().url().describe("URL to download"),
        format: z.enum(["video", "audio"]).optional().describe("Output format: 'video' (MP4/MKV) or 'audio' (MP3/M4A). Default: 'video'"),
        quality: z.enum(["best", "1080p", "720p", "4k"]).optional().describe("Desired video/audio quality preset. Default: 'best'"),
        subtitles: z.boolean().optional().describe("Whether to download subtitles (default: false)"),
        subtitleLang: z.string().optional().describe("Subtitle language code (e.g., 'es', 'en', 'es-orig')"),
        downloadPlaylist: z.boolean().optional().describe("Set to true if downloading an entire playlist"),
        maxItems: z.number().int().optional().describe("If downloading playlist, limit number of items (-1 for all)"),
        selectedIndices: z.array(z.number().int()).optional().describe("Optional list of specific video indices from a playlist to download"),
        group: z.string().optional().describe("Folder/group name for organizing downloads (letters, numbers, dashes, underscores, max 40 chars). Default: 'default'"),
        title: z.string().optional().describe("Optional human-readable title for UI tracking"),
      },
    },
    async (params) => {
      try {
        const res = await client.startDownload(params);
        return {
          content: [
            {
              type: "text",
              text: JSON.stringify(
                {
                  success: true,
                  taskId: res.task_id,
                  message: `Download job enqueued successfully. Task ID: ${res.task_id}. Use ytdlp_check_status to monitor progress.`,
                  params: {
                    url: params.url,
                    format: params.format || "video",
                    quality: params.quality || "best",
                    group: params.group || "default",
                  },
                },
                null,
                2
              ),
            },
          ],
        };
      } catch (err: any) {
        return {
          isError: false,
          content: [
            {
              type: "text",
              text: `Failed to enqueue download for ${params.url}: ${err.message}`,
            },
          ],
        };
      }
    }
  );

  // 5. ytdlp_check_status
  mcpServer.registerTool(
    "ytdlp_check_status",
    {
      description: "Checks the status of an asynchronous download job (progress percentage, speed, ETA, status, output filename, and ready download/stream URLs).",
      inputSchema: {
        taskId: z.string().describe("The task ID returned by ytdlp_download_async"),
      },
    },
    async ({ taskId }) => {
      try {
        const status = await client.getStatus(taskId);

        // Si ya completó y tiene archivo, inyectar los links de descarga directa
        if (status && status.filename) {
          const urls = client.buildDownloadUrls(status.filename, status.group || "default");
          status.download_url = urls.downloadUrl;
          status.stream_url = urls.streamUrl;
        }

        // Si es playlist con items individuales
        if (status && status.type === "playlist" && Array.isArray(status.items)) {
          status.items = status.items.map((item: any) => {
            if (item.filename) {
              const urls = client.buildDownloadUrls(item.filename, status.playlist_folder || status.group || "default");
              return {
                ...item,
                download_url: urls.downloadUrl,
                stream_url: urls.streamUrl,
              };
            }
            return item;
          });
        }

        return {
          content: [
            {
              type: "text",
              text: JSON.stringify(status, null, 2),
            },
          ],
        };
      } catch (err: any) {
        return {
          isError: false,
          content: [
            {
              type: "text",
              text: `Task check failed for ID "${taskId}": ${err.message}`,
            },
          ],
        };
      }
    }
  );

  // 6. ytdlp_cancel
  mcpServer.registerTool(
    "ytdlp_cancel",
    {
      description: "Cancels an ongoing or queued download task.",
      inputSchema: {
        taskId: z.string().describe("Task ID to cancel"),
      },
    },
    async ({ taskId }) => {
      try {
        const res = await client.cancelDownload(taskId);
        return {
          content: [
            {
              type: "text",
              text: JSON.stringify(res, null, 2),
            },
          ],
        };
      } catch (err: any) {
        return {
          isError: false,
          content: [
            {
              type: "text",
              text: `Failed to cancel task "${taskId}": ${err.message}`,
            },
          ],
        };
      }
    }
  );

  // 7. ytdlp_get_download_link (NUEVA HERRAMIENTA)
  mcpServer.registerTool(
    "ytdlp_get_download_link",
    {
      description: "Generates direct, ready-to-click download and browser streaming URLs for a downloaded file. You can provide either the completed taskId or the filename.",
      inputSchema: {
        taskId: z.string().optional().describe("Task ID of the download (if checking by task)"),
        filename: z.string().optional().describe("Name of the file (e.g., 'video.mp4' or from history/search)"),
        group: z.string().optional().describe("Group/folder name where the file is stored (default: 'default')"),
      },
    },
    async ({ taskId, filename, group = "default" }) => {
      try {
        let targetFile = filename;
        let targetGroup = group;

        if (taskId && !targetFile) {
          const status = await client.getStatus(taskId);
          if (!status) {
            return {
              isError: false,
              content: [{ type: "text", text: `Task with ID "${taskId}" not found.` }],
            };
          }
          if (status.status !== "completed") {
            return {
              isError: false,
              content: [
                {
                  type: "text",
                  text: JSON.stringify(
                    {
                      ready: false,
                      status: status.status,
                      progress: status.progress || 0,
                      message: `Download has not finished yet (current status: ${status.status}, progress: ${status.progress || 0}%).`,
                    },
                    null,
                    2
                  ),
                },
              ],
            };
          }

          targetFile = status.filename;
          targetGroup = status.group || targetGroup;
        }

        if (!targetFile) {
          return {
            isError: false,
            content: [
              {
                type: "text",
                text: "Please provide either a valid 'taskId' of a completed job or a 'filename'.",
              },
            ],
          };
        }

        const urls = client.buildDownloadUrls(targetFile, targetGroup);

        return {
          content: [
            {
              type: "text",
              text: JSON.stringify(
                {
                  ready: true,
                  filename: urls.filename,
                  group: targetGroup,
                  download_url: urls.downloadUrl,
                  stream_url: urls.streamUrl,
                  note: "Download link is active. Note: files are kept for 4 hours TTL before automatic cleanup.",
                },
                null,
                2
              ),
            },
          ],
        };
      } catch (err: any) {
        return {
          isError: false,
          content: [
            {
              type: "text",
              text: `Failed to generate download link: ${err.message}`,
            },
          ],
        };
      }
    }
  );

  // 8. ytdlp_list_history
  mcpServer.registerTool(
    "ytdlp_list_history",
    {
      description: "Lists all completed and downloaded media files available in storage for a given group, including direct download URLs, file size, date, and remaining TTL before auto-cleanup (default TTL: 4 hours).",
      inputSchema: {
        group: z.string().optional().describe("Group/company folder name (default: 'default')"),
      },
    },
    async ({ group = "default" }) => {
      try {
        const history = await client.getHistory(group);
        const enriched = Array.isArray(history)
          ? history.map((item: any) => {
              const urls = client.buildDownloadUrls(item.name, group);
              return {
                ...item,
                download_url: urls.downloadUrl,
                stream_url: urls.streamUrl,
              };
            })
          : history;

        return {
          content: [
            {
              type: "text",
              text: JSON.stringify(enriched, null, 2),
            },
          ],
        };
      } catch (err: any) {
        return {
          isError: false,
          content: [
            {
              type: "text",
              text: `Failed to retrieve download history: ${err.message}`,
            },
          ],
        };
      }
    }
  );

  // 9. ytdlp_search_file
  mcpServer.registerTool(
    "ytdlp_search_file",
    {
      description: "Finds if a specific file name or partial title has already been downloaded and is stored locally in the downloads folder, providing its direct download URL if found.",
      inputSchema: {
        filename: z.string().describe("Exact or partial file name to look up"),
      },
    },
    async ({ filename }) => {
      try {
        const res = await client.searchFile(filename);
        if (res && res.path) {
          const urls = client.buildDownloadUrls(res.path);
          res.download_url = urls.downloadUrl;
          res.stream_url = urls.streamUrl;
        }

        return {
          content: [
            {
              type: "text",
              text: JSON.stringify(res, null, 2),
            },
          ],
        };
      } catch (err: any) {
        return {
          isError: false,
          content: [
            {
              type: "text",
              text: `File not found in local storage: "${filename}". Details: ${err.message}`,
            },
          ],
        };
      }
    }
  );

  // 10. ytdlp_queue_stats
  mcpServer.registerTool(
    "ytdlp_queue_stats",
    {
      description: "Returns live statistics about the worker queue: number of pending, currently processing, completed, and failed tasks.",
      inputSchema: {},
    },
    async () => {
      try {
        const stats = await client.getQueueStats();
        return {
          content: [
            {
              type: "text",
              text: JSON.stringify(stats, null, 2),
            },
          ],
        };
      } catch (err: any) {
        return {
          isError: false,
          content: [
            {
              type: "text",
              text: `Unable to read queue stats: ${err.message}`,
            },
          ],
        };
      }
    }
  );
}
