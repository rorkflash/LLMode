// ---------------------------------------------------------------------------
// StatCard — a small labelled metric tile used on the dashboard.
// ---------------------------------------------------------------------------
import type { ReactNode } from "react";

/** Props: a label, the primary value, and an optional sub-line/children. */
interface StatCardProps {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
}

/** Render a single metric as a card (label on top, big value, optional sub). */
export function StatCard({ label, value, sub }: StatCardProps) {
  return (
    <div className="card stat">
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {sub && <div className="stat-sub">{sub}</div>}
    </div>
  );
}
