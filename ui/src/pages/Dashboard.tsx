// ---------------------------------------------------------------------------
// Dashboard page — live system overview: CPU/RAM trends, backends, loaded models.
// ---------------------------------------------------------------------------
import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { SystemResponse } from "../api/types";
import { useMetrics } from "../hooks/useMetrics";
import { Sparkline } from "../components/Sparkline";
import { StatCard } from "../components/StatCard";
import { formatBytes, formatPercent, stateColor } from "../util/format";

/** The default landing view: hardware, backends, and live resource charts. */
export function Dashboard() {
  // Static-ish system info, fetched once on mount.
  const [system, setSystem] = useState<SystemResponse | null>(null);
  // Live metrics snapshot from the WebSocket hook.
  const snapshot = useMetrics();
  // Rolling history buffers for the sparklines (kept in refs to avoid re-renders
  // resetting them); mirrored into state so the chart updates.
  const cpuHist = useRef<number[]>([]);
  const ramHist = useRef<number[]>([]);
  const [, force] = useState(0); // tiny tick to re-render on new samples

  useEffect(() => {
    // Load hardware + backend availability once.
    api.system().then(setSystem).catch(console.error);
  }, []);

  useEffect(() => {
    // Append each new snapshot to the rolling history (cap at 60 points).
    if (snapshot?.system) {
      cpuHist.current = [...cpuHist.current, snapshot.system.cpu_percent].slice(-60);
      const ramPct =
        (snapshot.system.ram_used_bytes / snapshot.system.ram_total_bytes) * 100;
      ramHist.current = [...ramHist.current, ramPct].slice(-60);
      force((n) => n + 1);
    }
  }, [snapshot]);

  const sys = snapshot?.system;

  return (
    <div className="page">
      <h2>Dashboard</h2>

      {/* Top row: headline resource stats with sparklines. */}
      <div className="grid">
        <StatCard
          label="CPU"
          value={sys ? formatPercent(sys.cpu_percent) : "—"}
          sub={<Sparkline data={cpuHist.current} max={100} color="#22c55e" />}
        />
        <StatCard
          label="RAM"
          value={
            sys
              ? `${formatBytes(sys.ram_used_bytes)} / ${formatBytes(sys.ram_total_bytes)}`
              : "—"
          }
          sub={<Sparkline data={ramHist.current} max={100} color="#3b82f6" />}
        />
        <StatCard
          label="Loaded models"
          value={snapshot?.models.length ?? 0}
        />
      </div>

      {/* Backends availability list. */}
      <h3>Backends</h3>
      <div className="grid">
        {system?.backends.map((b) => (
          <div key={b.name} className="card">
            <div className="row">
              <strong>{b.name}</strong>
              <span
                className="badge"
                style={{ background: b.available ? "#22c55e" : "#6b7280" }}
              >
                {b.available ? "available" : "missing"}
              </span>
            </div>
            <div className="muted">{b.version ?? b.detail}</div>
          </div>
        ))}
      </div>

      {/* Currently loaded models with their state + memory. */}
      <h3>Running models</h3>
      {snapshot && snapshot.models.length > 0 ? (
        <table className="table">
          <thead>
            <tr>
              <th>Model</th>
              <th>State</th>
              <th>Resident</th>
            </tr>
          </thead>
          <tbody>
            {snapshot.models.map((m) => (
              <tr key={m.model_id}>
                <td>{m.model_id}</td>
                <td>
                  <span className="dot" style={{ background: stateColor(m.state) }} />
                  {m.state}
                </td>
                <td>{formatBytes(m.resident_bytes)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="muted">No models loaded.</p>
      )}
    </div>
  );
}
