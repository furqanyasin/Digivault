import Link from "next/link";
import {
  Globe, AlertTriangle, Clock, Plus, ExternalLink, Activity, TrendingUp,
  Bell, CalendarClock, ShieldCheck, KeyRound, ShieldAlert,
} from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { getAccessToken } from "@/lib/server-token";
import { api } from "@/lib/api";
import type { Website, ScriptChange, Monitor, DetectedForm, FormSubmissionError } from "@/lib/api";
import { fmtDate, fmtDateTime, fmtRelative } from "@/lib/utils";

interface LogEntry {
  id: string;
  actor_email: string | null;
  actor_name: string;
  action: string;
  action_label: string;
  description: string;
  created_at: string;
}

interface RenewalRow {
  id: string;
  name: string;
  domain: string;
  days_until_expiry: number | null;
}

async function getData(token: string) {
  // Everything in one parallel batch. Changes/forms/form-errors used to be
  // fetched per site in a SECOND wave that had to wait on the websites list —
  // a 15-request waterfall before first paint. Team-wide endpoints make them
  // 3 requests that start immediately.
  const [
    websitesResult, monitorsResult, logsResult,
    sslResult, domainResult, hostingResult,
    changesResult, formsResult, formErrorsResult,
  ] = await Promise.allSettled([
    api.getAll<Website>("/api/v1/websites/", token),
    api.get<Monitor[]>("/api/v1/monitors/", token),
    api.get<LogEntry[]>("/api/v1/logs/", token),
    api.get<RenewalRow[]>("/api/v1/websites/expiring-ssl/?days=30", token),
    api.get<RenewalRow[]>("/api/v1/websites/expiring-domains/?days=30", token),
    api.get<RenewalRow[]>("/api/v1/websites/expiring-hosting/?days=30", token),
    api.getAll<ScriptChange>("/api/v1/changes/?unacknowledged=true", token),
    api.get<DetectedForm[]>("/api/v1/forms/", token),
    api.get<FormSubmissionError[]>("/api/v1/form-errors/", token),
  ]);

  const websites = websitesResult.status === "fulfilled" ? websitesResult.value : [];
  const monitors = monitorsResult.status === "fulfilled" ? monitorsResult.value : [];
  const recentActivity = logsResult.status === "fulfilled" ? logsResult.value.slice(0, 5) : [];
  const expiringSsl = sslResult.status === "fulfilled" ? sslResult.value : [];
  const expiringDomains = domainResult.status === "fulfilled" ? domainResult.value : [];
  const expiringHosting = hostingResult.status === "fulfilled" ? hostingResult.value : [];
  const allChanges = changesResult.status === "fulfilled" ? changesResult.value : [];
  const detectedForms = formsResult.status === "fulfilled" ? formsResult.value : [];
  const formErrors = formErrorsResult.status === "fulfilled" ? formErrorsResult.value : [];

  const weekAgo = Date.now() - 7 * 24 * 60 * 60 * 1000;
  const newThisWeek = websites.filter((w) => new Date(w.created_at).getTime() >= weekAgo).length;

  return {
    websites, allChanges, monitors, recentActivity,
    expiringSsl, expiringDomains, expiringHosting,
    detectedForms, formErrors, newThisWeek,
  };
}

// Two full rows on the lg 3-column grid. The rest live on /websites, which has
// search and filtering — a 60-card wall on the dashboard is unusable.
const DASHBOARD_SITE_LIMIT = 6;

const STATUS_DOT: Record<string, string> = {
  active: "bg-emerald-500",
  warning: "bg-amber-500",
  critical: "bg-red-500",
  inactive: "bg-slate-400",
};

const STATUS_BAR: Record<string, string> = {
  active: "bg-emerald-500",
  warning: "bg-amber-400",
  critical: "bg-red-500",
  inactive: "bg-slate-300",
};

