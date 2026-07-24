import { getAccessToken } from "@/lib/server-token";
import { api } from "@/lib/api";
import type { Notification, AlertRule, Website, ScriptChange } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { CheckCircle, AlertTriangle } from "lucide-react";
import { AcknowledgeButton } from "@/components/acknowledge-button";
import { CreateAlertRuleDialog } from "@/components/create-alert-rule-dialog";
import { AlertRulesClient } from "@/components/alert-rules-client";
import { fmtDate, fmtDateTime } from "@/lib/utils";

// A change tagged with the website it belongs to (added during fetch).
type ChangeWithSite = ScriptChange & { _websiteName: string; _websiteId: string };

async function getData(token: string) {
  const [notificationsResult, rulesResult, websitesResult] = await Promise.allSettled([
    api.get<Notification[]>("/api/v1/notifications/", token),
    api.get<AlertRule[]>("/api/v1/alert-rules/", token),
    api.get<Website[]>("/api/v1/websites/", token),
  ]);

  const websites = websitesResult.status === "fulfilled" ? websitesResult.value : [];

  // Fetch changes across all websites for the global alerts view. Each change is
  // tagged with its source website so the table can show attribution (the
  // ScriptChange payload itself doesn't carry the website).
  const changeSets = await Promise.allSettled(
    websites.map((s) => api.get<ScriptChange[]>(`/api/v1/websites/${s.id}/changes/`, token))
  );
  const allChanges: ChangeWithSite[] = changeSets.flatMap((r, i) => {
    if (r.status !== "fulfilled") return [];
    const site = websites[i];
    return r.value.map((c) => ({
      ...c,
      _websiteName: site.name || site.domain,
      _websiteId: site.id,
    }));
  });

  return {
    notifications: notificationsResult.status === "fulfilled" ? notificationsResult.value : [],
    rules: rulesResult.status === "fulfilled" ? rulesResult.value : [],
    allChanges,
    websites,
  };
}

function severityVariant(s: string): "destructive" | "warning" | "secondary" {
  if (s === "high" || s === "critical") return "destructive";
  if (s === "medium") return "warning";
  return "secondary";
}

export default async function AlertsPage() {
  const token = await getAccessToken();
  const { notifications, rules, allChanges, websites } = await getData(token ?? "");

  const INTERNAL_DOMAINS = ["digilaticsvps", "digivault.digilatics.co", "cdn.digivault.digilatics.co"];
  function isInternal(c: ChangeWithSite) {
    const hit = (s?: string) => !!s && INTERNAL_DOMAINS.some((d) => s.includes(d));
    return hit(c.script?.src_url) || hit(c.description);
  }

  const visibleChanges = allChanges.filter((c) => !isInternal(c));
  const pendingChanges = visibleChanges.filter((c) => !c.is_acknowledged);
  const highCount = pendingChanges.filter((c) => c.severity === "high" || c.severity === "critical").length;
  const medCount = pendingChanges.filter((c) => c.severity === "medium").length;

  return (
    <div className="p-8 space-y-8">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Alerts</h1>
          <p className="text-muted-foreground mt-1">Alert rules and their delivery channels.</p>
        </div>
        <CreateAlertRuleDialog
          websites={websites.map((w) => ({ id: w.id, name: w.name, domain: w.domain }))}
        />
      </div>

      {/* Alert rules — filterable by channel and severity */}
      <AlertRulesClient rules={rules} />

      {/* Summary bar */}
      <div className="grid grid-cols-3 gap-4">
        <Card>
          <CardContent className="flex items-center gap-3 py-4">
            <AlertTriangle className="h-6 w-6 text-red-500 shrink-0" />
            <div>
              <p className="text-xl font-bold">{highCount}</p>
              <p className="text-xs text-muted-foreground">High severity</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="flex items-center gap-3 py-4">
            <AlertTriangle className="h-6 w-6 text-amber-500 shrink-0" />
            <div>
              <p className="text-xl font-bold">{medCount}</p>
              <p className="text-xs text-muted-foreground">Medium severity</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="flex items-center gap-3 py-4">
            <CheckCircle className="h-6 w-6 text-emerald-500 shrink-0" />
            <div>
              <p className="text-xl font-bold">{visibleChanges.length - pendingChanges.length}</p>
              <p className="text-xs text-muted-foreground">Acknowledged</p>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Unacknowledged changes */}
      <Card>
        <CardHeader>
          <CardTitle>Unacknowledged Changes ({pendingChanges.length})</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {pendingChanges.length === 0 ? (
            <div className="p-10 flex flex-col items-center gap-2 text-center">
              <CheckCircle className="h-10 w-10 text-emerald-500" />
              <p className="font-medium">All clear!</p>
              <p className="text-sm text-muted-foreground">No unacknowledged changes across any of your sites.</p>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Severity</TableHead>
                  <TableHead>Website</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Script</TableHead>
                  <TableHead>Description</TableHead>
                  <TableHead>Detected</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {pendingChanges
                  .sort((a, b) => {
                    const order: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };
                    return (order[a.severity] ?? 4) - (order[b.severity] ?? 4);
                  })
                  .map((change) => (
                    <TableRow key={change.id}>
                      <TableCell><Badge variant={severityVariant(change.severity)}>{change.severity}</Badge></TableCell>
                      <TableCell className="text-sm font-medium max-w-[160px] truncate">{change._websiteName}</TableCell>
                      <TableCell className="capitalize font-medium text-sm">{change.change_type}</TableCell>
                      <TableCell className="font-mono text-xs max-w-[180px] truncate">{change.script?.src_url ?? "—"}</TableCell>
                      <TableCell className="text-sm text-muted-foreground max-w-[200px] truncate">{change.description}</TableCell>
                      <TableCell className="text-sm text-muted-foreground">{fmtDate(change.created_at)}</TableCell>
                      <TableCell><AcknowledgeButton changeId={change.id} /></TableCell>
                    </TableRow>
                  ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Notification delivery history */}
      {notifications.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Notification History ({notifications.length})</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Channel</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Sent</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {notifications.slice(0, 20).map((n) => (
                  <TableRow key={n.id}>
                    <TableCell className="capitalize">{n.channel}</TableCell>
                    <TableCell>
                      <Badge variant={n.status === "sent" ? "success" : n.status === "failed" ? "destructive" : "secondary"}>
                        {n.status}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-muted-foreground text-sm">{fmtDateTime(n.created_at)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
