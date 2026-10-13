import Link from "next/link";
import { Activity, Plus, ArrowUp, ArrowDown, Minus, Pause, Circle, Bell, ShieldAlert } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { getAccessToken } from "@/lib/server-token";
import { api } from "@/lib/api";
import type { Monitor } from "@/lib/api";
import { MonitorActions } from "@/components/monitor-actions";
import { MonitorSparkline } from "@/components/monitor-sparkline";
import { BlockedSitesPanel, type BlockedGroup } from "@/components/blocked-sites-panel";
import { checkedVia } from "@/lib/checked-via";

function statusIcon(status: Monitor["status"]) {
  switch (status) {
    case "up": return <ArrowUp className="h-4 w-4 text-emerald-500" />;
    case "down": return <ArrowDown className="h-4 w-4 text-red-500" />;
    case "degraded": return <Minus className="h-4 w-4 text-amber-500" />;
    case "blocked": return <ShieldAlert className="h-4 w-4 text-slate-500" />;
    case "paused": return <Pause className="h-4 w-4 text-slate-400" />;
    default: return <Circle className="h-4 w-4 text-slate-400" />;
  }
}

function statusBadgeVariant(status: Monitor["status"]) {
  switch (status) {
    case "up": return "success";
    case "down": return "destructive";
    case "degraded": return "warning";
    // Deliberately not destructive: the site is fine, our view of it is not.
    case "blocked": return "secondary";
    default: return "secondary";
  }
}

function uptimeColor(pct: number | null) {
  if (pct === null) return "text-muted-foreground";
  if (pct >= 99) return "text-emerald-600";
  if (pct >= 95) return "text-amber-500";
  return "text-red-500";
}

function fmt(ms: number | null) {
  if (ms === null) return "—";
  if (ms >= 1000) return `${(ms / 1000).toFixed(2)}s`;
  return `${Math.round(ms)}ms`;
}

