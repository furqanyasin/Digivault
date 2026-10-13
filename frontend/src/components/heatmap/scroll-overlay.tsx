"use client";

export interface ScrollStop {
  /** Page depth as a percentage, 0 = top. */
  y: number;
  /** Share of visits that reached at least this far, 0..1. */
  share: number;
}

interface Props {
  stops: ScrollStop[];
  height: number;
}

/**
 * Hotjar-style scroll map.
 *
 * The whole page is tinted by how many visitors reached each depth — warm and
 * bright where nearly everyone saw, cold and dark where almost nobody did — and
 * the depth at which half the audience has dropped away is called out as the
 * "average fold". This replaced a 3.5px-wide strip pinned to the left edge,
 * which technically carried the same numbers but told nobody anything at a
 * glance.
 */

// Reach scale, warm to cold. Deliberately not the click gradient: a scroll map
// answers "how many people got here", not "where did they click", and using the
// same colours for both invites the two maps to be read as one.
function reachColor(share: number, alpha = 0.62): string {
  const t = Math.max(0, Math.min(1, share));
  // 100% reach -> amber; 50% -> magenta-red; 0% -> deep blue.
  if (t >= 0.5) {
    const k = (t - 0.5) / 0.5;
    const r = Math.round(220 + 35 * k);
    const g = Math.round(60 + 150 * k);
    const b = Math.round(70 - 40 * k);
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
  }
  const k = t / 0.5;
  const r = Math.round(30 + 190 * k);
  const g = Math.round(50 + 10 * k);
  const b = Math.round(140 - 70 * k);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

/** Reach at an arbitrary depth, linearly interpolated between reported bands. */
function shareAt(stops: ScrollStop[], y: number): number {
  if (!stops.length) return 0;
  if (y <= stops[0].y) return stops[0].share;
  for (let i = 1; i < stops.length; i++) {
    if (y <= stops[i].y) {
      const a = stops[i - 1];
      const b = stops[i];
      const span = b.y - a.y || 1;
      return a.share + ((b.share - a.share) * (y - a.y)) / span;
    }
  }
  return stops[stops.length - 1].share;
}

/** The depth where reach crosses 50% — where half the audience has gone. */
function averageFold(stops: ScrollStop[]): number | null {
  for (let i = 0; i < stops.length; i++) {
    if (stops[i].share < 0.5) {
      if (i === 0) return stops[0].y;
      const a = stops[i - 1];
      const b = stops[i];
      const span = a.share - b.share || 1;
      return a.y + ((a.share - 0.5) / span) * (b.y - a.y);
    }
  }
  return null;
}

export function ScrollOverlay({ stops, height }: Props) {
  if (!stops.length) return null;

  // A gradient stop every 2% keeps the interpolation smooth even when the
  // histogram only reports every 5%.
  const gradientStops: string[] = [];
  for (let y = 0; y <= 100; y += 2) {
    gradientStops.push(`${reachColor(shareAt(stops, y))} ${y}%`);
  }
  const fold = averageFold(stops);

  // Label a handful of depths rather than all twenty bands — the tint carries
  // the shape, the labels only need to make it readable.
  const labelled = stops.filter((s) => s.y % 25 === 0 || s.y === 100);

  return (
    <div className="pointer-events-none absolute inset-0 z-10" aria-hidden="true">
      <div
        className="absolute inset-0"
        style={{ background: `linear-gradient(to bottom, ${gradientStops.join(", ")})` }}
      />

      {labelled.map((s) => (
        <div
          key={s.y}
          className="absolute inset-x-0 flex items-center justify-between px-2"
          style={{ top: `${s.y}%`, transform: "translateY(-50%)" }}
        >
          <span className="rounded bg-black/70 px-1.5 py-0.5 text-[10px] font-medium tabular-nums text-white">
            {Math.round(s.share * 100)}% reached
          </span>
          <span className="rounded bg-black/50 px-1.5 py-0.5 text-[10px] tabular-nums text-white/80">
            {s.y}% depth
          </span>
        </div>
      ))}

      {fold !== null && height > 0 && (
        <div
          className="absolute inset-x-0 border-t-2 border-dashed border-white"
          style={{ top: `${Math.min(100, fold)}%` }}
        >
          <span className="absolute left-1/2 top-0 -translate-x-1/2 -translate-y-1/2 whitespace-nowrap rounded bg-white px-2 py-0.5 text-[10px] font-semibold text-black shadow">
            Average fold — half your visitors stop here
          </span>
        </div>
      )}
    </div>
  );
}
