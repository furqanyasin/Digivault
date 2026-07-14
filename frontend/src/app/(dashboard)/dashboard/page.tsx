import Link from "next/link";
import { Globe, AlertTriangle, Clock, Plus, ExternalLink, Activity, TrendingUp } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { getAccessToken } from "@/lib/server-token";
import { api } from "@/lib/api";
import type { Website, ScriptChange, Monitor } from "@/lib/api";
import { fmtDate, fmtDateTime } from "@/lib/utils";

async function getData(token: string) {
  const [websitesResult, monitorsResult] = await Promise.allSettled([
    api.get<Website[]>("/api/v1/websites/", token),
    api.get<Monitor[]>("/api/v1/monitors/", token),
  ]);
  const websites = websitesResult.status === "fulfilled" ? websitesResult.value : [];
  const monitors = monitorsResult.status === "fulfilled" ? monitorsResult.value : [];

  const dashboardSites = websites.filter((w) => !w.domain?.includes("digilaticsvps")).slice(0, 5);
  const changeSets = await Promise.allSettled(
    dashboardSites.map((site) =>
      api.get<ScriptChange[]>(`/api/v1/websites/${site.id}/changes/`, token)
    )
  );
  const allChanges = changeSets
    .filter((r) => r.status === "fulfilled")
    .flatMap((r) => (r as PromiseFulfilledResult<ScriptChange[]>).value);

  return { websites, allChanges, monitors };
}

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

export default async function DashboardPage() {
  const token = await getAccessToken();
  const { websites, allChanges, monitors } = await getData(token ?? "");

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
  const withIssues = websites.filter((w) => w.status === "critical" || w.status === "warning").length;
  const monitorsDown = monitors.filter((m) => m.status === "down" || m.status === "degraded").length;

  const stats = [
    {
      label: "Monitored Sites", value: websites.length, icon: Globe,
      chip: "bg-violet-500/10", iconColor: "text-violet-600 dark:text-violet-400", bg: "",
      href: "/websites",
    },
    {
      label: "Sites with Issues", value: withIssues, icon: AlertTriangle,
      chip: withIssues > 0 ? "bg-rose-500/10" : "bg-emerald-500/10",
      iconColor: withIssues > 0 ? "text-rose-600 dark:text-rose-400" : "text-emerald-600 dark:text-emerald-400",
      bg: withIssues > 0 ? "bg-rose-50/50 dark:bg-rose-950/20" : "",
      href: "/websites",
    },
    {
      label: "Pending Changes", value: pending.length, icon: Clock,
      chip: "bg-amber-500/10",
      iconColor: pending.length > 0 ? "text-amber-600 dark:text-amber-400" : "text-amber-500/60",
      bg: pending.length > 0 ? "bg-amber-50/50 dark:bg-amber-950/20" : "",
      href: null,
    },
    {
      label: "High Risk", value: highRisk.length, icon: AlertTriangle,
      chip: highRisk.length > 0 ? "bg-red-500/10" : "bg-emerald-500/10",
      iconColor: highRisk.length > 0 ? "text-red-600 dark:text-red-400" : "text-emerald-600 dark:text-emerald-400",
      bg: highRisk.length > 0 ? "bg-red-50/50 dark:bg-red-950/20" : "",
      href: null,
    },
    {
      label: "Monitors", value: monitors.length, icon: Activity,
      chip: "bg-sky-500/10", iconColor: "text-sky-600 dark:text-sky-400", bg: "",
      href: "/monitors",
    },
    {
      label: "Monitors Down", value: monitorsDown, icon: TrendingUp,
      chip: monitorsDown > 0 ? "bg-red-500/10" : "bg-emerald-500/10",
      iconColor: monitorsDown > 0 ? "text-red-600 dark:text-red-400" : "text-emerald-600 dark:text-emerald-400",
      bg: monitorsDown > 0 ? "bg-red-50/50 dark:bg-red-950/20" : "",
      href: "/monitors",
    },
  ];

  return (
    <div className="p-8 space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Dashboard</h1>
          <p className="text-muted-foreground mt-1">Overview of your script monitoring activity</p>
        </div>
        <Link href="/websites/new">
          <Button>
            <Plus className="h-4 w-4 mr-2" />
            Add website
          </Button>
        </Link>
      </div>

      {/* Stats */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        {stats.map(({ label, value, icon: Icon, chip, iconColor, bg, href }) => {
          const card = (
            <Card key={label} className={`${bg} ${href ? "hover:border-primary/50 hover:shadow-md transition-all cursor-pointer" : ""}`}>
              <CardContent className="flex items-center gap-3 p-4">
                <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg ${chip}`}>
                  <Icon className={`h-5 w-5 ${iconColor}`} />
                </div>
                <div className="min-w-0">
                  <div className="text-2xl font-bold leading-none">{value}</div>
                  <div className="text-xs font-medium text-muted-foreground mt-1 truncate">{label}</div>
                </div>
              </CardContent>
            </Card>
          );
          return href ? <Link key={label} href={href}>{card}</Link> : <div key={label}>{card}</div>;
        })}
      </div>

      {/* Website cards grid */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-lg font-semibold">Your Sites</h2>
          <Link href="/websites">
            <Button variant="outline" size="sm">View all</Button>
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
            {websites.map((site) => {
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
