"use client";

import type { MonitorCheck } from "@/lib/api";

interface Props {
  checks: MonitorCheck[];
  days?: number;
}

type DayStatus = "up" | "degraded" | "down" | "no-data";

const STATUS_COLOR: Record<DayStatus, string> = {
  up: "bg-emerald-500",
  degraded: "bg-amber-400",
  down: "bg-red-500",
  "no-data": "bg-muted",
};

const STATUS_LABEL: Record<DayStatus, string> = {
  up: "Operational",
  degraded: "Degraded",
  down: "Outage",
  "no-data": "No data",
};

function toDateKey(iso: string) {
  return iso.slice(0, 10);
}

function computeBuckets(checks: MonitorCheck[], days: number): Array<{ date: string; status: DayStatus }> {
  const byDay: Record<string, MonitorCheck[]> = {};
  for (const c of checks) {
    if (!c.checked_at) continue;
    const key = toDateKey(c.checked_at);
    if (!byDay[key]) byDay[key] = [];
    byDay[key].push(c);
  }

  const buckets: Array<{ date: string; status: DayStatus }> = [];
  const now = new Date();
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(now);
    d.setDate(d.getDate() - i);
    const key = d.toISOString().slice(0, 10);
    const dayChecks = byDay[key];
    let status: DayStatus = "no-data";
    if (dayChecks && dayChecks.length > 0) {
      if (dayChecks.some((c) => c.status === "down")) status = "down";
      else if (dayChecks.some((c) => c.status === "degraded")) status = "degraded";
      else status = "up";
    }
    buckets.push({ date: key, status });
  }
  return buckets;
}

export function UptimeHeatmap({ checks, days = 90 }: Props) {
  const buckets = computeBuckets(checks, days);
  const weeks: Array<typeof buckets> = [];
  for (let i = 0; i < buckets.length; i += 7) {
    weeks.push(buckets.slice(i, i + 7));
  }

  return (
    <div className="space-y-3">
      <div className="flex gap-0.5 overflow-x-auto pb-1">
        {weeks.map((week, wi) => (
          <div key={wi} className="flex flex-col gap-0.5">
            {week.map((day, di) => (
              <div
                key={di}
                title={`${day.date}: ${STATUS_LABEL[day.status]}`}
                className={`w-3 h-3 rounded-sm ${STATUS_COLOR[day.status]} transition-opacity hover:opacity-80`}
              />
            ))}
          </div>
        ))}
      </div>
      <div className="flex items-center gap-3 text-xs text-muted-foreground">
        {(["up", "degraded", "down", "no-data"] as DayStatus[]).map((s) => (
          <span key={s} className="flex items-center gap-1">
            <span className={`inline-block w-2.5 h-2.5 rounded-sm ${STATUS_COLOR[s]}`} />
            {STATUS_LABEL[s]}
          </span>
        ))}
        <span className="ml-auto">{days}-day history</span>
      </div>
    </div>
  );
}