const ACTIVITY_STYLE: Record<string, { icon: typeof Activity; className: string }> = {
  "auth.login": { icon: Activity, className: "bg-emerald-500/10 text-emerald-600" },
  "auth.login_failed": { icon: ShieldAlert, className: "bg-red-500/10 text-red-600" },
  "auth.2fa_enabled": { icon: ShieldCheck, className: "bg-emerald-500/10 text-emerald-600" },
  "auth.2fa_disabled": { icon: ShieldAlert, className: "bg-red-500/10 text-red-600" },
  "credential.revealed": { icon: KeyRound, className: "bg-amber-500/10 text-amber-600" },
  "credential.deleted": { icon: KeyRound, className: "bg-red-500/10 text-red-600" },
  "website.scan_triggered": { icon: Globe, className: "bg-violet-500/10 text-violet-600" },
  "website.snippet_verified": { icon: ShieldCheck, className: "bg-emerald-500/10 text-emerald-600" },
  "team.member_removed": { icon: ShieldAlert, className: "bg-red-500/10 text-red-600" },
  "team.member_role_changed": { icon: Activity, className: "bg-sky-500/10 text-sky-600" },
};
function activityStyle(action: string) {
  return ACTIVITY_STYLE[action] ?? { icon: Activity, className: "bg-slate-500/10 text-slate-600" };
}

