// ---------------------------------------------------------------------------
// Catalog page — search the Hugging Face Hub and download models.
// ---------------------------------------------------------------------------
import { useState } from "react";
import { api } from "../api/client";
import type { ModelView } from "../api/types";

/** Search + download UI for discovering new models. */
export function Catalog() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<ModelView[]>([]);
  const [busy, setBusy] = useState(false);
  // Per-model download status messages keyed by repo id.
  const [status, setStatus] = useState<Record<string, string>>({});

  /** Run a catalog search against the daemon. */
  async function runSearch() {
    setBusy(true);
    try {
      setResults(await api.search(query));
    } catch (e) {
      console.error(e);
    } finally {
      setBusy(false);
    }
  }

  /** Trigger a download for a given repo id and reflect progress/result. */
  async function download(repoId: string) {
    setStatus((s) => ({ ...s, [repoId]: "downloading…" }));
    try {
      await api.download(repoId);
      setStatus((s) => ({ ...s, [repoId]: "downloaded ✓" }));
    } catch (e) {
      setStatus((s) => ({ ...s, [repoId]: `failed: ${(e as Error).message}` }));
    }
  }

  return (
    <div className="page">
      <h2>Catalog</h2>

      {/* Search bar. Enter or the button both submit. */}
      <div className="row">
        <input
          className="input"
          placeholder="Search Hugging Face (e.g. 'llama gguf')"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && runSearch()}
        />
        <button className="btn" onClick={runSearch} disabled={busy}>
          {busy ? "Searching…" : "Search"}
        </button>
      </div>

      {/* Result rows with a per-model download button. */}
      <table className="table">
        <thead>
          <tr>
            <th>Model</th>
            <th>Format</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {results.map((m) => (
            <tr key={m.id}>
              <td>{m.id}</td>
              <td>{m.format}</td>
              <td>
                {status[m.id] ? (
                  <span className="muted">{status[m.id]}</span>
                ) : (
                  <button className="btn small" onClick={() => download(m.id)}>
                    Download
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {results.length === 0 && !busy && (
        <p className="muted">Search for a model to get started.</p>
      )}
    </div>
  );
}
