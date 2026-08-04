"use client";

import { Line } from "react-chartjs-2";
import {
  Chart as ChartJS, LineElement, PointElement, LinearScale, CategoryScale, Filler, Tooltip,
} from "chart.js";
import { alpha } from "@/lib/chart-theme";
import { useChartTheme } from "./use-chart-theme";

ChartJS.register(LineElement, PointElement, LinearScale, CategoryScale, Filler, Tooltip);

export interface AreaSeries {
  label: string;
  /** Aligned with `labels`. `null` = unobserved, and stays a gap. */
  data: (number | null)[];
  /** "series" takes categorical slot 1; "status" tones are for state. */
  tone?: "series" | "critical";
  /** Percentages get a 0–100 axis and a % suffix. */
  unit?: "count" | "percent";
}

/** Trend over time. One series → no legend box (the title names it); two →
 *  a legend is rendered by the caller alongside the heading.
 */
export function ActivityAreaChart({
  labels, series, height = 190,
}: {
  labels: string[];
  series: AreaSeries[];
  height?: number;
}) {
  const { tokens, mounted } = useChartTheme();

  const colourFor = (s: AreaSeries) =>
    s.tone === "critical" ? tokens.status.critical : tokens.series[0];

  const isPercent = series.some((s) => s.unit === "percent");
  const anyData = series.some((s) => s.data.some((v) => v != null));

  if (!anyData) {
    return (
      <div className="flex items-center justify-center text-sm text-muted-foreground" style={{ height }}>
        No data in this range.
      </div>
    );
  }

  return (
    <div style={{ height }}>
      {mounted && (
        <Line
          aria-label={series.map((s) => s.label).join(", ")}
          data={{
            labels,
            datasets: series.map((s) => {
              const colour = colourFor(s);
              return {
                label: s.label,
                data: s.data,
                borderColor: colour,
                borderWidth: 2,
                backgroundColor: alpha(colour, 0.1),
                fill: true,
                tension: 0.35,
                pointRadius: 0,
                pointHoverRadius: 4,
                pointHoverBackgroundColor: colour,
                pointHoverBorderColor: tokens.surface,
                pointHoverBorderWidth: 2,
                spanGaps: false,
              };
            }),
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
                callbacks: {
                  label: (c) =>
                    ` ${c.dataset.label}: ${c.formattedValue}${isPercent ? "%" : ""}`,
                },
              },
            },
            scales: {
              x: {
                grid: { display: false },
                border: { display: false },
                ticks: {
                  color: tokens.muted,
                  font: { size: 11 },
                  maxRotation: 0,
                  autoSkipPadding: 16,
                },
              },
              y: {
                beginAtZero: !isPercent,
                // Uptime lives in the top few percent; a 0–100 axis would flatten
                // every dip into the baseline.
                suggestedMin: isPercent ? undefined : 0,
                // Solid hairline gridlines, one step off the surface. Never dashed.
                grid: { color: tokens.grid, lineWidth: 1 },
                border: { display: false },
                ticks: {
                  color: tokens.muted,
                  font: { size: 11 },
                  precision: 0,
                  callback: (v) => `${v}${isPercent ? "%" : ""}`,
                },
              },
            },
          }}
        />
      )}
    </div>
  );
}