export default async function MonitorsPage() {
  const token = await getAccessToken();
  // getAll, not get: /api/v1/monitors/ pages at 25 (StandardPagination), so a
  // plain get silently truncated the table and every summary count once a team
  // passed 25 monitors.
  const [monitors, blockedSummary] = await Promise.all([
    api.getAll<Monitor>("/api/v1/monitors/", token ?? "").catch(() => [] as Monitor[]),
    // Falls back to nothing on an older backend; the panel then stays hidden.
    api.get<{ egress_ips: string[]; second_opinion_enabled?: boolean; groups: BlockedGroup[] }>(
      "/api/v1/monitors/blocked-summary/", token ?? "",
    )
      .catch(() => null),
  ]);

  const up = monitors.filter((m) => m.status === "up").length;
  const down = monitors.filter((m) => m.status === "down").length;
  const degraded = monitors.filter((m) => m.status === "degraded").length;
  const blocked = monitors.filter((m) => m.status === "blocked").length;

  return (
    <div className="p-8 space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Uptime Monitors</h1>
          <p className="text-muted-foreground mt-1">Track availability and response times for your services</p>
        </div>
        <div className="flex items-center gap-2">
          <Link href="/monitors/channels">
            <Button variant="outline">
              <Bell className="h-4 w-4 mr-2" />
              Channels
            </Button>
          </Link>
          <Link href="/monitors/new">
            <Button>
              <Plus className="h-4 w-4 mr-2" />
              Add monitor
            </Button>
          </Link>
        </div>
      </div>

      {/* Summary row */}
      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="text-sm font-medium text-muted-foreground">Total Monitors</CardTitle>
            <Activity className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent><div className="text-2xl font-bold">{monitors.length}</div></CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="text-sm font-medium text-muted-foreground">Up</CardTitle>
            <ArrowUp className="h-4 w-4 text-emerald-500" />
          </CardHeader>
          <CardContent><div className="text-2xl font-bold text-emerald-600">{up}</div></CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="text-sm font-medium text-muted-foreground">Issues</CardTitle>
            <ArrowDown className="h-4 w-4 text-red-500" />
          </CardHeader>
          <CardContent><div className="text-2xl font-bold text-red-600">{down + degraded}</div></CardContent>
        </Card>
        {/* Deliberately its own tile rather than folded into Issues: these sites
            are serving visitors fine, we just cannot see them. Counting them as
            issues is the false-alarm we set out to remove; hiding them entirely
            would leave the coverage gap invisible. */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="text-sm font-medium text-muted-foreground">Blocked</CardTitle>
            <ShieldAlert className="h-4 w-4 text-slate-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-slate-600">{blocked}</div>
            {blocked > 0 && (
              <p className="text-xs text-muted-foreground mt-1">
                Serving visitors, but a firewall blocks our checks.{" "}
                <a href="/bot" className="underline">How to allowlist us</a>
              </p>
            )}
          </CardContent>
        </Card>
      </div>

      <BlockedSitesPanel
        groups={blockedSummary?.groups ?? []}
        egressIps={blockedSummary?.egress_ips ?? []}
        secondOpinionEnabled={blockedSummary?.second_opinion_enabled}
      />

      {/* Monitor table */}
      {monitors.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center gap-3 text-center py-16">
            <Activity className="h-10 w-10 text-muted-foreground" />
            <p className="text-lg font-medium">No monitors yet</p>
            <p className="text-muted-foreground text-sm">Add a monitor to start tracking uptime and response times</p>
            <Link href="/monitors/new">
              <Button variant="outline" className="mt-2">
                <Plus className="h-4 w-4 mr-2" />
                Add monitor
              </Button>
            </Link>
          </CardContent>
        </Card>
      ) : (
        <Card>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b bg-muted/30">
                  <th className="px-4 py-3 text-left font-medium text-muted-foreground">Status</th>
                  <th className="px-4 py-3 text-left font-medium text-muted-foreground">Name</th>
                  <th className="px-4 py-3 text-left font-medium text-muted-foreground">URL / Target</th>
                  <th className="px-4 py-3 text-left font-medium text-muted-foreground">Type</th>
                  <th className="px-4 py-3 text-right font-medium text-muted-foreground">Response</th>
                  <th className="px-4 py-3 text-right font-medium text-muted-foreground">Uptime 24h</th>
                  <th className="px-4 py-3 text-right font-medium text-muted-foreground">Uptime 7d</th>
                  <th className="px-4 py-3 text-left font-medium text-muted-foreground">Last 20</th>
                  <th className="px-4 py-3 text-right font-medium text-muted-foreground">Interval</th>
                  <th className="px-4 py-3 text-right font-medium text-muted-foreground">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {monitors.map((m) => (
                  <tr key={m.id} className="hover:bg-muted/20 transition-colors">
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-1.5">
                        {statusIcon(m.status)}
                        <Badge variant={statusBadgeVariant(m.status) as never} className="capitalize text-xs">
                          {m.status}
                          {checkedVia(m.last_checked_via) ? ` · via ${checkedVia(m.last_checked_via)!.short}` : ""}
                        </Badge>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <Link href={`/monitors/${m.id}`} className="font-medium hover:underline">
                        {m.name}
                      </Link>
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-muted-foreground max-w-xs truncate">
                      {m.url}
                    </td>
                    <td className="px-4 py-3">
                      <Badge variant="outline" className="uppercase text-xs">{m.monitor_type}</Badge>
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-xs">
                      {fmt(m.last_response_time)}
                    </td>
                    <td className={`px-4 py-3 text-right font-mono text-xs font-semibold ${uptimeColor(m.uptime_24h)}`}>
                      {m.uptime_24h !== null ? `${m.uptime_24h.toFixed(2)}%` : "—"}
                    </td>
                    <td className={`px-4 py-3 text-right font-mono text-xs font-semibold ${uptimeColor(m.uptime_7d)}`}>
                      {m.uptime_7d !== null ? `${m.uptime_7d.toFixed(2)}%` : "—"}
                    </td>
                    <td className="px-4 py-3">
                      <MonitorSparkline statuses={m.recent_statuses ?? []} />
                    </td>
                    <td className="px-4 py-3 text-right text-xs text-muted-foreground">
                      {m.check_interval}s
                    </td>
                    <td className="px-4 py-3 text-right">
                      <MonitorActions monitor={m} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}
