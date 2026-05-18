import Link from "next/link";
import { notFound } from "next/navigation";
import {
  ArrowUp, ArrowDown, Minus, Pause, Circle,
  Activity, CheckCircle2, XCircle, ChevronLeft,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { getAccessToken } from "@/lib/server-token";
import { api } from "@/lib/api";
import type { Monitor, MonitorCheck, MonitorNotificationRule, NotificationChannel } from "@/lib/api";
import { MonitorActions } from "@/components/monitor-actions";
import { MonitorNotificationPanel } from "@/components/monitor-notification-panel";
import { MonitorResponseChart } from "@/components/monitor-response-chart";
import { MonitorEditForm } from "@/components/monitor-edit-form";
import { UptimeHeatmap } from "@/components/uptime-heatmap";

type Props = { params: Promise<{ id: string }> };

function statusIcon(status: Monitor["status"] | MonitorCheck["status"]) {
  switch (status) {
    case "up": return <ArrowUp className="h-4 w-4 text-emerald-500" />;
    case "down": return <ArrowDown className="h-4 w-4 text-red-500" />;
    case "degraded": return <Minus className="h-4 w-4 text-amber-500" />;
    case "paused": return <Pause className="h-4 w-4 text-slate-400" />;
    default: return <Circle className="h-4 w-4 text-slate-400" />;
  }
}

function statusBadgeVariant(status: string) {
  switch (status) {
    case "up": return "success";
    case "down": return "destructive";
    case "degraded": return "warning";
    default: return "secondary";
  }
}

function fmt(ms: number | null) {
  if (ms === null) return "—";
  if (ms >= 1000) return `${(ms / 1000).toFixed(2)}s`;
  return `${Math.round(ms)}ms`;
}

function uptimeColor(pct: number | null) {
  if (pct === null) return "text-muted-foreground";
  if (pct >= 99) return "text-emerald-600";
  if (pct >= 95) return "text-amber-500";
  return "text-red-500";
}

function fmtDate(iso: string | null) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

export default async function MonitorDetailPage({ params }: Props) {
  const { id } = await params;
  const token = await getAccessToken();

  const [monitorResult, checksResult, rulesResult, channelsResult] = await Promise.allSettled([
    api.get<Monitor>(`/api/v1/monitors/${id}/`, token ?? ""),
    api.get<MonitorCheck[]>(`/api/v1/monitors/${id}/checks/`, token ?? ""),
    api.get<MonitorNotificationRule[]>(`/api/v1/monitors/${id}/notification-rules/`, token ?? ""),
    api.get<NotificationChannel[]>("/api/v1/notification-channels/", token ?? ""),
  ]);

  if (monitorResult.status === "rejected") notFound();
  const monitor = monitorResult.value;
  const checks = checksResult.status === "fulfilled" ? checksResult.value : [];
  const rules = rulesResult.status === "fulfilled" ? rulesResult.value : [];
  const channels = channelsResult.status === "fulfilled" ? channelsResult.value : [];

  const upCount = checks.filter((c) => c.status === "up").length;
  const downCount = checks.filter((c) => c.status === "down").length;
  const responseTimes = checks.filter((c) => c.response_time_ms !== null).map((c) => c.response_time_ms as number);
  const avgResponse = responseTimes.length
    ? Math.round(responseTimes.reduce((s, v) => s + v, 0) / responseTimes.length)
    : null;

  return (
    <div className="p-8 space-y-8">
      {/* Header */}
      <div className="space-y-1">
        <Link href="/monitors" className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors w-fit">
          <ChevronLeft className="h-4 w-4" />
          All monitors
        </Link>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            {statusIcon(monitor.status)}
            <h1 className="text-3xl font-bold tracking-tight">{monitor.name}</h1>
            <Badge variant={statusBadgeVariant(monitor.status) as never} className="capitalize">
              {monitor.status}
            </Badge>
          </div>
          <MonitorActions monitor={monitor} />
        </div>
        <p className="font-mono text-sm text-muted-foreground">{monitor.url}</p>
      </div>

      {/* Uptime stats */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Uptime 24h</CardTitle>
          </CardHeader>
          <CardContent>
            <div className={`text-2xl font-bold ${uptimeColor(monitor.uptime_24h)}`}>
              {monitor.uptime_24h !== null ? `${monitor.uptime_24h.toFixed(2)}%` : "—"}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Uptime 7d</CardTitle>
          </CardHeader>
          <CardContent>
            <div className={`text-2xl font-bold ${uptimeColor(monitor.uptime_7d)}`}>
              {monitor.uptime_7d !== null ? `${monitor.uptime_7d.toFixed(2)}%` : "—"}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Uptime 30d</CardTitle>
          </CardHeader>
          <CardContent>
            <div className={`text-2xl font-bold ${uptimeColor(monitor.uptime_30d)}`}>
              {monitor.uptime_30d !== null ? `${monitor.uptime_30d.toFixed(2)}%` : "—"}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Last response</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{fmt(monitor.last_response_time)}</div>
            <p className="text-xs text-muted-foreground mt-1">{fmtDate(monitor.last_checked_at)}</p>
          </CardContent>
        </Card>
      </div>

      {/* Response time chart */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base flex items-center gap-2">
            <Activity className="h-4 w-4" />
            Response time trend
            <span className="text-xs font-normal text-muted-foreground ml-1">last {Math.min(checks.length, 60)} checks</span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <MonitorResponseChart checks={checks} />
          {checks.length > 0 && (
            <div className="flex items-center gap-4 mt-3 text-xs text-muted-foreground">
              <span className="flex items-center gap-1"><span className="inline-block h-2 w-2 rounded-full bg-emerald-500" /> Up</span>
              <span className="flex items-center gap-1"><span className="inline-block h-2 w-2 rounded-full bg-amber-400" /> Degraded</span>
              <span className="flex items-center gap-1"><span className="inline-block h-2 w-2 rounded-full bg-red-500" /> Down</span>
              <span className="ml-auto">Avg: {fmt(avgResponse)}</span>
            </div>
          )}
        </CardContent>
      </Card>

      {/* 90-day uptime heatmap */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Daily uptime history</CardTitle>
        </CardHeader>
        <CardContent>
          <UptimeHeatmap checks={checks} days={90} />
        </CardContent>
      </Card>

      {/* Config edit + notification rules side by side */}
      <div className="grid gap-6 md:grid-cols-2">
        <MonitorEditForm monitor={monitor} />

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Check summary</CardTitle>
          </CardHeader>
          <CardContent>
            <dl className="space-y-3 text-sm">
              <div className="flex justify-between">
                <dt className="text-muted-foreground">Total checks</dt>
                <dd className="font-medium">{checks.length}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-muted-foreground flex items-center gap-1">
                  <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" /> Successful
                </dt>
                <dd className="font-medium text-emerald-600">{upCount}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-muted-foreground flex items-center gap-1">
                  <XCircle className="h-3.5 w-3.5 text-red-500" /> Failed
                </dt>
                <dd className="font-medium text-red-600">{downCount}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-muted-foreground">Success rate</dt>
                <dd className={`font-medium ${uptimeColor(checks.length ? Math.round((upCount / checks.length) * 10000) / 100 : null)}`}>
                  {checks.length ? `${((upCount / checks.length) * 100).toFixed(1)}%` : "—"}
                </dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-muted-foreground">Avg response</dt>
                <dd className="font-mono font-medium">{fmt(avgResponse)}</dd>
              </div>
            </dl>
          </CardContent>
        </Card>
      </div>

      {/* Notification rules */}
      <MonitorNotificationPanel
        monitorId={monitor.id}
        initialRules={rules}
        channels={channels}
      />

      {/* Check history table */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Check history</CardTitle>
        </CardHeader>
        {checks.length === 0 ? (
          <CardContent>
            <p className="text-sm text-muted-foreground text-center py-8">
              No checks recorded yet. Click ⚡ to run one now.
            </p>
          </CardContent>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b bg-muted/30">
                  <th className="px-4 py-3 text-left font-medium text-muted-foreground">Time</th>
                  <th className="px-4 py-3 text-left font-medium text-muted-foreground">Status</th>
                  <th className="px-4 py-3 text-right font-medium text-muted-foreground">Response</th>
                  <th className="px-4 py-3 text-right font-medium text-muted-foreground">Code</th>
                  <th className="px-4 py-3 text-left font-medium text-muted-foreground">Error</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {checks.map((c) => (
                  <tr key={c.id} className="hover:bg-muted/20 transition-colors">
                    <td className="px-4 py-2.5 text-xs text-muted-foreground font-mono whitespace-nowrap">
                      {fmtDate(c.checked_at)}
                    </td>
                    <td className="px-4 py-2.5">
                      <div className="flex items-center gap-1.5">
                        {statusIcon(c.status)}
                        <Badge variant={statusBadgeVariant(c.status) as never} className="capitalize text-xs">
                          {c.status}
                        </Badge>
                      </div>
                    </td>
                    <td className="px-4 py-2.5 text-right font-mono text-xs">{fmt(c.response_time_ms)}</td>
                    <td className="px-4 py-2.5 text-right font-mono text-xs">{c.status_code ?? "—"}</td>
                    <td className="px-4 py-2.5 text-xs text-muted-foreground max-w-xs truncate">{c.error_message || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