export default async function DashboardPage() {
  const token = await getAccessToken();
  const {
    websites, allChanges, monitors, recentActivity,
    expiringSsl, expiringDomains, expiringHosting,
    detectedForms, formErrors, newThisWeek,
  } = await getData(token ?? "");

  const INTERNAL_DOMAINS = ["digilaticsvps", "digivault.digilatics.co", "cdn.digivault.digilatics.co"];
  function isInternal(c: ScriptChange) {
    const check = (s?: string) => s && INTERNAL_DOMAINS.some((d) => s.includes(d));
    return check(c.script?.src_url) || check(c.description);
  }
  const visibleChanges = allChanges.filter((c) => !isInternal(c));
  const pending = visibleChanges.filter((c) => !c.is_acknowledged);
  const highRisk = visibleChanges.filter(
    (c) => (c.severity === "critical" || c.severity === "high") && !c.is_acknowledged
  );
  const newScripts = visibleChanges.filter((c) => c.change_type === "added");
  const monitorsDown = monitors.filter((m) => m.status === "down" || m.status === "degraded").length;

  const uptimeSamples = monitors.map((m) => m.uptime_30d).filter((v): v is number => v != null);
  const avgUptime = uptimeSamples.length
    ? uptimeSamples.reduce((sum, v) => sum + v, 0) / uptimeSamples.length
    : null;

  const renewalIds = new Set([
    ...expiringSsl.map((r) => r.id),
    ...expiringDomains.map((r) => r.id),
    ...expiringHosting.map((r) => r.id),
  ]);
  const nextRenewalDays = [...expiringSsl, ...expiringDomains, ...expiringHosting]
    .map((r) => r.days_until_expiry)
    .filter((v): v is number => v != null)
    .sort((a, b) => a - b)[0];

  const totalScripts = websites.reduce((sum, w) => sum + (w.script_count ?? 0), 0);
  const sslValid = Math.max(websites.length - expiringSsl.length, 0);

  const stats = [
    {
      label: "Websites monitored", value: websites.length, icon: Globe,
      caption: newThisWeek > 0 ? `+${newThisWeek} this week` : "No new sites this week",
      href: "/websites",
    },
    {
      label: "Active alerts", value: pending.length, icon: Bell,
      caption: highRisk.length > 0 ? `${highRisk.length} critical` : "None critical",
      href: "/alerts",
    },
    {
      label: "Upcoming renewals", value: renewalIds.size, icon: CalendarClock,
      caption: nextRenewalDays != null ? `Next in ${nextRenewalDays} days` : "Nothing due soon",
      href: "/renewals",
    },
    {
      label: "Avg uptime (30d)", value: avgUptime != null ? `${avgUptime.toFixed(2)}%` : "—", icon: TrendingUp,
      caption: monitorsDown > 0 ? `${monitorsDown} monitor${monitorsDown === 1 ? "" : "s"} down` : "All monitors up",
      href: "/monitors",
    },
  ];

  return (
    <div className="p-8 space-y-8">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Dashboard</h1>
        <p className="text-muted-foreground mt-1">A live snapshot of every website your team is watching.</p>
      </div>

      {/* Stats */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        {stats.map(({ label, value, icon: Icon, caption, href }) => (
          <Link key={label} href={href}>
            <Card className="hover:border-primary/50 hover:shadow-md transition-all cursor-pointer">
              <CardContent className="p-5">
                <div className="flex items-center justify-between text-muted-foreground">
                  <span className="text-sm">{label}</span>
                  <Icon className="h-4 w-4" />
                </div>
                <div className="text-2xl font-bold mt-2">{value}</div>
                <div className="text-xs text-muted-foreground mt-1">{caption}</div>
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>

      {/* Recent activity + fleet health */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardContent className="p-6">
            <h2 className="text-base font-semibold mb-4">Recent activity</h2>
            {recentActivity.length === 0 ? (
              <p className="text-sm text-muted-foreground py-6 text-center">No recent activity.</p>
            ) : (
              <div className="divide-y">
                {recentActivity.map((entry) => {
                  const { icon: Icon, className } = activityStyle(entry.action);
                  return (
                    <div key={entry.id} className="flex items-start gap-3 py-3 first:pt-0 last:pb-0">
                      <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full ${className}`}>
                        <Icon className="h-3.5 w-3.5" />
                      </span>
                      <div className="min-w-0">
                        <p className="text-sm leading-snug">
                          <span className="font-semibold">{entry.actor_name || entry.actor_email || "System"}</span>{" "}
                          <span className="text-muted-foreground">{entry.description || entry.action_label}</span>
                        </p>
                        <p className="text-xs text-muted-foreground mt-0.5" title={fmtDateTime(entry.created_at)}>
                          {fmtRelative(entry.created_at)}
                        </p>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-6 space-y-1">
            <h2 className="text-base font-semibold mb-3">Fleet health</h2>

            <div className="flex items-center justify-between py-2.5 border-b">
              <div>
                <p className="text-sm font-medium">Uptime</p>
                <p className="text-xs text-muted-foreground">
                  {avgUptime != null ? `${avgUptime.toFixed(2)}%` : "No monitors yet"}
                </p>
              </div>
              <Badge variant={monitorsDown > 0 ? "destructive" : "default"}>
                {monitorsDown > 0 ? `${monitorsDown} down` : "Operational"}
              </Badge>
            </div>

            <div className="flex items-center justify-between py-2.5 border-b">
              <div>
                <p className="text-sm font-medium">SSL certificates</p>
                <p className="text-xs text-muted-foreground">{sslValid} / {websites.length} valid</p>
              </div>
              <Badge variant={expiringSsl.length > 0 ? "warning" : "default"}>
                {expiringSsl.length > 0 ? `${expiringSsl.length} expiring` : "All valid"}
              </Badge>
            </div>

            <div className="flex items-center justify-between py-2.5 border-b">
              <div>
                <p className="text-sm font-medium">Third-party scripts</p>
                <p className="text-xs text-muted-foreground">{totalScripts} tracked</p>
              </div>
              <Badge variant="secondary">
                {newScripts.length > 0 ? `${newScripts.length} new` : "No new activity"}
              </Badge>
            </div>

            <div className="flex items-center justify-between py-2.5">
              <div>
                <p className="text-sm font-medium">Forms</p>
                <p className="text-xs text-muted-foreground">{detectedForms.length} monitored</p>
              </div>
              <Badge variant={formErrors.length > 0 ? "destructive" : "default"}>
                {formErrors.length > 0 ? `${formErrors.length} broken` : "All healthy"}
              </Badge>
            </div>

            <Link href="/renewals" className="block pt-3">
              <Button variant="outline" className="w-full">
                <ShieldCheck className="h-4 w-4 mr-2" />
                Run fleet audit
              </Button>
            </Link>
          </CardContent>
        </Card>
      </div>

      {/* Website cards grid */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-lg font-semibold">Your Sites</h2>
          <Link href="/websites">
            <Button variant="outline" size="sm">
              {websites.length > DASHBOARD_SITE_LIMIT ? `View all ${websites.length}` : "View all"}
            </Button>
          </Link>
        </div>

        {websites.length === 0 ? (
          <Card>
            <CardContent className="flex flex-col items-center justify-center py-16 gap-3 text-center">
              <Globe className="h-10 w-10 text-muted-foreground" />
              <p className="text-lg font-medium">No websites yet</p>
              <p className="text-muted-foreground text-sm">Add your first website to start monitoring scripts</p>
              <Link href="/websites/new">
                <Button variant="outline" className="mt-2">
                  <Plus className="h-4 w-4 mr-2" />
                  Add website
                </Button>
              </Link>
            </CardContent>
          </Card>
        ) : (
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {websites.slice(0, DASHBOARD_SITE_LIMIT).map((site) => {
              return (
                <Card key={site.id} className="hover:border-primary/50 hover:shadow-md transition-all">
                  <CardContent className="p-5 space-y-3">
                    <div className="flex items-start justify-between">
                      <div className="flex items-center gap-2 min-w-0">
                        <span className={`h-2.5 w-2.5 rounded-full shrink-0 ${STATUS_DOT[site.status] ?? "bg-slate-400"}`} />
                        <div className="min-w-0">
                          <p className="font-semibold text-sm truncate">{site.name || site.domain}</p>
                          <p className="text-xs text-muted-foreground font-mono truncate">{site.domain}</p>
                        </div>
                      </div>
                      <Link href={`/websites/${site.id}`}>
                        <Button variant="ghost" size="sm" className="shrink-0 ml-2 h-7 w-7 p-0">
                          <ExternalLink className="h-3.5 w-3.5" />
                        </Button>
                      </Link>
                    </div>

                    {/* Health score */}
                    <div className="space-y-1">
                      <div className="flex items-center justify-between text-xs text-muted-foreground">
                        <span>Health</span>
                        <div className="flex items-center gap-2">
                          <span className={`font-bold text-sm ${
                            site.status === "critical" ? "text-red-500" :
                            site.status === "warning" ? "text-amber-500" :
                            site.status === "active" ? "text-emerald-600" :
                            "text-muted-foreground"
                          }`}>
                            {site.health_score ?? 100}
                          </span>
                          <Badge
                            variant={
                              site.status === "critical" ? "destructive" :
                              site.status === "warning" ? "warning" :
                              site.status === "active" ? "success" : "secondary"
                            }
                            className="text-xs h-5"
                          >
                            {site.status ?? "unknown"}
                          </Badge>
                        </div>
                      </div>
                      <div className="h-1.5 rounded-full bg-muted overflow-hidden">
                        <div
                          className={`h-full rounded-full transition-all ${STATUS_BAR[site.status ?? "inactive"] ?? "bg-slate-300"}`}
                          style={{ width: `${site.health_score ?? 100}%` }}
                        />
                      </div>
                    </div>

                    <div className="flex items-center gap-3 text-xs text-muted-foreground">
                      <span className="flex items-center gap-1">
                        <Globe className="h-3 w-3" />
                        {site.script_count ?? 0} scripts
                      </span>
                      {(site.unknown_script_count ?? 0) > 0 && (
                        <span className="flex items-center gap-1 text-red-600 font-semibold">
                          <AlertTriangle className="h-3 w-3" />
                          {site.unknown_script_count} unknown
                        </span>
                      )}
                      {site.last_seen_at && (
                        <span className="ml-auto flex items-center gap-1" title={fmtDateTime(site.last_seen_at)}>
                          <Clock className="h-3 w-3" />
                          {fmtDate(site.last_seen_at)}
                        </span>
                      )}
                    </div>
                  </CardContent>
                </Card>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
