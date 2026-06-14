// ---------------------------------------------------------------------------
// Sparkline — a dependency-free inline SVG line chart for live metric history.
//
// We keep charting deps out of the bundle by rendering a tiny SVG polyline.
// Good enough for at-a-glance CPU/RAM trends on the dashboard.
// ---------------------------------------------------------------------------

interface SparklineProps {
  data: number[]; // series values (most recent last)
  max?: number; // optional fixed upper bound (e.g. 100 for percentages)
  width?: number;
  height?: number;
  color?: string;
}

/** Render a series of numbers as a normalized SVG polyline. */
export function Sparkline({
  data,
  max,
  width = 240,
  height = 48,
  color = "#22c55e",
}: SparklineProps) {
  if (data.length === 0) return <svg width={width} height={height} />;

  // Determine the value range to normalize against.
  const hi = max ?? Math.max(...data, 1);
  const lo = 0;

  // Map each sample to an (x, y) point within the SVG viewport.
  const points = data
    .map((v, i) => {
      const x = (i / Math.max(1, data.length - 1)) * width;
      // Invert y because SVG's origin is top-left.
      const y = height - ((v - lo) / (hi - lo)) * height;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  return (
    <svg width={width} height={height} className="sparkline">
      <polyline points={points} fill="none" stroke={color} strokeWidth={2} />
    </svg>
  );
}
