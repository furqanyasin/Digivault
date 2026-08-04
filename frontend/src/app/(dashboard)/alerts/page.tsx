import { getAccessToken } from "@/lib/server-token";
import { api } from "@/lib/api";
import type { Notification, AlertRule, Website, ScriptChange } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { AlertTriangle, Globe } from "lucide-react";
import { CreateAlertRuleDialog } from "@/components/create-alert-rule-dialog";
import { AlertRulesClient } from "@/components/alert-rules-client";
import { AlertsFeedClient, type FeedChange } from "@/components/alerts-feed-client";
import { AlertHistoryClient } from "@/components/alert-history-client";

// A change tagged with the website it belongs to (added during fetch).
type ChangeWithSite = ScriptChange & { _websiteName: string; _websiteId: string };

async function getData(token: string) {
  // One team-wide changes call. This used to be a request per website — 60+
  // sequential round trips on a real agency account, all before first paint.
  const [notificationsResult, rulesResult, websitesResult, changesResult] =
    await Promise.allSettled([
      api.get<Notification[]>("/api/v1/notifications/", token),
      api.get<AlertRule[]>("/api/v1/alert-rules/", token),
      api.getAll<Website>("/api/v1/websites/", token),
      api.getAll<ScriptChange>("/api/v1/changes/?unacknowledged=true", token),
    ]);

  const websites = websitesResult.status === "fulfilled" ? websitesResult.value : [];
  const changes = changesResult.status === "fulfilled" ? changesResult.value : [];

  const allChanges: ChangeWithSite[] = changes.map((c) => ({
    ...c,
    _websiteName: c.website_name || "",
    _websiteId: c.website || "",
  }));

  return {
    notifications: notificationsResult.status === "fulfilled" ? notificationsResult.value : [],
    rules: rulesResult.status === "fulfilled" ? rulesResult.value : [],
    allChanges,
    websites,
  };
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

  // Changes and notifications only carry a website, so the client name — what
  // the filters key on — is resolved from the websites list once, here.
  const clientByWebsite: Record<string, string> = Object.fromEntries(
    websites.map((w) => [w.id, w.client_name ?? ""])
  );
  const feedChanges: FeedChange[] = pendingChanges.map((c) => ({
    id: c.id,
    severity: c.severity,
    change_type: c.change_type,
    description: c.description,
    created_at: c.created_at,
    scriptUrl: c.script?.src_url ?? "",
    websiteId: c._websiteId,
    websiteName: c._websiteName,
    clientName: clientByWebsite[c._websiteId] ?? "",
  }));
  // We only fetch unacknowledged changes now, so an "Acknowledged" total would
  // always read 0. Distinct affected sites is both accurate and more useful.
  const affectedSites = new Set(pendingChanges.map((c) => c._websiteId)).size;

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
          <CardContent className="flex items-center gap-3">
            <AlertTriangle className="h-6 w-6 text-red-500 shrink-0" />
            <div>
              <p className="text-xl font-bold">{highCount}</p>
              <p className="text-xs text-muted-foreground">High severity</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="flex items-center gap-3">
            <AlertTriangle className="h-6 w-6 text-amber-500 shrink-0" />
            <div>
              <p className="text-xl font-bold">{medCount}</p>
              <p className="text-xs text-muted-foreground">Medium severity</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="flex items-center gap-3">
            <Globe className="h-6 w-6 text-violet-500 shrink-0" />
            <div>
              <p className="text-xl font-bold">{affectedSites}</p>
              <p className="text-xs text-muted-foreground">Sites affected</p>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Unacknowledged changes — searchable, filterable by client */}
      <AlertsFeedClient changes={feedChanges} />

      {/* Delivery history — every alert that actually went out */}
      <AlertHistoryClient notifications={notifications} clientByWebsite={clientByWebsite} />

    </div>
  );
}
