import Link from "next/link";
import { Globe, AlertTriangle, CheckCircle, Clock, Plus, ExternalLink, Activity } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { getAccessToken } from "@/lib/server-token";
import { api } from "@/lib/api";
import type { Website, ScriptChange, Monitor } from "@/lib/api";

async function getData(token: string) {
  const [websitesResult, monitorsResult] = await Promise.allSettled([
    api.get<Website[]>("/api/v1/websites/", token),
    api.get<Monitor[]>("/api/v1/monitors/", token),
  ]);
  const websites = websitesResult.status === "fulfilled" ? websitesResult.value : [];
  const monitors = monitorsResult.status === "fulfilled" ? monitorsResult.value : [];

  const changeSets = await Promise.allSettled(
    websites.slice(0, 5).map((site) =>
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

export default async function DashboardPage() {
  const token = await getAccessToken();
  const { websites, allChanges, monitors } = await getData(token ?? "");

  const pending = allChanges.filter((c) => !c.is_acknowledged);
  const highRisk = allChanges.filter(
    (c) => (c.severity === "critical" || c.severity === "high") && !c.is_acknowledged
  );
  const withIssues = websites.filter((w) => w.status === "critical" || w.status === "warning").length;
  const monitorsDown = monitors.filter((m) => m.status === "down" || m.status === "degraded").length;

  const stats = [
    { label: "Monitored Sites", value: websites.length, icon: Globe, color: "text-blue-500" },
    { label: "Sites with Issues", value: withIssues, icon: AlertTriangle, color: withIssues > 0 ? "text-red-500" : "text-muted-foreground" },
    { label: "Pending Changes", value: pending.length, icon: Clock, color: pending.length > 0 ? "text-amber-500" : "text-muted-foreground" },
    { label: "High Risk", value: highRisk.length, icon: AlertTriangle, color: highRisk.length > 0 ? "text-red-500" : "text-muted-foreground" },
    { label: "Monitors", value: monitors.length, icon: Activity, color: "text-violet-500", href: "/monitors" },
    { label: "Monitors Down", value: monitorsDown, icon: Activity, color: monitorsDown > 0 ? "text-red-500" : "text-muted-foreground", href: "/monitors" },
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
        {stats.map(({ label, value, icon: Icon, color, href }) => {
          const card = (
            <Card key={label} className={href ? "hover:border-primary/50 transition-colors cursor-pointer" : ""}>
              <CardHeader className="flex flex-row items-center justify-between pb-2">
                <CardTitle className="text-sm font-medium text-muted-foreground">{label}</CardTitle>
                <Icon className={`h-4 w-4 ${color}`} />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{value}</div>
              </CardContent>
            </Card>
          );
          return href ? <Link key={label} href={href}>{card}</Link> : card;
        })}
      </div>

      {/* High-risk alerts */}
      {highRisk.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-lg font-semibold">High-Risk Changes</h2>
            <Link href="/alerts">
              <Button variant="outline" size="sm">View all alerts</Button>
            </Link>
          </div>
          <div className="space-y-2">
            {highRisk.slice(0, 5).map((change) => (
              <Card key={change.id} className="border-red-200">
                <CardContent className="flex items-center justify-between py-3 px-4">
                  <div>
                    <p className="text-sm font-medium capitalize">{change.change_type}</p>
                    <p className="text-xs text-muted-foreground mt-0.5">{change.description}</p>
                  </div>
                  <Badge variant="destructive" className="capitalize">{change.severity}</Badge>
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
            {websites.map((site) => (
              <Card key={site.id} className="hover:border-primary/50 transition-colors">
                <CardContent className="p-5">
                  <div className="flex items-start justify-between mb-3">
                    <div className="flex items-center gap-2 min-w-0">
                      <span className={`h-2.5 w-2.5 rounded-full shrink-0 ${STATUS_DOT[site.status] ?? "bg-slate-400"}`} />
                      <div className="min-w-0">
                        <p className="font-semibold text-sm truncate">{site.name || site.domain}</p>
                        <p className="text-xs text-muted-foreground font-mono truncate">{site.domain}</p>
                      </div>
                    </div>
                    <Link href={`/websites/${site.id}`}>
                      <Button variant="ghost" size="sm" className="shrink-0 ml-2">
                        <ExternalLink className="h-3.5 w-3.5" />
                      </Button>
                    </Link>
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
                      <span className="flex items-center gap-1">
                        <Clock className="h-3 w-3" />
                        {new Date(site.last_seen_at).toLocaleDateString()}
                      </span>
                    )}
                  </div>

                  <div className="mt-3">
                    <Badge
                      variant={
                        site.status === "critical" ? "destructive" :
                        site.status === "warning" ? "warning" :
                        site.status === "active" ? "success" : "secondary"
                      }
                      className="text-xs"
                    >
                      {site.status ?? "unknown"}
                    </Badge>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
