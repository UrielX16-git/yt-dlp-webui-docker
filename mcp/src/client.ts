/**
 * Cliente HTTP para comunicarse con la API REST de yt-dlp.
 */
export class YtDlpClient {
  private baseUrl: string;
  public readonly publicBaseUrl: string;

  constructor(baseUrl?: string, publicBaseUrl?: string) {
    this.baseUrl = (baseUrl || process.env.YTDLP_API_URL || "http://localhost:8001").replace(/\/+$/, "");
    this.publicBaseUrl = (publicBaseUrl || process.env.PUBLIC_BASE_URL || process.env.YTDLP_PUBLIC_URL || "http://localhost:8001").replace(/\/+$/, "");
  }

  /**
   * Genera los links directos de descarga y streaming en el navegador.
   */
  buildDownloadUrls(filename: string, group = "default"): { downloadUrl: string; streamUrl: string; filename: string } {
    const clean = filename.trim().replace(/^[\/\\]+/, "");
    let relativePath: string;
    if (clean.includes("/") || clean.includes("\\")) {
      relativePath = clean.split(/[\/\\]/).map(encodeURIComponent).join("/");
    } else {
      relativePath = `${encodeURIComponent(group || "default")}/${encodeURIComponent(clean)}`;
    }

    return {
      filename: clean,
      downloadUrl: `${this.publicBaseUrl}/descarga/archivo/${relativePath}`,
      streamUrl: `${this.publicBaseUrl}/descarga/view/${relativePath}`,
    };
  }

  private async request<T>(path: string, options: RequestInit = {}): Promise<T> {
    const url = `${this.baseUrl}${path}`;
    const headers = {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    };

    const res = await fetch(url, {
      ...options,
      headers,
    });

    const text = await res.text();
    let data: any;
    try {
      data = text ? JSON.parse(text) : {};
    } catch {
      data = text;
    }

    if (!res.ok) {
      const detail = data?.detail || data?.message || text || `Error HTTP ${res.status}`;
      throw new Error(`[API Error ${res.status}] ${detail}`);
    }

    return data as T;
  }

  async searchYouTube(query: string, limit = 5): Promise<any> {
    const params = new URLSearchParams({
      query,
      limit: String(limit),
    });
    return this.request(`/descarga/search-youtube?${params.toString()}`);
  }

  async getVideoInfo(url: string): Promise<any> {
    return this.request("/descarga/info", {
      method: "POST",
      body: JSON.stringify({ url }),
    });
  }

  async getPlaylistInfo(url: string, maxItems = -1): Promise<any> {
    return this.request("/descarga/playlist-info", {
      method: "POST",
      body: JSON.stringify({ url, max_items: maxItems }),
    });
  }

  async startDownload(params: {
    url: string;
    format?: "video" | "audio";
    quality?: string;
    subtitles?: boolean;
    subtitleLang?: string;
    downloadPlaylist?: boolean;
    maxItems?: number;
    group?: string;
    title?: string;
    thumbnail?: string;
    selectedIndices?: number[];
  }): Promise<{ task_id: string }> {
    return this.request("/descarga/iniciar", {
      method: "POST",
      body: JSON.stringify({
        url: params.url,
        format: params.format || "video",
        quality: params.quality || "best",
        subtitles: Boolean(params.subtitles),
        subtitle_lang: params.subtitleLang || null,
        download_playlist: Boolean(params.downloadPlaylist),
        max_items: params.maxItems ?? -1,
        group: params.group || "default",
        title: params.title || null,
        thumbnail: params.thumbnail || null,
        selected_indices: params.selectedIndices || null,
      }),
    });
  }

  async cancelDownload(taskId: string): Promise<any> {
    return this.request("/descarga/cancel", {
      method: "POST",
      body: JSON.stringify({ task_id: taskId }),
    });
  }

  async getStatus(taskId: string): Promise<any> {
    return this.request(`/descarga/status/${encodeURIComponent(taskId)}`);
  }

  async getQueueStats(): Promise<any> {
    return this.request("/descarga/queue/stats");
  }

  async getHistory(group = "default"): Promise<any> {
    const params = new URLSearchParams({ group });
    return this.request(`/descarga/historial?${params.toString()}`);
  }

  async searchFile(filename: string): Promise<any> {
    return this.request("/descarga/search", {
      method: "POST",
      body: JSON.stringify({ filename }),
    });
  }

  async getGroups(): Promise<string[]> {
    return this.request("/descarga/grupos");
  }

  async checkHealth(): Promise<any> {
    return this.request("/health");
  }
}
