// ---------------------------------------------------------------------------
// Typed HTTP client for the LLMode daemon's management API.
//
// Base URL resolution:
//   * In dev, requests are relative ("/api/...") and Vite proxies them to the
//     daemon (see vite.config.ts) — same-origin, no CORS.
//   * In a separate-origin deployment, set VITE_LLMODE_API to the daemon URL.
// ---------------------------------------------------------------------------
import type {
  MetricsSnapshot,
  ModelView,
  SystemResponse,
} from "./types";

// Daemon base URL: empty string means "same origin" (dev proxy handles it).
const BASE = import.meta.env.VITE_LLMODE_API ?? "";

// Optional bearer token (when the daemon enforces auth); read from env at build.
const TOKEN = import.meta.env.VITE_LLMODE_TOKEN as string | undefined;

/** Build request headers, attaching the bearer token when configured. */
function headers(extra: Record<string, string> = {}): Record<string, string> {
  const h: Record<string, string> = { ...extra };
  if (TOKEN) h["Authorization"] = `Bearer ${TOKEN}`;
  return h;
}

/** Perform a fetch and parse JSON, throwing a helpful error on non-2xx. */
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, {
    ...init,
    headers: headers(init?.body ? { "Content-Type": "application/json" } : {}),
  });
  if (!resp.ok) {
    // Surface the daemon's error detail to the caller for display.
    const text = await resp.text();
    throw new Error(`${resp.status}: ${text}`);
  }
  return resp.json() as Promise<T>;
}

// --- Management API surface (one method per endpoint) ----------------------
export const api = {
  /** GET /api/system — hardware + backend availability. */
  system: () => request<SystemResponse>("/api/system"),

  /** GET /api/models — catalog merged with live run state. */
  models: () => request<ModelView[]>("/api/models"),

  /** POST /api/models/search — search the remote catalog. */
  search: (query: string, limit = 20) =>
    request<ModelView[]>("/api/models/search", {
      method: "POST",
      body: JSON.stringify({ query, limit }),
    }),

  /** POST /api/models/download — fetch weights into the local store. */
  download: (repo_id: string, filename?: string) =>
    request<ModelView>("/api/models/download", {
      method: "POST",
      body: JSON.stringify({ repo_id, filename: filename ?? null }),
    }),

  /** POST /api/models/{id}/load — load a model (optionally forcing a backend). */
  load: (id: string, backend?: string) =>
    request(`/api/models/${encodeURIComponent(id)}/load`, {
      method: "POST",
      body: JSON.stringify({ backend: backend ?? null }),
    }),

  /** POST /api/models/{id}/unload — stop a running model. */
  unload: (id: string) =>
    request(`/api/models/${encodeURIComponent(id)}/unload`, { method: "POST" }),

  /** GET /api/models/{id}/logs — buffered backend logs. */
  logs: (id: string) =>
    request<{ model_id: string; logs: string[] }>(
      `/api/models/${encodeURIComponent(id)}/logs`,
    ),

  /** GET /api/metrics — latest snapshot (one-shot poll). */
  metrics: () => request<MetricsSnapshot>("/api/metrics"),

  /** GET /api/events — recent structured events. */
  events: (limit = 100) =>
    request<{ events: { timestamp: number; kind: string; model_id: string | null; message: string }[] }>(
      `/api/events?limit=${limit}`,
    ),
};

/**
 * Build the WebSocket URL for live metrics (/api/events).
 * Converts the http(s) base origin into ws(s) and appends the path.
 */
export function eventsWsUrl(): string {
  // When BASE is empty (dev proxy), derive from the current page origin.
  const origin = BASE || window.location.origin;
  const wsOrigin = origin.replace(/^http/, "ws");
  return `${wsOrigin}/api/events`;
}
