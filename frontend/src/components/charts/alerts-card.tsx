"use client";

import { Card, CardContent } from "@/components/ui/card";
import { AcknowledgeAllButton } from "@/components/acknowledge-all-button";
import { ChartCardHeader } from "./chart-card-header";
import { ActivityAreaChart } from "./activity-area-chart";
import { SeverityStrip, type SeverityCounts } from "./severity-strip";
import {
  dayKey, rangeCaption, useDashboardWindow, windowDays,
} from "@/lib/dashboard-window";

/** Only what the chart needs — not the whole ScriptChange. */
export interface AlertPoint {
  id: string;
  severity: string;
  created_at: string;
}

interface Props {
  alerts: AlertPoint[];
  severityCounts: SeverityCounts;
}

/** Open alerts: the total, the per-day shape over the selected window, and the
 *  severity mix.
 *
 *  Client-side so a preset click re-buckets in place instead of triggering a
 *  server navigation. The alerts themselves are window-independent — the totals
 *  and the mix always describe the whole open backlog; only the per-day series
 *  is scoped.
 */
export function AlertsCard({ alerts, severityCounts }: Props) {
  const win = useDashboardWindow();
  const days = windowDays(win);
  const perDay = days.map(
    (d) => alerts.filter((a) => dayKey(new Date(a.created_at)) === d).length
  );
  const labels = days.map((d) =>
    new Date(`${d}T00:00:00`).toLocaleDateString(undefined, { day: "numeric", month: "short" })
  );
  const highRisk = alerts.filter(
    (a) => a.severity === "critical" || a.severity === "high"
  ).length;

  return (
    <Card className="lg:col-span-3">
      <CardContent>
        <ChartCardHeader
          title="Open alerts"
          subtitle={`Raised per day · ${rangeCaption(win)}`}
          value={alerts.length}
          caption={highRisk > 0 ? `${highRisk} critical or high` : "None critical"}
          captionTone={highRisk > 0 ? "critical" : "good"}
          href="/alerts"
          action={
            <AcknowledgeAllButton
              changeIds={alerts.map((a) => a.id)}
              highRiskCount={highRisk}
            />
          }
        />
        <ActivityAreaChart
          labels={labels}
          series={[{ label: "Alerts raised", data: perDay, tone: "critical" }]}
          height={150}
        />
        {/* The severity breakdown used to be its own card, restating this card's
            total. As a strip it adds the mix without repeating it. */}
        <SeverityStrip counts={severityCounts} />
      </CardContent>
    </Card>
  );
}
