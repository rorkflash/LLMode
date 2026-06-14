// ---------------------------------------------------------------------------
// Sparkline — a dependency-free inline SVG line chart for live metric history.
//
// Uses a fixed viewBox coordinate space (VB_W × VB_H) for point math, then
// renders the SVG at width="100%" so it always fills its parent container
// without overflowing. height is still a fixed pixel prop so cards stay a
// consistent size regardless of their width.
// ---------------------------------------------------------------------------

// Internal coordinate space used for all point calculations.
// The SVG scales to any rendered width via viewBox, so these numbers only
// affect precision, not the visible size.
const VB_W = 300;
const VB_H = 60;

interface SparklineProps {
  data: number[]; // series values, oldest first / most recent last
  max?: number;   // optional fixed upper bound (e.g. 100 for percentages)
  height?: number; // rendered pixel height; width is always 100% of the parent
  color?: string;
}

/** Render a series of numbers as a normalized SVG polyline. */
export function Sparkline({
  data,
  max,
  height = 48,
  color = "#22c55e",
}: SparklineProps) {
  // Render an empty placeholder that still reserves the right height.
  if (data.length === 0) {
    return <svg width="100%" height={height} viewBox={`0 0 ${VB_W} ${VB_H}`} />;
  }

  // Determine the value ceiling to normalize against.
  const hi = max ?? Math.max(...data, 1);

  // Map each sample to a point in viewBox space.
  // X spans 0..VB_W across the data window; Y is inverted (SVG origin top-left).
  const points = data
    .map((v, i) => {
      const x = (i / Math.max(1, data.length - 1)) * VB_W;
      const y = VB_H - (v / hi) * VB_H;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  return (
    // width="100%" + viewBox: the SVG fills its container horizontally and
    // scales the polyline proportionally. preserveAspectRatio="none" stretches
    // the chart to fill the full width rather than letterboxing.
    <svg
      width="100%"
      height={height}
      viewBox={`0 0 ${VB_W} ${VB_H}`}
      preserveAspectRatio="none"
      className="sparkline"
    >
      <polyline points={points} fill="none" stroke={color} strokeWidth={3} />
    </svg>
  );
}
