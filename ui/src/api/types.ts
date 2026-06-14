// ---------------------------------------------------------------------------
// TypeScript mirrors of the daemon's Pydantic schemas (llmode/schemas.py).
//
// Keeping these in sync by hand is fine for v1; a future enhancement is to
// generate them from the daemon's OpenAPI spec. Only the fields the UI uses are
// modelled.
// ---------------------------------------------------------------------------

/** Lifecycle states a model can be in (mirrors ModelState). */
export type ModelState =
  | "available"
  | "loading"
  | "ready"
  | "idle"
  | "unloading"
  | "error";

/** A single accelerator (GPU/NPU) discovered on the host. */
export interface AcceleratorInfo {
  kind: string;
  name: string;
  vram_total_bytes: number;
  vram_used_bytes: number;
}

/** Static host hardware description. */
export interface HardwareInfo {
  os: string;
  arch: string;
  cpu_count: number;
  ram_total_bytes: number;
  accelerators: AcceleratorInfo[];
}

/** Availability report for one backend runner. */
export interface BackendInfo {
  name: string;
  available: boolean;
  version: string | null;
  path: string | null;
  detail: string | null;
}

/** Combined response from GET /api/system. */
export interface SystemResponse {
  hardware: HardwareInfo;
  backends: BackendInfo[];
}

/** A live (or recently finished) model run. */
export interface ModelRun {
  model_id: string;
  backend: string;
  state: ModelState;
  pid: number | null;
  port: number | null;
  base_url: string | null;
  started_at: number;
  last_used_at: number;
  error: string | null;
}

/** A catalog model enriched with its current run state (GET /api/models). */
export interface ModelView {
  id: string;
  name: string;
  source: string;
  format: string;
  quantization: string | null;
  size_bytes: number;
  path: string | null;
  backends: string[];
  run: ModelRun | null;
}

/** One live metrics snapshot pushed over the WebSocket / returned by /api/metrics. */
export interface MetricsSnapshot {
  system: {
    timestamp: number;
    cpu_percent: number;
    ram_used_bytes: number;
    ram_total_bytes: number;
    accelerators: AcceleratorInfo[];
  } | null;
  models: {
    model_id: string;
    state: ModelState;
    resident_bytes: number;
    tokens_per_second: number;
    ttft_ms: number;
    requests: number;
  }[];
}
