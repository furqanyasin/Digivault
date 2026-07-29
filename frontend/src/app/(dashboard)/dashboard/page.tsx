import { Suspense } from "react";
import Link from "next/link";
import {
  Globe, Bell, CalendarClock, TrendingUp, AlertTriangle, Activity, ShieldCheck,
  ShieldAlert, KeyRound, ArrowRight, Star, ExternalLink,
} from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { KpiTile } from "@/components/charts/kpi-tile";
import { FleetHealthDonut } from "@/components/charts/fleet-health-donut";
import { ActivityAreaChart } from "@/components/charts/activity-area-chart";
import { RenewalBars } from "@/components/charts/renewal-bars";
import { DashboardFilters } from "@/components/dashboard-filters";
import { AcknowledgeAllButton } from "@/components/acknowledge-all-button";
import { getAccessToken } from "@/lib/server-token";
import { api } from "@/lib/api";
import { healthBand } from "@/lib/chart-theme";
import type { Website, ScriptChange, Monitor } from "@/lib/api";
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

/** `value` is null for days with no checks — see monitors.UptimeTrendView. */
interface UptimeTrend {
  days: number;
  points: { date: string; value: number | null }[];
}

interface ClientRow {
  id: string;
  name: string;
}

const DEFAULT_DAYS = 14;
const MAX_DAYS = 90;
const ATTENTION_LIMIT = 6;

/** Resolve the window the whole page is scoped to. An explicit from+to wins;
 *  half a range is ignored, matching the backend's rule. */
function resolveWindow(from?: string, to?: string, days?: string) {
  const iso = /^\d{4}-\d{2}-\d{2}$/;
  if (from && to && iso.test(from) && iso.test(to)) {
    const [a, b] = from <= to ? [from, to] : [to, from];
    return { from: a, to: b, days: null as number | null };
  }
  const n = Number(days);
  const clamped = Number.isFinite(n) && n > 0 ? Math.min(Math.trunc(n), MAX_DAYS) : DEFAULT_DAYS;
  return { from: null, to: null, days: clamped };
}

