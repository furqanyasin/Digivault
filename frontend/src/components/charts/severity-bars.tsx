"use client";

import { Bar } from "react-chartjs-2";
import {
  Chart as ChartJS, BarElement, LinearScale, CategoryScale, Tooltip,
} from "chart.js";
import { useChartTheme } from "./use-chart-theme";

ChartJS.register(BarElement, LinearScale, CategoryScale, Tooltip);

export interface SeverityCounts {
  critical: number;
  high: number;
  medium: number;
  low: number;
}

/** Severity is an ORDERED scale, so this uses the ordinal one-hue ramp
 *  (darkest = worst) rather than the status palette.
 *
 *  The obvious choice — red/orange/amber/slate to match the badges — was
 *  measured and rejected: orange vs amber comes out at normal-vision ΔE 9.6,
 *  below the 15 floor, so a full-colour reader cannot reliably tell "high" from
 *  "medium", let alone a colourblind one. The ordinal blue ramp passes every
 *  check (monotone lightness, adjacent ΔL, light end clears the surface), and
 *  each bar is directly labelled, so identity never rests on hue alone.
 */
const RAMP_LIGHT = ["#184f95", "#256abf", "#3987e5", "#86b6ef"];
const RAMP_DARK = ["#9ec5f4", "#6da7ec", "#3987e5", "#256abf"];

const ROWS = [
  { key: "critical", label: "Critical" },
  { key: "high", label: "High" },
  { key: "medium", label: "Medium" },
  { key: "low", label: "Low" },
] as const;

export function SeverityBars({ counts }: { counts: SeverityCounts }) {
  const { tokens, isDark, mounted } = useChartTheme();
  const ramp = isDark ? RAMP_DARK : RAMP_LIGHT;

  const total = ROWS.reduce((sum, r) => sum + (counts[r.key] ?? 0), 0);
  if (total === 0) {
    return (
      <p className="py-10 text-center text-sm text-muted-foreground">
        No open alerts. Nothing to triage.
      </p>
    );
  }

  const values = ROWS.map((r) => counts[r.key] ?? 0);

  return (
    <div className="space-y-3">
      <div className="h-[150px]">
        {mounted && (
          <Bar
            aria-label="Open alerts by severity"
            data={{
              labels: ROWS.map((r) => r.label),
              datasets: [
                {
                  data: values,
                  backgroundColor: ramp,
                  // 4px rounded data-end, square at the baseline.
                  borderRadius: { topLeft: 0, topRight: 4, bottomLeft: 0, bottomRight: 4 },
                  borderSkipped: false,
                  maxBarThickness: 20,
                },
              ],
            }}
            options={{
              indexAxis: "y",
              responsive: true,
              maintainAspectRatio: false,
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
                  displayColors: false,
                  callbacks: {
                    label: (c) =>
                      ` ${c.formattedValue} of ${total} open (${Math.round(
                        (Number(c.raw) / total) * 100
                      )}%)`,
                  },
                },
              },
              scales: {
                x: {
                  beginAtZero: true,
                  // Pinned to the real max: Chart.js' "nice" rounding leaves
                  // counts of 1-2 as slivers.
                  max: Math.max(1, ...values),
                  grid: { color: tokens.grid, lineWidth: 1 },
                  border: { display: false },
                  ticks: { color: tokens.muted, font: { size: 11 }, stepSize: 1, precision: 0 },
                },
                y: {
                  grid: { display: false },
                  border: { display: false },
                  ticks: { color: tokens.muted, font: { size: 11 } },
                },
              },
            }}
          />
        )}
      </div>

      {/* Counts in text as well as bars — the values are never hover-only. */}
      <ul className="flex flex-wrap gap-x-4 gap-y-1">
        {ROWS.map((r, i) => (
          <li key={r.key} className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <span
              className="h-2 w-2 shrink-0 rounded-full"
              style={{ backgroundColor: ramp[i] }}
              aria-hidden
            />
            {r.label}
            <span className="font-semibold tabular-nums text-foreground">{counts[r.key] ?? 0}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
