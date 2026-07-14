"use client";

import { useState } from "react";
import { AlertTriangle } from "lucide-react";
import type { PublicIncident, UptimeBar } from "@/lib/api";

function barColor(status: UptimeBar["status"]) {
  switch (status) {
    case "up": return "bg-emerald-500";
    case "down": return "bg-red-500";
    case "degraded": return "bg-amber-400";
    default: return "bg-slate-300";
  }
}

function fmtDuration(mins: number): string {
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return `${h} hr${h === 1 ? "" : "s"}  ${m} min${m === 1 ? "" : "s"}`;
}

function fmtDay(iso: string): string {
  const d = new Date(`${iso}T00:00:00`);
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

export function UptimeBarStrip({
  bars,
  incidents,
}: {
  bars: UptimeBar[];
  incidents: PublicIncident[];
}) {
  const [hover, setHover] = useState<number | null>(null);

  // Index incidents by their calendar day so a hovered bar can list the day's
  // related incidents (matched by date — our incidents are page-level).
  const byDay = new Map<string, PublicIncident[]>();
  for (const inc of incidents) {
    const key = new Date(inc.created_at).toISOString().slice(0, 10);
    const list = byDay.get(key) ?? [];
    list.push(inc);
    byDay.set(key, list);
  }

  const active = hover === null ? null : bars[hover];
  const related = active ? byDay.get(active.date) ?? [] : [];
  // Position the popover over the hovered bar, clamped so it never overflows.
  const leftPct = hover === null ? 0 : ((hover + 0.5) / bars.length) * 100;
  const clampedLeft = Math.min(88, Math.max(12, leftPct));

  const hasDowntime = active ? active.down_minutes > 0 : false;
  const hasDegraded = active ? active.degraded_minutes > 0 : false;

  return (
    <div className="relative">
      <div className="flex items-end gap-px h-8">
        {bars.map((bar, i) => (
          <div
            key={bar.date}
            onMouseEnter={() => setHover(i)}
            onMouseLeave={() => setHover((cur) => (cur === i ? null : cur))}
            className={`flex-1 rounded-sm h-full cursor-default ${barColor(bar.status)} ${
              hover === i ? "opacity-100 ring-1 ring-slate-400" : "opacity-80"
            } transition-opacity`}
          />
        ))}
      </div>

      {active && (
        <div
          className="absolute z-20 top-9 -translate-x-1/2 w-64 rounded-lg border bg-popover text-popover-foreground shadow-lg p-3 text-sm"
          style={{ left: `${clampedLeft}%` }}
        >
          <p className="font-semibold text-foreground">{fmtDay(active.date)}</p>

          {hasDowntime ? (
            <div className="mt-2 flex items-center gap-2 rounded-md bg-amber-50 border border-amber-200 px-2.5 py-1.5">
              <AlertTriangle className="h-4 w-4 text-amber-500 shrink-0" />
              <span className="font-medium text-amber-800">Partial outage</span>
              <span className="ml-auto font-mono text-xs text-amber-700">
                {fmtDuration(active.down_minutes)}
              </span>
            </div>
          ) : hasDegraded ? (
            <div className="mt-2 flex items-center gap-2 rounded-md bg-amber-50 border border-amber-200 px-2.5 py-1.5">
              <AlertTriangle className="h-4 w-4 text-amber-500 shrink-0" />
              <span className="font-medium text-amber-800">Degraded</span>
              <span className="ml-auto font-mono text-xs text-amber-700">
                {fmtDuration(active.degraded_minutes)}
              </span>
            </div>
          ) : active.status === "no-data" ? (
            <p className="mt-1.5 text-muted-foreground">No data recorded on this day.</p>
          ) : (
            <p className="mt-1.5 text-muted-foreground">No downtime recorded on this day.</p>
          )}

          {related.length > 0 && (
            <div className="mt-2.5 border-t pt-2">
              <p className="text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">
                Related
              </p>
              <ul className="mt-1 space-y-0.5">
                {related.map((inc) => (
                  <li key={inc.id} className="text-sm text-blue-600 truncate">
                    {inc.title}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
