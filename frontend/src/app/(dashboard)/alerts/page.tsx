import { getAccessToken } from "@/lib/server-token";
import { api } from "@/lib/api";
import type { Notification, AlertRule, Website, ScriptChange } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { CheckCircle, AlertTriangle } from "lucide-react";
import { AcknowledgeButton } from "@/components/acknowledge-button";
import { CreateAlertRuleDialog } from "@/components/create-alert-rule-dialog";
import { fmtDate, fmtDateTime } from "@/lib/utils";

async function getData(token: string) {
  const [notificationsResult, rulesResult, websitesResult] = await Promise.allSettled([
    api.get<Notification[]>("/api/v1/notifications/", token),
    api.get<AlertRule[]>("/api/v1/alert-rules/", token),
    api.get<Website[]>("/api/v1/websites/", token),
  ]);

  const websites = websitesResult.status === "fulfilled" ? websitesResult.value : [];

  // Fetch changes across all websites for the global alerts view
  const changeSets = await Promise.allSettled(
    websites.map((s) => api.get<ScriptChange[]>(`/api/v1/websites/${s.id}/changes/`, token))
  );
  const allChanges = changeSets
    .filter((r) => r.status === "fulfilled")
    .flatMap((r) => (r as PromiseFulfilledResult<ScriptChange[]>).value);

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

  const pendingChanges = allChanges.filter((c) => !c.is_acknowledged);
  const highCount = pendingChanges.filter((c) => c.severity === "high" || c.severity === "critical").length;
  const medCount = pendingChanges.filter((c) => c.severity === "medium").length;

  // Build website lookup for change attribution
  const websiteMap = Object.fromEntries(websites.map((w) => [w.id, w]));

  return (
    <div className="p-8 space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Alerts</h1>
          <p className="text-muted-foreground mt-1">Unacknowledged changes and notification history</p>
        </div>
      </div>

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
              <p className="text-xl font-bold">{allChanges.length - pendingChanges.length}</p>
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

      {/* Alert Rules */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>Alert Rules ({rules.length})</CardTitle>
          <CreateAlertRuleDialog />
        </CardHeader>
        <CardContent className="p-0">
          {rules.length === 0 ? (
            <div className="p-8 text-center space-y-2">
              <p className="font-medium">No alert rules configured</p>
              <p className="text-sm text-muted-foreground">Create a rule to receive notifications via email, Slack, or in-app.</p>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Channel</TableHead>
                  <TableHead>Min risk score</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rules.map((rule) => (
                  <TableRow key={rule.id}>
                    <TableCell className="font-medium">{rule.name}</TableCell>
                    <TableCell className="capitalize">{rule.channel}</TableCell>
                    <TableCell>{rule.min_risk_score}</TableCell>
                    <TableCell>
                      <Badge variant={rule.is_active ? "success" : "secondary"}>
                        {rule.is_active ? "Active" : "Paused"}
                      </Badge>
                    </TableCell>
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
