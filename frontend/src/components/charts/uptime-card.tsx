"use client";

import { Card, CardContent } from "@/components/ui/card";
import { ChartCardHeader } from "./chart-card-header";
import { ActivityAreaChart } from "./activity-area-chart";
import {
  rangeCaption, useDashboardWindow, windowDays,
} from "@/lib/dashboard-window";

interface Props {
  /** The widest window (90 days), fetched once. Sliced here per selection. */
  points: { date: string; value: number | null }[];
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
  const byDay = new Map(points.map((p) => [p.date, p.value]));
  const series = days.map((d) => byDay.get(d) ?? null);
  const labels = days.map((d) =>
    new Date(`${d}T00:00:00`).toLocaleDateString(undefined, { day: "numeric", month: "short" })
  );

  return (
    <Card className="lg:col-span-3">
      <CardContent>
        <ChartCardHeader
          title="Uptime"
          subtitle={`Across all monitors · ${rangeCaption(win)} · gaps mean no checks ran`}
          value={avgUptime ?? 0}
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
