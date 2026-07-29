import Link from "next/link";
import {
  Globe, Plus, Activity, TrendingUp, Star, AlertTriangle,
  Bell, CalendarClock, ShieldCheck, KeyRound, ShieldAlert, ArrowRight,
} from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { SiteHealthCard } from "@/components/site-health-card";
import { getAccessToken } from "@/lib/server-token";
import { api } from "@/lib/api";
import type { Website, ScriptChange, Monitor, DetectedForm, FormSubmissionError } from "@/lib/api";
import { fmtDateTime, fmtRelative } from "@/lib/utils";

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

// One row each. These sections exist to name the few sites worth opening now;
// a longer list would just be the grid again.
const SPOTLIGHT_LIMIT = 3;

// Mirrors Website.HEALTH_WARNING_BELOW.
const ATTENTION_BELOW = 85;

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

  // Spotlight sections. Selected from the already-fetched list — no extra
  // request. Worst score first, so the three shown are the three worth opening.
  const byWorstScore = (a: Website, b: Website) =>
    (a.health_score ?? 100) - (b.health_score ?? 100);

  const vipSites = websites.filter((w) => w.is_vip).sort(byWorstScore);

  // Driven by `status`, not by the score alone. Status is the backend's
  // "how urgent is the worst open issue" verdict, so it catches sites with a
  // real problem that barely dents the number — two broken contact forms score
  // 88, which a `< 85` threshold would have quietly skipped. The score band is
  // kept as a floor for anything status hasn't classified.
  const needsAttention = websites
    .filter(
      (w) =>
        !w.is_vip &&
        w.status !== "inactive" &&
        (w.status === "critical" ||
          w.status === "warning" ||
          (w.health_score ?? 100) < ATTENTION_BELOW)
    )
    .sort(byWorstScore);

  const stats = [
    {
      label: "Websites monitored", value: websites.length, icon: Globe,
      caption: newThisWeek > 0 ? `+${newThisWeek} this week` : "No new sites this week",
      href: "/websites",
    },
    {
      label: "Active alerts", value: pending.length, icon: Bell,
      caption: highRisk.length > 0 ? `${highRisk.length} critical` : "None critical",
      // Critical alerts are the one caption that must not read as ambient text.
      captionClass: highRisk.length > 0 ? "text-red-600 font-semibold" : undefined,
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
        {stats.map(({ label, value, icon: Icon, caption, captionClass, href }) => (
          <Link key={label} href={href}>
            <Card className="hover:border-primary/50 hover:shadow-md transition-all cursor-pointer">
              <CardContent className="p-5">
                <div className="flex items-center justify-between text-muted-foreground">
                  <span className="text-sm">{label}</span>
                  <Icon className="h-4 w-4" />
                </div>
                <div className="text-2xl font-bold mt-2">{value}</div>
                <div className={`text-xs mt-1 ${captionClass ?? "text-muted-foreground"}`}>
                  {caption}
                </div>
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>

      {/* VIP websites — the sites where a problem costs the most. Always
          rendered, even when empty, so the feature is discoverable. */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-lg font-semibold flex items-center gap-2">
            <Star className="h-4 w-4 fill-amber-400 text-amber-500" />
            VIP Websites
          </h2>
          {vipSites.length > SPOTLIGHT_LIMIT && (
            <Link href="/websites?vip=1">
              <Button variant="outline" size="sm">
                View all {vipSites.length}
              </Button>
            </Link>
          )}
        </div>

        {vipSites.length === 0 ? (
          <Card>
            <CardContent className="flex flex-col items-center justify-center gap-2 py-10 text-center">
              <Star className="h-8 w-8 text-muted-foreground" />
              <p className="font-medium">No VIP websites yet</p>
              <p className="text-sm text-muted-foreground max-w-md">
                Mark a site VIP from its page to pin it here — useful for the
                handful of client sites where downtime costs the most.
              </p>
              <Link href="/websites">
                <Button variant="outline" size="sm" className="mt-1">
                  Choose a site
                  <ArrowRight className="h-4 w-4 ml-2" />
                </Button>
              </Link>
            </CardContent>
          </Card>
        ) : (
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {vipSites.slice(0, SPOTLIGHT_LIMIT).map((site) => (
              <SiteHealthCard key={site.id} site={site} showVipMark />
            ))}
          </div>
        )}
      </div>

      {/* Needs attention — non-VIP sites with a real problem. Hidden when
          empty; "nothing is wrong" is better said by absence than by a card. */}
      {needsAttention.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-lg font-semibold flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-amber-500" />
              Needs Attention
            </h2>
            {needsAttention.length > SPOTLIGHT_LIMIT && (
              <Link href="/websites">
                <Button variant="outline" size="sm">
                  View all {needsAttention.length}
                </Button>
              </Link>
            )}
          </div>
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {needsAttention.slice(0, SPOTLIGHT_LIMIT).map((site) => (
              <SiteHealthCard key={site.id} site={site} />
            ))}
          </div>
        </div>
      )}

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
            <h2 className="text-base font-semibold mb-3">Renewal Center</h2>

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
                Open Renewal Center
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
            {websites.slice(0, DASHBOARD_SITE_LIMIT).map((site) => (
              <SiteHealthCard key={site.id} site={site} showVipMark />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
