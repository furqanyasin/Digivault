"use client";

import { useChartTheme } from "./use-chart-theme";

export interface UrgencyRow {
  label: string;
  urgent: number;
  soon: number;
  later: number;
}

/** Urgency is a *state*, so the segments wear the reserved status colours
 *  rather than the categorical slots — red/amber/neutral already mean
 *  critical/warning/idle everywhere else in the app. Each band ships a written
 *  label and a number in the legend, so nothing is reachable by colour alone. */
const BANDS = [
  { key: "urgent", label: "Urgent", hint: "Overdue or due within 7 days", tone: "critical" },
  { key: "soon", label: "Soon", hint: "Due in 8–30 days", tone: "warning" },
  { key: "later", label: "Later", hint: "Due in 31–90 days", tone: "neutral" },
] as const;

/** Part-to-whole across three fixed rows. A horizontal stack is the right form
 *  here: the counts are heavily skewed toward "later", which leaves a vertical
 *  column chart mostly empty, and the row labels read straight without rotation. */
export function RenewalUrgencyBars({ rows }: { rows: UrgencyRow[] }) {
  // No `mounted` guard, unlike the canvas charts: this renders real HTML during
  // SSR, so a token that differed between modes would land as a hydration
  // mismatch on the inline style. The status steps are deliberately identical in
  // both modes (see chart-theme.ts), which is what makes that safe — re-step
  // them per mode and this needs the same placeholder treatment as the others.
  const { tokens } = useChartTheme();
  const colour = {
    urgent: tokens.status.critical,
    soon: tokens.status.warning,
    later: tokens.status.neutral,
  };

  const totals = BANDS.map((b) => ({
    ...b,
    total: rows.reduce((sum, r) => sum + (r[b.key] ?? 0), 0),
  }));
  const grand = totals.reduce((s, t) => s + t.total, 0);

  if (grand === 0) {
    return <p className="py-6 text-sm text-muted-foreground">Nothing due in the next 90 days.</p>;
  }

  // One shared scale across rows, so bar lengths are comparable between types.
  const widest = Math.max(1, ...rows.map((r) => r.urgent + r.soon + r.later));

  return (
    <div className="space-y-4">
      {/* Legend carries the totals, so no value needs a hover to reach. */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        {totals.map((b) => (
          <span key={b.key} className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <span
              className="h-2 w-2 shrink-0 rounded-full"
              style={{ backgroundColor: colour[b.key] }}
              aria-hidden
            />
            {b.label}
            <span className="font-semibold tabular-nums text-foreground">{b.total}</span>
          </span>
        ))}
      </div>

      <div className="space-y-3">
        {rows.map((r) => {
          const total = r.urgent + r.soon + r.later;
          return (
            <div key={r.label} className="grid grid-cols-[88px_1fr_2.5rem] items-center gap-3">
              <span className="text-xs text-muted-foreground truncate">{r.label}</span>

              {/* Track keeps every row the same length so the bars share a scale. */}
              <div className="h-6 w-full">
                {total === 0 ? (
                  <div className="h-full w-full rounded bg-muted/50" />
                ) : (
                  <div
                    className="flex h-full gap-[2px]"
                    style={{ width: `${(total / widest) * 100}%` }}
                    role="img"
                    aria-label={`${r.label}: ${BANDS.map((b) => `${r[b.key]} ${b.label.toLowerCase()}`).join(", ")}`}
                  >
                    {BANDS.map((b, i) => {
                      const v = r[b.key] ?? 0;
                      if (v === 0) return null;
                      const isFirst = BANDS.slice(0, i).every((p) => (r[p.key] ?? 0) === 0);
                      const isLast = BANDS.slice(i + 1).every((n) => (r[n.key] ?? 0) === 0);
                      return (
                        <div
                          key={b.key}
                          title={`${r.label} · ${b.label} — ${b.hint}: ${v}`}
                          className="flex items-center justify-center overflow-hidden"
                          style={{
                            flexGrow: v,
                            flexBasis: 0,
                            backgroundColor: colour[b.key],
                            // 4px rounded data-ends; inner edges stay square so
                            // the segments read as one bar.
                            borderTopLeftRadius: isFirst ? 4 : 0,
                            borderBottomLeftRadius: isFirst ? 4 : 0,
                            borderTopRightRadius: isLast ? 4 : 0,
                            borderBottomRightRadius: isLast ? 4 : 0,
                          }}
                        >
                          {/* Direct label, but only where it actually fits. */}
                          {v / widest > 0.08 && (
                            <span className="px-1 text-[11px] font-semibold tabular-nums text-white">
                              {v}
                            </span>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>

              <span className="text-right text-xs font-semibold tabular-nums">{total}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
