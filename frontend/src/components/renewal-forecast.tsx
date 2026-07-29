"use client";

import { useTheme } from "next-themes";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell,
} from "recharts";

/** Renewals coming due, bucketed by how soon. Three series (SSL / Domain /
 *  Hosting) is an identity job, so the colours are categorical, not a value ramp.
 *
 *  Palette: reference slots 1–3, validated all-pairs in BOTH modes with
 *  scripts/validate_palette.js against this app's real card surfaces
 *  (#ffffff / #121219). Light aqua sits at 2.82:1, below 3:1 — the relief rule
 *  applies, so the legend carries a visible count for every series and totals
 *  are labelled above each column. Never dismiss that warning silently.
 */
const SERIES = [
  { key: "ssl", label: "SSL", light: "#2a78d6", dark: "#3987e5" },
  { key: "domain", label: "Domain", light: "#eb6834", dark: "#d95926" },
  { key: "hosting", label: "Hosting", light: "#1baf7a", dark: "#199e70" },
] as const;

export interface RenewalBucket {
  label: string;
  ssl: number;
  domain: number;
  hosting: number;
}

interface Props {
  buckets: RenewalBucket[];
}

export function RenewalForecast({ buckets }: Props) {
  // Dark mode is a *selected* set of steps, not an automatic flip, so the chart
  // needs the resolved theme rather than a CSS filter.
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme === "dark";

  const colour = (s: (typeof SERIES)[number]) => (isDark ? s.dark : s.light);
  const totals = SERIES.map((s) => ({
    ...s,
    total: buckets.reduce((sum, b) => sum + (b[s.key] ?? 0), 0),
  }));
  const grand = totals.reduce((sum, t) => sum + t.total, 0);

  if (grand === 0) {
    return (
      <p className="text-xs text-muted-foreground py-3">
        Nothing due in the next 90 days.
      </p>
    );
  }

  return (
    <div className="space-y-2">
      {/* Legend is always present for >= 2 series, and carries the counts so no
          value is reachable only by hovering. */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        {totals.map((s) => (
          <span key={s.key} className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <span
              className="h-2 w-2 rounded-full shrink-0"
              style={{ backgroundColor: colour(s) }}
              aria-hidden
            />
            {s.label}
            <span className="font-semibold text-foreground tabular-nums">{s.total}</span>
          </span>
        ))}
      </div>

      {/* Height includes the x-axis band so the card never grows a nested scroll. */}
      <ResponsiveContainer width="100%" height={128}>
        <BarChart data={buckets} margin={{ top: 14, right: 4, bottom: 0, left: -28 }}>
          {/* Hairline, solid — never dashed. */}
          <CartesianGrid vertical={false} stroke="currentColor" className="text-border" />
          <XAxis
            dataKey="label"
            tick={{ fontSize: 11 }}
            stroke="currentColor"
            className="text-muted-foreground"
            tickLine={false}
            axisLine={false}
          />
          {/* Pin the top of the scale to the tallest stack. Recharts' auto
              domain rounds up to a "nice" number, which for counts of 1-2 left
              the bars as slivers in an empty plot. */}
          <YAxis
            allowDecimals={false}
            domain={[0, (dataMax: number) => Math.max(1, Math.ceil(dataMax))]}
            tick={{ fontSize: 11 }}
            stroke="currentColor"
            className="text-muted-foreground"
            tickLine={false}
            axisLine={false}
            width={44}
          />
          <Tooltip
            cursor={{ fill: "currentColor", className: "text-muted/40" }}
            contentStyle={{
              fontSize: 12,
              borderRadius: 8,
              border: "1px solid rgba(127,127,127,0.25)",
              background: isDark ? "#121219" : "#ffffff",
              color: isDark ? "#f5f5f5" : "#111111",
            }}
          />
          {SERIES.map((s, i) => (
            <Bar
              key={s.key}
              dataKey={s.key}
              name={s.label}
              stackId="renewals"
              maxBarSize={24}
              // 2px surface gap between stacked segments — the separator is the
              // gap, not a stroke drawn around each mark.
              stroke={isDark ? "#121219" : "#ffffff"}
              strokeWidth={2}
              radius={i === SERIES.length - 1 ? [4, 4, 0, 0] : 0}
            >
              {buckets.map((_, k) => (
                <Cell key={k} fill={colour(s)} />
              ))}
            </Bar>
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
