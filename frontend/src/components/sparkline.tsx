/** A stat-tile trend line. Server-rendered inline SVG — no client JS, no
 *  hydration, no layout shift for something this small.
 *
 *  Gaps are honest: a `null` point breaks the line rather than being smoothed
 *  over, so a stretch with no data never reads as a flat healthy run.
 */

interface Props {
  /** Oldest → newest. `null` means "no data for this bucket", not zero. */
  points: (number | null)[];
  /** Accessible summary — the sparkline is decoration without it. */
  label: string;
  /** Higher is better (uptime) vs higher is worse (open alerts). Only affects
   *  the end-dot tone, never the geometry. */
  goodDirection?: "up" | "down";
  width?: number;
  height?: number;
}

const STROKE = 2;
const DOT_R = 3;

export function Sparkline({
  points,
  label,
  goodDirection = "up",
  width = 88,
  height = 30,
}: Props) {
  const real = points.filter((p): p is number => p != null);
  // Two points is the minimum that can describe a direction. Below that the
  // caller shows a "not enough history" note instead of a misleading flat line.
  if (real.length < 2) return null;

  const min = Math.min(...real);
  const max = Math.max(...real);
  const span = max - min || 1;

  const padX = DOT_R + 1;
  const padY = DOT_R + 1;
  const plotW = width - padX * 2;
  const plotH = height - padY * 2;

  const x = (i: number) =>
    points.length === 1 ? padX : padX + (i / (points.length - 1)) * plotW;
  const y = (v: number) => padY + plotH - ((v - min) / span) * plotH;

  // Split into contiguous runs so nulls leave real gaps.
  const runs: { i: number; v: number }[][] = [];
  let run: { i: number; v: number }[] = [];
  points.forEach((v, i) => {
    if (v == null) {
      if (run.length) runs.push(run);
      run = [];
    } else {
      run.push({ i, v });
    }
  });
  if (run.length) runs.push(run);

  // Last index that actually holds data — the end dot must sit on a real
  // observation, not on a trailing gap.
  const lastIdx = points.reduce<number>((acc, v, i) => (v != null ? i : acc), -1);
  const lastVal = points[lastIdx] as number;
  const firstVal = real[0];
  const rising = lastVal > firstVal;
  // Direction is only "good" or "bad" once you know which way is which.
  const improving = goodDirection === "up" ? rising : !rising;
  const dotClass = lastVal === firstVal
    ? "fill-muted-foreground"
    : improving
      ? "fill-emerald-600 dark:fill-emerald-500"
      : "fill-red-600 dark:fill-red-500";

  const areaOf = (r: { i: number; v: number }[]) =>
    r.length < 2
      ? ""
      : `M ${x(r[0].i)} ${height - padY} ` +
        r.map((p) => `L ${x(p.i)} ${y(p.v)}`).join(" ") +
        ` L ${x(r[r.length - 1].i)} ${height - padY} Z`;

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={label}
      className="overflow-visible shrink-0"
    >
      <title>{label}</title>
      {/* Area wash at ~10%, per the mark spec — never a saturated block. */}
      {runs.map((r, k) => (
        <path key={`a${k}`} d={areaOf(r)} className="fill-muted-foreground/10" />
      ))}
      {/* The line itself sits in the de-emphasis tone; the tile's number is the
          thing being read, the trend is context. */}
      {runs.map((r, k) => (
        <polyline
          key={`l${k}`}
          points={r.map((p) => `${x(p.i)},${y(p.v)}`).join(" ")}
          fill="none"
          strokeWidth={STROKE}
          strokeLinecap="round"
          strokeLinejoin="round"
          className="stroke-muted-foreground/60"
        />
      ))}
      {/* End dot carries the accent + a 2px surface ring so it stays legible
          where it crosses the line. */}
      <circle
        cx={x(lastIdx)}
        cy={y(lastVal)}
        r={DOT_R + 1}
        className="fill-card"
      />
      <circle cx={x(lastIdx)} cy={y(lastVal)} r={DOT_R} className={dotClass} />
    </svg>
  );
}