const dayKey = (iso: string) => {
  const d = new Date(iso);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

/** Every calendar day in the window, oldest first. */
function windowDays(w: ReturnType<typeof resolveWindow>): string[] {
  const out: string[] = [];
  if (w.from && w.to) {
    const cur = new Date(`${w.from}T00:00:00`);
    const end = new Date(`${w.to}T00:00:00`);
    while (cur <= end && out.length < MAX_DAYS) {
      out.push(dayKey(cur.toISOString()));
      cur.setDate(cur.getDate() + 1);
    }
    return out;
  }
  const today = new Date();
  for (let i = (w.days ?? DEFAULT_DAYS) - 1; i >= 0; i--) {
    const d = new Date(today);
    d.setDate(today.getDate() - i);
    out.push(dayKey(d.toISOString()));
  }
  return out;
}

/** Short axis label — "12 Jul". Full dates live in the tooltip. */
const shortLabel = (day: string) =>
  new Date(`${day}T00:00:00`).toLocaleDateString(undefined, { day: "numeric", month: "short" });

async function getData(token: string, w: ReturnType<typeof resolveWindow>) {
  const uptimeQuery = w.from && w.to ? `from=${w.from}&to=${w.to}` : `days=${w.days}`;

  // Forms and form-errors used to be fetched here for the Coverage card. That
  // card is gone, so the two requests went with it rather than being left to
  // load data nothing renders.
  const [
    websitesResult, monitorsResult, logsResult,
    sslResult, domainResult, hostingResult,
    changesResult, uptimeResult, clientsResult,
  ] = await Promise.allSettled([
    api.getAll<Website>("/api/v1/websites/", token),
    api.get<Monitor[]>("/api/v1/monitors/", token),
    api.get<LogEntry[]>("/api/v1/logs/", token),
    // 90 days feeds the renewal forecast; the KPI filters back down to 30.
    api.get<RenewalRow[]>("/api/v1/websites/expiring-ssl/?days=90", token),
    api.get<RenewalRow[]>("/api/v1/websites/expiring-domains/?days=90", token),
    api.get<RenewalRow[]>("/api/v1/websites/expiring-hosting/?days=90", token),
    api.getAll<ScriptChange>("/api/v1/changes/?unacknowledged=true", token),
    api.get<UptimeTrend>(`/api/v1/monitors/uptime-trend/?${uptimeQuery}`, token),
    api.getAll<ClientRow>("/api/v1/clients/", token),
  ]);

  const val = <T,>(r: PromiseSettledResult<T>, fallback: T): T =>
    r.status === "fulfilled" ? r.value : fallback;

  return {
    websites: val(websitesResult, [] as Website[]),
    monitors: val(monitorsResult, [] as Monitor[]),
    activity: val(logsResult, [] as LogEntry[]).slice(0, 6),
    expiringSsl: val(sslResult, [] as RenewalRow[]),
    expiringDomains: val(domainResult, [] as RenewalRow[]),
    expiringHosting: val(hostingResult, [] as RenewalRow[]),
    allChanges: val(changesResult, [] as ScriptChange[]),
    uptimePoints: val(uptimeResult, { days: 0, points: [] } as UptimeTrend).points,
    clients: val(clientsResult, [] as ClientRow[]),
  };
}

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
const activityStyle = (action: string) =>
  ACTIVITY_STYLE[action] ?? { icon: Activity, className: "bg-slate-500/10 text-slate-600" };

const SCORE_TONE = (s: number) =>
  s >= 85 ? "text-emerald-600" : s >= 60 ? "text-amber-600" : "text-red-600";
const SCORE_BAR = (s: number) =>
  s >= 85 ? "bg-emerald-500" : s >= 60 ? "bg-amber-400" : "bg-red-500";
const STATUS_BADGE: Record<string, "destructive" | "warning" | "success" | "secondary"> = {
  active: "success", warning: "warning", critical: "destructive", inactive: "secondary",
};

export default async function DashboardPage({
  searchParams,
}: {
  // Next 16: searchParams is a Promise and must be awaited.
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const sp = await searchParams;
  const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v);
  const win = resolveWindow(one(sp.from), one(sp.to), one(sp.days));
  const clientId = one(sp.client) ?? "";

  const token = await getAccessToken();
  const {
    websites: allWebsites, monitors, activity,
    expiringSsl, expiringDomains, expiringHosting,
    allChanges, uptimePoints, clients,
  } = await getData(token ?? "", win);

  // --- client filter: scopes every number on the page ----------------------
  const websites = clientId ? allWebsites.filter((w) => w.client === clientId) : allWebsites;
  const siteIds = new Set(websites.map((w) => w.id));
  const scopedToClient = Boolean(clientId);
  const activeClientName = clients.find((c) => c.id === clientId)?.name;

  // Digivault's own infra is hidden from the Change Log and can never be
  // acknowledged, so it must not be counted as an alert either.
  const INTERNAL_DOMAINS = ["digilaticsvps", "digivault.digilatics.co", "cdn.digivault.digilatics.co"];
  const isInternal = (c: ScriptChange) => {
    const hit = (s?: string) => s && INTERNAL_DOMAINS.some((d) => s.includes(d));
    return hit(c.script?.src_url) || hit(c.description);
  };
  const visibleChanges = allChanges.filter(
    (c) => !isInternal(c) && (!scopedToClient || siteIds.has(c.website))
  );
  const pending = visibleChanges.filter((c) => !c.is_acknowledged);
  const highRisk = pending.filter((c) => c.severity === "critical" || c.severity === "high");

  const scopedMonitors = scopedToClient
    ? monitors.filter((m) => m.website && siteIds.has(m.website))
    : monitors;
  const monitorsDown = scopedMonitors.filter(
    (m) => m.status === "down" || m.status === "degraded"
  ).length;
  const uptimeSamples = scopedMonitors.map((m) => m.uptime_30d).filter((v): v is number => v != null);
  const avgUptime = uptimeSamples.length
    ? uptimeSamples.reduce((a, b) => a + b, 0) / uptimeSamples.length
    : null;

  const scopedRenewals = (rows: RenewalRow[]) =>
    scopedToClient ? rows.filter((r) => siteIds.has(r.id)) : rows;
  const ssl = scopedRenewals(expiringSsl);
  const domains = scopedRenewals(expiringDomains);
  const hosting = scopedRenewals(expiringHosting);

  const within30 = (rows: RenewalRow[]) =>
    rows.filter((r) => r.days_until_expiry != null && r.days_until_expiry <= 30);
  const renewalIds = new Set([
    ...within30(ssl).map((r) => r.id),
    ...within30(domains).map((r) => r.id),
    ...within30(hosting).map((r) => r.id),
  ]);
  const nextRenewalDays = [...ssl, ...domains, ...hosting]
    .map((r) => r.days_until_expiry)
    .filter((v): v is number => v != null)
    .sort((a, b) => a - b)[0];

  // --- series, all real -----------------------------------------------------
  const days = windowDays(win);
  const labels = days.map(shortLabel);

  const websiteTrend = days.map((d) => websites.filter((w) => dayKey(w.created_at) <= d).length);
  const alertTrend = days.map((d) => pending.filter((c) => dayKey(c.created_at) === d).length);
  const uptimeByDay = new Map(uptimePoints.map((p) => [p.date, p.value]));
  const uptimeSeries = days.map((d) => uptimeByDay.get(d) ?? null);

  const BUCKETS = [
    { label: "≤30d", from: 0, to: 30 },
    { label: "31–60d", from: 31, to: 60 },
    { label: "61–90d", from: 61, to: 90 },
  ];
  const countIn = (rows: RenewalRow[], from: number, to: number) =>
    rows.filter(
      (r) => r.days_until_expiry != null && r.days_until_expiry >= from && r.days_until_expiry <= to
    ).length;
  const renewalBuckets = BUCKETS.map((b) => ({
    label: b.label,
    ssl: countIn(ssl, b.from, b.to),
    domain: countIn(domains, b.from, b.to),
    hosting: countIn(hosting, b.from, b.to),
  }));
  const renewalTrend = renewalBuckets.map((b) => b.ssl + b.domain + b.hosting);

  // Health bands for the donut. `inactive` is a lifecycle state, so it is
  // counted separately rather than folded into a score band.
  const bands = { healthy: 0, warning: 0, critical: 0, inactive: 0 };
  for (const w of websites) {
    if (w.status === "inactive") bands.inactive += 1;
    else bands[healthBand(w.health_score ?? 100)] += 1;
  }

  // Sites worth opening now: worst score first.
  const needsAttention = websites
    .filter(
      (w) =>
        w.status !== "inactive" &&
        (w.status === "critical" || w.status === "warning" || (w.health_score ?? 100) < 85)
    )
    .sort((a, b) => (a.health_score ?? 100) - (b.health_score ?? 100));

  const rangeCaption = win.from && win.to ? `${win.from} → ${win.to}` : `last ${win.days} days`;

  return (
    <div className="p-6 lg:p-8 space-y-6">
      {/* Header + the single filter row that scopes everything below it */}
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight lg:text-3xl">Dashboard</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {scopedToClient && activeClientName ? (
              <>
                Showing <span className="font-medium text-foreground">{activeClientName}</span> ·{" "}
                {rangeCaption}
              </>
            ) : (
              <>Every website your team is watching · {rangeCaption}</>
            )}
          </p>
        </div>
        {/* DashboardFilters calls useSearchParams, which Next requires to sit
            under a Suspense boundary — without one React throws #419 during the
            streamed render. The fallback reserves the row's height so the header
            doesn't jump. */}
        <Suspense fallback={<div className="h-[30px]" />}>
          <DashboardFilters clients={clients} />
        </Suspense>
      </div>

      {/* KPI row — animated values with a trend line each */}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KpiTile
          label="Websites"
          value={websites.length}
          caption={`${bands.healthy} healthy · ${bands.warning + bands.critical} need work`}
          href="/websites"
          icon={<Globe className="h-4 w-4" />}
          trend={websiteTrend}
          trendLabel="Sites under management"
          goodDirection="up"
        />
        <KpiTile
          label="Open alerts"
          value={pending.length}
          caption={highRisk.length > 0 ? `${highRisk.length} critical` : "None critical"}
          captionTone={highRisk.length > 0 ? "critical" : "muted"}
          href="/alerts"
          icon={<Bell className="h-4 w-4" />}
          trend={alertTrend}
          trendLabel="Alerts raised per day"
          goodDirection="down"
        />
        <KpiTile
          label="Renewals due"
          value={renewalIds.size}
          caption={nextRenewalDays != null ? `Next in ${nextRenewalDays} days` : "Nothing due soon"}
          href="/renewals"
          icon={<CalendarClock className="h-4 w-4" />}
          trend={renewalTrend}
          trendLabel="Renewals due per 30-day window"
          goodDirection="down"
        />
        <KpiTile
          label="Avg uptime"
          value={avgUptime ?? 0}
          suffix="%"
          decimals={2}
          caption={monitorsDown > 0 ? `${monitorsDown} monitor${monitorsDown === 1 ? "" : "s"} down` : "All monitors up"}
          captionTone={monitorsDown > 0 ? "critical" : "muted"}
          href="/monitors"
          icon={<TrendingUp className="h-4 w-4" />}
          trend={uptimeSeries}
          trendLabel="Daily uptime"
          goodDirection="up"
        />
      </div>

      {/* Fleet composition beside alert volume */}
      <div className="grid gap-4 lg:grid-cols-5">
        <Card className="lg:col-span-2">
          <CardContent className="p-5">
            <h2 className="text-sm font-semibold">Website health</h2>
            <p className="mb-4 mt-0.5 text-xs text-muted-foreground">
              Every site by health band
            </p>
            <FleetHealthDonut counts={bands} />
          </CardContent>
        </Card>

        <Card className="lg:col-span-3">
          <CardContent className="p-5">
            <div className="mb-4 flex items-start justify-between gap-3">
              <div>
                <h2 className="text-sm font-semibold">Alert volume</h2>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  Open alerts raised per day · {rangeCaption}
                </p>
              </div>
              <AcknowledgeAllButton
                changeIds={pending.map((c) => c.id)}
                highRiskCount={highRisk.length}
              />
            </div>
            <ActivityAreaChart
              labels={labels}
              series={[{ label: "Alerts raised", data: alertTrend, tone: "critical" }]}
            />
          </CardContent>
        </Card>
      </div>

      {/* Uptime beside the renewal forecast */}
      <div className="grid gap-4 lg:grid-cols-5">
        <Card className="lg:col-span-3">
          <CardContent className="p-5">
            <h2 className="text-sm font-semibold">Uptime</h2>
            <p className="mb-4 mt-0.5 text-xs text-muted-foreground">
              Daily uptime across all monitors · gaps mean no checks ran
            </p>
            <ActivityAreaChart
              labels={labels}
              series={[{ label: "Uptime", data: uptimeSeries, unit: "percent" }]}
            />
          </CardContent>
        </Card>

        <Card className="lg:col-span-2">
          <CardContent className="p-5">
            <div className="mb-4 flex items-start justify-between gap-2">
              <div>
                <h2 className="text-sm font-semibold">Renewals due</h2>
                <p className="mt-0.5 text-xs text-muted-foreground">Next 90 days</p>
              </div>
              <Link href="/renewals">
                <Button variant="ghost" size="sm" className="h-7 px-2 text-xs">
                  Open
                  <ArrowRight className="ml-1 h-3 w-3" />
                </Button>
              </Link>
            </div>
            <RenewalBars buckets={renewalBuckets} />
          </CardContent>
        </Card>
      </div>

      {/* Recent activity — full-width row, matching the rows above it */}
      <Card>
        <CardContent className="p-5">
          <div className="mb-3 flex items-center justify-between gap-3">
            <h2 className="text-sm font-semibold">Recent activity</h2>
            <Link href="/logs">
              <Button variant="outline" size="sm">
                Activity log
              </Button>
            </Link>
          </div>
          {activity.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted-foreground">No recent activity.</p>
          ) : (
            <ul className="divide-y">
              {activity.map((entry) => {
                const { icon: Icon, className } = activityStyle(entry.action);
                return (
                  <li key={entry.id} className="flex items-center gap-3 py-2.5 first:pt-0 last:pb-0">
                    <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full ${className}`}>
                      <Icon className="h-3.5 w-3.5" />
                    </span>
                    <p className="min-w-0 flex-1 truncate text-sm">
                      <span className="font-medium">
                        {entry.actor_name || entry.actor_email || "System"}
                      </span>{" "}
                      <span className="text-muted-foreground">
                        {entry.description || entry.action_label}
                      </span>
                    </p>
                    {/* Timestamp trails at the row end, as in Needs attention. */}
                    <span
                      className="shrink-0 text-xs text-muted-foreground"
                      title={fmtDateTime(entry.created_at)}
                    >
                      {fmtRelative(entry.created_at)}
                    </span>
                  </li>
                );
              })}
            </ul>
          )}
        </CardContent>
      </Card>

      {/* Needs attention — a dense table now, not a wall of cards */}
      <Card>
        <CardContent className="p-5">
          <div className="mb-3 flex items-center justify-between gap-3">
            <h2 className="flex items-center gap-2 text-sm font-semibold">
              <AlertTriangle className="h-4 w-4 text-amber-500" />
              Needs attention
              {needsAttention.length > 0 && (
                <span className="rounded-full bg-muted px-1.5 py-0.5 text-xs font-medium text-muted-foreground">
                  {needsAttention.length}
                </span>
              )}
            </h2>
            <Link href="/websites">
              <Button variant="outline" size="sm">
                All {websites.length} sites
              </Button>
            </Link>
          </div>

          {needsAttention.length === 0 ? (
            <div className="flex flex-col items-center gap-2 py-10 text-center">
              <ShieldCheck className="h-8 w-8 text-emerald-500" />
              <p className="text-sm font-medium">Nothing needs attention</p>
              <p className="text-xs text-muted-foreground">
                Every site is above 85 with no open critical issues.
              </p>
            </div>
          ) : (
            <ul className="divide-y">
              {needsAttention.slice(0, ATTENTION_LIMIT).map((site) => {
                const score = site.health_score ?? 100;
                return (
                  <li key={site.id} className="flex items-center gap-3 py-2.5 first:pt-0">
                    <div className="min-w-0 flex-1">
                      <p className="flex items-center gap-1.5 truncate text-sm font-medium">
                        {site.is_vip && (
                          <Star className="h-3.5 w-3.5 shrink-0 fill-amber-400 text-amber-500" aria-label="VIP" />
                        )}
                        <span className="truncate">{site.name || site.domain}</span>
                      </p>
                      <p className="truncate font-mono text-xs text-muted-foreground">{site.domain}</p>
                    </div>

                    {/* A meter, not a chart: one ratio against a limit. */}
                    <div className="hidden w-28 shrink-0 sm:block">
                      <div
                        className="h-1.5 overflow-hidden rounded-full bg-muted"
                        role="progressbar"
                        aria-valuenow={score}
                        aria-valuemin={0}
                        aria-valuemax={100}
                        aria-label={`Health score for ${site.name || site.domain}`}
                      >
                        <div
                          className={`h-full rounded-full ${SCORE_BAR(score)}`}
                          style={{ width: `${Math.max(0, Math.min(100, score))}%` }}
                        />
                      </div>
                    </div>

                    <span className={`w-8 shrink-0 text-right text-sm font-semibold ${SCORE_TONE(score)}`}>
                      {score}
                    </span>

                    <Badge
                      variant={STATUS_BADGE[site.status] ?? "secondary"}
                      className="h-5 w-[64px] shrink-0 justify-center text-xs"
                    >
                      {site.status}
                    </Badge>

                    {(site.unknown_script_count ?? 0) > 0 && (
                      <span className="hidden shrink-0 items-center gap-1 text-xs font-semibold text-red-600 md:flex">
                        <AlertTriangle className="h-3 w-3" />
                        {site.unknown_script_count}
                      </span>
                    )}

                    <Link href={`/websites/${site.id}`} aria-label={`Open ${site.name || site.domain}`}>
                      <Button variant="ghost" size="sm" className="h-7 w-7 shrink-0 p-0">
                        <ExternalLink className="h-3.5 w-3.5" />
                      </Button>
                    </Link>
                  </li>
                );
              })}
            </ul>
          )}
        </CardContent>
      </Card>

    </div>
  );
}
