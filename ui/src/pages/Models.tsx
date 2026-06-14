// ---------------------------------------------------------------------------
// Models page — local models with load/unload controls and a log viewer.
// ---------------------------------------------------------------------------
import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { ModelView } from "../api/types";
import { formatBytes, stateColor } from "../util/format";

/** Manage downloaded models: load, unload, inspect logs. */
export function Models() {
  const [models, setModels] = useState<ModelView[]>([]);
  // Which model's logs are expanded, and the fetched lines.
  const [openLogs, setOpenLogs] = useState<string | null>(null);
  const [logLines, setLogLines] = useState<string[]>([]);

  /** Refresh the model list from the daemon. */
  const refresh = useCallback(async () => {
    try {
      setModels(await api.models());
    } catch (e) {
      console.error(e);
    }
  }, []);

  // Poll the model list periodically so state transitions are visible.
  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 3000);
    return () => clearInterval(id);
  }, [refresh]);

  /** Load a model, then refresh to reflect the new state. */
  async function load(id: string) {
    try {
      await api.load(id);
    } catch (e) {
      alert((e as Error).message); // surface budget/backend errors directly
    }
    refresh();
  }

  /** Unload a model and refresh. */
  async function unload(id: string) {
    await api.unload(id);
    refresh();
  }

  /** Toggle the log panel for a model, fetching its current buffer. */
  async function toggleLogs(id: string) {
    if (openLogs === id) {
      setOpenLogs(null);
      return;
    }
    const { logs } = await api.logs(id);
    setLogLines(logs);
    setOpenLogs(id);
  }

  // Only downloaded models are manageable here (path != null).
  const local = models.filter((m) => m.path);

  return (
    <div className="page">
      <h2>Models</h2>
      {local.length === 0 && <p className="muted">No local models yet — download some from the Catalog.</p>}

      {local.map((m) => {
        const state = m.run?.state ?? "available";
        const running = state === "ready" || state === "idle" || state === "loading";
        return (
          <div key={m.id} className="card">
            <div className="row">
              <div>
                <strong>{m.name}</strong>
                <div className="muted">
                  {m.id} · {m.format} · {formatBytes(m.size_bytes)}
                </div>
              </div>
              <div className="row">
                {/* Status badge driven by the live run state. */}
                <span className="badge" style={{ background: stateColor(state) }}>
                  {state}
                </span>
                {running ? (
                  <button className="btn small" onClick={() => unload(m.id)}>
                    Unload
                  </button>
                ) : (
                  <button className="btn small" onClick={() => load(m.id)}>
                    Load
                  </button>
                )}
                <button className="btn small ghost" onClick={() => toggleLogs(m.id)}>
                  Logs
                </button>
              </div>
            </div>

            {/* Inline log viewer (collapsed by default). */}
            {openLogs === m.id && (
              <pre className="logs">
                {logLines.length ? logLines.join("\n") : "(no logs)"}
              </pre>
            )}
            {m.run?.error && <div className="error">{m.run.error}</div>}
          </div>
        );
      })}
    </div>
  );
}
