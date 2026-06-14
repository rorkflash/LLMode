// ---------------------------------------------------------------------------
// Small formatting helpers shared across the UI.
// ---------------------------------------------------------------------------

/** Format a byte count as a human-readable string (e.g. 1.5 GB). */
export function formatBytes(bytes: number): string {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  // Pick the largest unit where the value stays >= 1.
  const i = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)));
  return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${units[i]}`;
}

/** Format a 0..100 percentage with one decimal and a % sign. */
export function formatPercent(pct: number): string {
  return `${pct.toFixed(1)}%`;
}

/** Map a model lifecycle state to a CSS color for status dots/badges. */
export function stateColor(state: string): string {
  switch (state) {
    case "ready":
      return "#22c55e"; // green — serving
    case "loading":
    case "unloading":
      return "#f59e0b"; // amber — transitioning
    case "idle":
      return "#3b82f6"; // blue — loaded but unused
    case "error":
      return "#ef4444"; // red — failed
    default:
      return "#6b7280"; // gray — available/unknown
  }
}
