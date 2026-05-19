import Link from "next/link";
import { Globe, AlertTriangle, CheckCircle, Clock, Plus, ExternalLink, Activity, TrendingUp } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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

function extractDomain(url: string): string {
  try { return new URL(url).hostname; } catch { return url; }
}

function smartUrl(url: string): string {
  try {
    const u = new URL(url);
    const parts = u.pathname.split("/").filter(Boolean);
    const filename = parts[parts.length - 1] ?? "";
    return `${u.hostname}${filename ? `/${filename}` : ""}`;
  } catch {
    return url.length > 55 ? url.slice(0, 52) + "…" : url;
  }
}

// Simple SVG donut chart for risk split
function RiskDonut({ high, medium, low }: { high: number; medium: number; low: number }) {
  const total = high + medium + low;
  if (total === 0) return null;
  const r = 18;
  const circ = 2 * Math.PI * r;
  const segs = [
    { pct: high / total, color: "#ef4444" },
    { pct: medium / total, color: "#f59e0b" },
    { pct: low / total, color: "#3b82f6" },
  ];
  let offset = 0;
  return (
    <svg width="44" height="44" viewBox="0 0 44 44" className="shrink-0">
      {segs.map((s, i) => {
        const dash = s.pct * circ;
        const gap = circ - dash;
        const el = (
          <circle
            key={i}
            cx="22" cy="22" r={r}
            fill="none"
            stroke={s.color}
            strokeWidth="6"
            strokeDasharray={`${dash} ${gap}`}
            strokeDashoffset={-(offset * circ)}
            transform="rotate(-90 22 22)"
          />
        );
        offset += s.pct;
        return el;
      })}
      <text x="22" y="26" textAnchor="middle" fontSize="10" fontWeight="bold" fill="currentColor">{total}</text>
    </svg>
  );
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

  const pending = allChanges.filter((c) => !c.is_acknowledged);
  const highRisk = allChanges.filter(
    (c) => (c.severity === "critical" || c.severity === "high") && !c.is_acknowledged
  );
  const mediumRisk = allChanges.filter((c) => c.severity === "medium" && !c.is_acknowledged);
  const lowRisk = allChanges.filter((c) => c.severity === "low" && !c.is_acknowledged);
  const withIssues = websites.filter((w) => w.status === "critical" || w.status === "warning").length;
  const monitorsDown = monitors.filter((m) => m.status === "down" || m.status === "degraded").length;

  // Group high-risk changes by domain
  const byDomain = highRisk.reduce<Record<string, ScriptChange[]>>((acc, c) => {
    const domain = c.script?.src_url ? extractDomain(c.script.src_url) : "unknown";
    (acc[domain] ??= []).push(c);
    return acc;
  }, {});

  const stats = [
    {
      label: "Monitored Sites", value: websites.length, icon: Globe,
      iconColor: "text-blue-500", borderColor: "border-l-blue-500", bg: "",
      href: "/websites",
    },
    {
      label: "Sites with Issues", value: withIssues, icon: AlertTriangle,
      iconColor: withIssues > 0 ? "text-red-500" : "text-muted-foreground",
      borderColor: withIssues > 0 ? "border-l-red-500" : "border-l-slate-200 dark:border-l-slate-700",
      bg: withIssues > 0 ? "bg-red-50/50 dark:bg-red-950/20" : "",
      href: "/websites",
    },
    {
      label: "Pending Changes", value: pending.length, icon: Clock,
      iconColor: pending.length > 0 ? "text-amber-500" : "text-muted-foreground",
      borderColor: pending.length > 0 ? "border-l-amber-400" : "border-l-slate-200 dark:border-l-slate-700",
      bg: pending.length > 0 ? "bg-amber-50/50 dark:bg-amber-950/20" : "",
      href: null,
    },
    {
      label: "High Risk", value: highRisk.length, icon: AlertTriangle,
      iconColor: highRisk.length > 0 ? "text-red-600" : "text-muted-foreground",
      borderColor: highRisk.length > 0 ? "border-l-red-600" : "border-l-slate-200 dark:border-l-slate-700",
      bg: highRisk.length > 0 ? "bg-red-50/50 dark:bg-red-950/20" : "",
      href: null,
    },
    {
      label: "Monitors", value: monitors.length, icon: Activity,
      iconColor: "text-violet-500", borderColor: "border-l-violet-500", bg: "",
      href: "/monitors",
    },
    {
      label: "Monitors Down", value: monitorsDown, icon: TrendingUp,
      iconColor: monitorsDown > 0 ? "text-red-500" : "text-muted-foreground",
      borderColor: monitorsDown > 0 ? "border-l-red-500" : "border-l-slate-200 dark:border-l-slate-700",
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
        {stats.map(({ label, value, icon: Icon, iconColor, borderColor, bg, href }) => {
          const card = (
            <Card key={label} className={`border-l-4 ${borderColor} ${bg} ${href ? "hover:border-primary/50 transition-colors cursor-pointer" : ""}`}>
              <CardHeader className="flex flex-row items-center justify-between pb-2 pt-4">
                <CardTitle className="text-xs font-medium text-muted-foreground">{label}</CardTitle>
                <Icon className={`h-4 w-4 ${iconColor}`} />
              </CardHeader>
              <CardContent className="pb-4">
                <div className="text-2xl font-bold">{value}</div>
              </CardContent>
            </Card>
          );
          return href ? <Link key={label} href={href}>{card}</Link> : <div key={label}>{card}</div>;
        })}
      </div>

      {/* High-risk alerts */}
      {highRisk.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-3">
              <h2 className="text-lg font-semibold">High-Risk Changes</h2>
              <RiskDonut high={highRisk.length} medium={mediumRisk.length} low={lowRisk.length} />
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-red-500 inline-block" />{highRisk.length} high</span>
                {mediumRisk.length > 0 && <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-amber-400 inline-block" />{mediumRisk.length} medium</span>}
                {lowRisk.length > 0 && <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-blue-400 inline-block" />{lowRisk.length} low</span>}
              </div>
            </div>
            <Link href="/alerts">
              <Button variant="outline" size="sm">View all alerts</Button>
            </Link>
          </div>
          <div className="space-y-3">
            {Object.entries(byDomain).slice(0, 6).map(([domain, changes]) => (
              <Card key={domain} className="border-red-200 dark:border-red-900">
                <CardContent className="p-0">
                  {/* Domain header */}
                  <div className="flex items-center gap-2 px-4 py-2 border-b bg-red-50/50 dark:bg-red-950/20">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={`https://www.google.com/s2/favicons?domain=${domain}&sz=16`}
                      alt=""
                      width={16} height={16}
                      className="rounded-sm opacity-80"
                    />
                    <span className="text-xs font-mono font-semibold">{domain}</span>
                    <Badge variant="destructive" className="ml-auto text-xs">{changes.length}</Badge>
                  </div>
                  {/* Changes list */}
                  <div className="divide-y">
                    {changes.slice(0, 3).map((change) => (
                      <div key={change.id} className="flex items-center justify-between px-4 py-2.5 gap-3">
                        <div className="flex items-center gap-2 min-w-0">
                          <Badge
                            variant={change.severity === "critical" ? "destructive" : "destructive"}
                            className="capitalize text-xs shrink-0"
                          >
                            {change.severity}
                          </Badge>
                          <span className="text-xs capitalize text-muted-foreground shrink-0">{change.change_type}</span>
                          <span className="font-mono text-xs truncate text-muted-foreground" title={change.script?.src_url}>
                            {change.script?.src_url ? smartUrl(change.script.src_url) : "—"}
                          </span>
                        </div>
                        <span className="text-xs text-muted-foreground shrink-0 whitespace-nowrap">{fmtDate(change.created_at)}</span>
                      </div>
                    ))}
                    {changes.length > 3 && (
                      <div className="px-4 py-2 text-xs text-muted-foreground">+{changes.length - 3} more from this domain</div>
                    )}
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      )}

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
                <Card key={site.id} className="hover:border-primary/50 transition-colors">
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

                    {/* Health bar */}
                    <div className="space-y-1">
                      <div className="flex items-center justify-between text-xs text-muted-foreground">
                        <span>Health</span>
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
                      <div className="h-1.5 rounded-full bg-muted overflow-hidden">
                        <div
                          className={`h-full rounded-full transition-all ${STATUS_BAR[site.status] ?? "bg-slate-300"}`}
                          style={{
                            width: site.status === "active" ? "100%" :
                                   site.status === "warning" ? "60%" :
                                   site.status === "critical" ? "25%" : "0%"
                          }}
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
