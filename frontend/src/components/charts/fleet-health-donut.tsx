"use client";

import { Doughnut } from "react-chartjs-2";
import { Chart as ChartJS, ArcElement, Tooltip } from "chart.js";
import { useChartTheme } from "./use-chart-theme";

ChartJS.register(ArcElement, Tooltip);

export interface HealthBandCounts {
  healthy: number;
  warning: number;
  critical: number;
  inactive: number;
}

/** Part-to-whole across four ordered STATE classes, so the colours come from the
 *  reserved status palette rather than the categorical slots.
 *
 *  A donut is legal here — four segments, read at a glance, and the centre
 *  carries the total. It would be the wrong form for comparing close values;
 *  the counts are printed in the legend for exactly that reason, which also
 *  satisfies the relief rule for the sub-3:1 status hues.
 */
export function FleetHealthDonut({ counts }: { counts: HealthBandCounts }) {
  const { tokens, mounted } = useChartTheme();

  const slices = [
    { key: "healthy", label: "Healthy", hint: "85–100", value: counts.healthy, colour: tokens.status.good },
    { key: "warning", label: "Warning", hint: "60–84", value: counts.warning, colour: tokens.status.warning },
    { key: "critical", label: "Critical", hint: "below 60", value: counts.critical, colour: tokens.status.critical },
    { key: "inactive", label: "Inactive", hint: "paused", value: counts.inactive, colour: tokens.status.neutral },
  ].filter((s) => s.value > 0);

  const total = slices.reduce((sum, s) => sum + s.value, 0);

  if (total === 0) {
    return (
      <p className="py-8 text-center text-sm text-muted-foreground">
        No websites yet.
      </p>
    );
  }

  return (
    <div className="flex items-center gap-5">
      <div className="relative h-[132px] w-[132px] shrink-0">
        {mounted && (
          <Doughnut
            aria-label="Websites by health band"
            data={{
              labels: slices.map((s) => s.label),
              datasets: [
                {
                  data: slices.map((s) => s.value),
                  backgroundColor: slices.map((s) => s.colour),
                  // 2px gap in the surface colour separates touching segments —
                  // the gap does the separating, not a border around each arc.
                  borderColor: tokens.surface,
                  borderWidth: 2,
                  hoverOffset: 4,
                },
              ],
            }}
            options={{
              responsive: true,
              maintainAspectRatio: false,
              cutout: "68%",
              plugins: {
                legend: { display: false },
                tooltip: {
                  backgroundColor: tokens.tooltipBg,
                  titleColor: tokens.tooltipInk,
                  bodyColor: tokens.tooltipInk,
                  borderColor: tokens.grid,
                  borderWidth: 1,
                  padding: 10,
                  cornerRadius: 8,
                  usePointStyle: true,
                  callbacks: {
                    label: (c) => {
                      const n = c.parsed as number;
                      return ` ${c.label}: ${n} (${Math.round((n / total) * 100)}%)`;
                    },
                  },
                },
              },
            }}
          />
        )}
        {/* The total lives in the hole — the one number the ring is about. */}
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-2xl font-semibold leading-none">{total}</span>
          <span className="mt-0.5 text-[10px] uppercase tracking-wide text-muted-foreground">
            sites
          </span>
        </div>
      </div>

      {/* Legend carries every count, so no value is reachable by hover alone. */}
      <ul className="min-w-0 flex-1 space-y-1.5">
        {slices.map((s) => (
          <li key={s.key} className="flex items-center gap-2 text-sm">
            <span
              className="h-2.5 w-2.5 shrink-0 rounded-full"
              style={{ backgroundColor: s.colour }}
              aria-hidden
            />
            <span className="truncate text-muted-foreground">{s.label}</span>
            <span className="ml-auto shrink-0 tabular-nums font-semibold">{s.value}</span>
            <span className="w-16 shrink-0 text-right text-xs text-muted-foreground">
              {Math.round((s.value / total) * 100)}%
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
