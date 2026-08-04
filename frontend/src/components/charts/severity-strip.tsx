export interface SeverityCounts {
  critical: number;
  high: number;
  medium: number;
  low: number;
}

/** Severity mix as one proportional bar plus counts.
 *
 *  This replaces the separate "Alerts by severity" chart card. That card restated
 *  a number the Alerts card already showed, so it read as padding; as a strip
 *  inside the Alerts card it adds the breakdown without repeating the total.
 *
 *  Severity is an ORDERED scale, so the fill is the ordinal one-hue ramp
 *  (darkest = worst) rather than red/orange/amber to match the badges: that trio
 *  measures normal-vision ΔE 9.6 between orange and amber, below the 15 floor,
 *  so "high" and "medium" would be indistinguishable even with full colour
 *  vision. Every segment is labelled, so identity never rests on hue.
 */
const ROWS = [
  { key: "critical", label: "Critical", light: "#184f95", dark: "#9ec5f4" },
  { key: "high", label: "High", light: "#256abf", dark: "#6da7ec" },
  { key: "medium", label: "Medium", light: "#3987e5", dark: "#3987e5" },
  { key: "low", label: "Low", light: "#86b6ef", dark: "#256abf" },
] as const;

export function SeverityStrip({ counts }: { counts: SeverityCounts }) {
  const total = ROWS.reduce((sum, r) => sum + (counts[r.key] ?? 0), 0);
  if (total === 0) return null;

  const present = ROWS.filter((r) => (counts[r.key] ?? 0) > 0);

  return (
    <div className="mt-4 border-t pt-3">
      <p className="mb-2 text-xs font-medium text-muted-foreground">Severity mix</p>

      {/* 2px surface gaps separate the segments — the gap does the separating,
          not a border drawn around each one. */}
      <div className="flex h-2 w-full gap-0.5 overflow-hidden rounded-full bg-muted">
        {present.map((r) => (
          <div
            key={r.key}
            className="dv-sev"
            style={{
              width: `${((counts[r.key] ?? 0) / total) * 100}%`,
              // Light/dark steps are selected per mode, not flipped.
              ["--sev-light" as string]: r.light,
              ["--sev-dark" as string]: r.dark,
            }}
          />
        ))}
      </div>

      {/* Counts in text as well as in the bar, so no value is hover-only. */}
      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
        {ROWS.map((r) => (
          <li key={r.key} className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <span
              className="dv-sev h-2 w-2 shrink-0 rounded-full"
              style={{
                ["--sev-light" as string]: r.light,
                ["--sev-dark" as string]: r.dark,
              }}
              aria-hidden
            />
            {r.label}
            <span className="font-semibold tabular-nums text-foreground">
              {counts[r.key] ?? 0}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
