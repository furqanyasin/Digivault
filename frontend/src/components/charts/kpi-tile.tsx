"use client";

import { useEffect, useRef } from "react";
import Link from "next/link";
import { CountUp } from "countup.js";
import { Line } from "react-chartjs-2";
import {
  Chart as ChartJS, LineElement, PointElement, LinearScale, CategoryScale, Filler, Tooltip,
} from "chart.js";
import { Card, CardContent } from "@/components/ui/card";
import { alpha } from "@/lib/chart-theme";
import { useChartTheme } from "./use-chart-theme";

ChartJS.register(LineElement, PointElement, LinearScale, CategoryScale, Filler, Tooltip);

export interface KpiTileProps {
  label: string;
  /** Numeric value drives the count-up; `suffix` carries units like "%". */
  value: number;
  suffix?: string;
  decimals?: number;
  caption: string;
  /** Renders the caption as an alert rather than ambient text. */
  captionTone?: "muted" | "critical";
  href: string;
  icon: React.ReactNode;
  /** Oldest → newest. `null` = no data for that bucket, never zero. */
  trend: (number | null)[];
  trendLabel: string;
  /** Which way is good, so a rising line isn't coloured as success by default. */
  goodDirection: "up" | "down";
}

/** Animated numeric value. CountUp handles the tween; we only feed it the
 *  target and honour prefers-reduced-motion by jumping straight to it. */
function AnimatedValue({
  value, suffix, decimals = 0,
}: { value: number; suffix?: string; decimals?: number }) {
  const ref = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced) {
      el.textContent = value.toFixed(decimals) + (suffix ?? "");
      return;
    }
    const counter = new CountUp(el, value, {
      duration: 1.1,
      decimalPlaces: decimals,
      suffix: suffix ?? "",
      separator: ",",
      // Proportional figures on a display-size number; tabular only in columns.
      useEasing: true,
    });
    if (counter.error) {
      el.textContent = value.toFixed(decimals) + (suffix ?? "");
      return;
    }
    counter.start();
    return () => counter.reset();
  }, [value, suffix, decimals]);

  // Server render shows the final value, so the number is correct with JS off
  // and there is no blank frame before the tween starts.
  return <span ref={ref}>{value.toFixed(decimals) + (suffix ?? "")}</span>;
}

export function KpiTile({
  label, value, suffix, decimals, caption, captionTone = "muted",
  href, icon, trend, trendLabel, goodDirection,
}: KpiTileProps) {
  const { tokens, mounted } = useChartTheme();

  const real = trend.filter((v): v is number => v != null);
  const hasTrend = real.length >= 2;
  const first = real[0];
  const last = real[real.length - 1];
  const flat = last === first;
  const improving = goodDirection === "up" ? last > first : last < first;
  const lineColour = flat
    ? tokens.muted
    : improving
      ? tokens.status.good
      : tokens.status.critical;

  return (
    <Link href={href} className="group">
      <Card className="h-full transition-all hover:border-primary/40 hover:shadow-md">
        <CardContent className="p-5">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                {label}
              </p>
              <p className="mt-1.5 text-3xl font-semibold leading-none">
                <AnimatedValue value={value} suffix={suffix} decimals={decimals} />
              </p>
            </div>
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
              {icon}
            </span>
          </div>

          {/* Fixed height whether or not a line renders, so tiles stay aligned
              and nothing shifts when the theme resolves. */}
          <div className="mt-3 h-[34px]">
            {hasTrend && mounted ? (
              <Line
                aria-label={trendLabel}
                data={{
                  labels: trend.map((_, i) => String(i)),
                  datasets: [
                    {
                      data: trend,
                      borderColor: lineColour,
                      borderWidth: 2,
                      // ~10% wash, per the mark spec — never a saturated block.
                      backgroundColor: alpha(lineColour, 0.12),
                      fill: true,
                      tension: 0.35,
                      pointRadius: 0,
                      // A null point breaks the line instead of being bridged,
                      // so a gap in the data never reads as a steady run.
                      spanGaps: false,
                      pointHoverRadius: 4,
                      pointHoverBackgroundColor: lineColour,
                      pointHoverBorderColor: tokens.surface,
                      pointHoverBorderWidth: 2,
                    },
                  ],
                }}
                options={{
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
                      displayColors: false,
                      padding: 8,
                      callbacks: {
                        title: () => trendLabel,
                        label: (c) => `${c.formattedValue}${suffix ?? ""}`,
                      },
                    },
                  },
                  scales: { x: { display: false }, y: { display: false } },
                  elements: { line: { capBezierPoints: true } },
                }}
              />
            ) : (
              <p className="pt-2 text-[11px] text-muted-foreground/70">
                {hasTrend ? "" : "No trend data for this range"}
              </p>
            )}
          </div>

          <p
            className={`mt-1 text-xs ${
              captionTone === "critical" ? "font-semibold text-red-600" : "text-muted-foreground"
            }`}
          >
            {caption}
          </p>
        </CardContent>
      </Card>
    </Link>
  );
}
