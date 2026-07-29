"use client";

import { Bar } from "react-chartjs-2";
import {
  Chart as ChartJS, BarElement, LinearScale, CategoryScale, Tooltip,
} from "chart.js";
import { useChartTheme } from "./use-chart-theme";

ChartJS.register(BarElement, LinearScale, CategoryScale, Tooltip);

export interface RenewalBucket {
  label: string;
  ssl: number;
  domain: number;
  hosting: number;
}

const KEYS = [
  { key: "ssl", label: "SSL" },
  { key: "domain", label: "Domain" },
  { key: "hosting", label: "Hosting" },
] as const;

/** Part-to-whole over forward time buckets. Three series is an identity job, so
 *  the colours are the validated categorical slots — three is the cap here, a
 *  fourth would put yellow beside orange and fail the all-pairs gate.
 */
export function RenewalBars({ buckets }: { buckets: RenewalBucket[] }) {
  const { tokens, mounted } = useChartTheme();

  const totals = KEYS.map((k, i) => ({
    ...k,
    colour: tokens.series[i],
    total: buckets.reduce((sum, b) => sum + (b[k.key] ?? 0), 0),
  }));
  const grand = totals.reduce((sum, t) => sum + t.total, 0);

  if (grand === 0) {
    return (
      <p className="py-6 text-sm text-muted-foreground">
        Nothing due in the next 90 days.
      </p>
    );
  }

  const tallest = Math.max(
    1,
    ...buckets.map((b) => (b.ssl ?? 0) + (b.domain ?? 0) + (b.hosting ?? 0))
  );

  return (
    <div className="space-y-3">
      {/* Legend always present for >= 2 series, and carries the counts so no
          value is reachable only by hovering. */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        {totals.map((s) => (
          <span key={s.key} className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <span
              className="h-2 w-2 shrink-0 rounded-full"
              style={{ backgroundColor: s.colour }}
              aria-hidden
            />
            {s.label}
            <span className="font-semibold tabular-nums text-foreground">{s.total}</span>
          </span>
        ))}
      </div>

      {/* Height includes the x-axis band, so the card never grows a nested scroll. */}
      <div className="h-[150px]">
        {mounted && (
          <Bar
            aria-label="Renewals due, by how soon"
            data={{
              labels: buckets.map((b) => b.label),
              datasets: KEYS.map((k, i) => ({
                label: k.label,
                data: buckets.map((b) => b[k.key] ?? 0),
                backgroundColor: tokens.series[i],
                // 2px gap in the surface colour between stacked segments.
                borderColor: tokens.surface,
                borderWidth: { top: 2, right: 0, bottom: 0, left: 0 },
                borderSkipped: false,
                maxBarThickness: 24,
                // Only the top segment gets a rounded data-end; the rest stay
                // square so the stack reads as one column.
                borderRadius:
                  i === KEYS.length - 1
                    ? { topLeft: 4, topRight: 4, bottomLeft: 0, bottomRight: 0 }
                    : 0,
                stack: "renewals",
              })),
            }}
            options={{
              responsive: true,
              maintainAspectRatio: false,
              interaction: { mode: "index", intersect: false },
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
                  boxWidth: 8,
                  boxHeight: 8,
                  filter: (item) => (item.parsed.y as number) > 0,
                },
              },
              scales: {
                x: {
                  stacked: true,
                  grid: { display: false },
                  border: { display: false },
                  ticks: { color: tokens.muted, font: { size: 11 } },
                },
                y: {
                  stacked: true,
                  beginAtZero: true,
                  // Pinned to the tallest stack: Chart.js' auto max rounds up to
                  // a "nice" number, which leaves counts of 1-2 as slivers.
                  max: tallest,
                  ticks: {
                    color: tokens.muted,
                    font: { size: 11 },
                    stepSize: 1,
                    precision: 0,
                  },
                  grid: { color: tokens.grid, lineWidth: 1 },
                  border: { display: false },
                },
              },
            }}
          />
        )}
      </div>
    </div>
  );
}
