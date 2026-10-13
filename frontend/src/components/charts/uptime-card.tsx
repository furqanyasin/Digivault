"use client";

import { Card, CardContent } from "@/components/ui/card";
import { ChartCardHeader } from "./chart-card-header";
import { ActivityAreaChart } from "./activity-area-chart";
import {
  rangeCaption, useDashboardWindow, windowDays,
} from "@/lib/dashboard-window";

interface Props {
  /** The widest window (90 days), fetched once. Sliced here per selection. */
  points: { date: string; value: number | null; up?: number; total?: number }[];
  /** Per-monitor 30-day average. Only a fallback for a backend that does not
   *  send `up`/`total` yet — it ignores the selected window. */
  avgUptime: number | null;
  monitorsDown: number;
}

/** Uptime over the selected window.
 *
 *  Client-side so changing the preset re-slices in place. It used to be a server
 *  component, which meant every preset click was a full navigation that refetched
 *  all ten dashboard endpoints to change this one series.
 */
export function UptimeCard({ points, avgUptime, monitorsDown }: Props) {
  const win = useDashboardWindow();
  const days = windowDays(win);
  const byDay = new Map(points.map((p) => [p.date, p]));
  const series = days.map((d) => byDay.get(d)?.value ?? null);

  // The headline pools the window's checks, so it is the same number the curve
  // is drawn from. It used to be the mean of each monitor's cached uptime_30d:
  // a 30-day figure under a "last 7 days" caption, never agreeing with the chart.
  let up = 0;
  let total = 0;
  let hasCounts = false;
  for (const d of days) {
    const p = byDay.get(d);
    if (p?.total == null) continue;
    hasCounts = true;
    up += p.up ?? 0;
    total += p.total;
  }
  const headline = hasCounts ? (total ? (up * 100) / total : null) : avgUptime;
  const labels = days.map((d) =>
    new Date(`${d}T00:00:00`).toLocaleDateString(undefined, { day: "numeric", month: "short" })
  );

  return (
    <Card className="lg:col-span-3">
      <CardContent>
        <ChartCardHeader
          title="Uptime"
          subtitle={`Across all monitors · ${rangeCaption(win)} · gaps mean no checks ran`}
          value={headline ?? 0}
          suffix="%"
          decimals={2}
          caption={
            monitorsDown > 0
              ? `${monitorsDown} monitor${monitorsDown === 1 ? "" : "s"} down`
              : "All monitors up"
          }
          captionTone={monitorsDown > 0 ? "critical" : "good"}
          href="/monitors"
        />
        <ActivityAreaChart
          labels={labels}
          series={[{ label: "Uptime", data: series, unit: "percent" }]}
          height={150}
        />
      </CardContent>
    </Card>
  );
}
