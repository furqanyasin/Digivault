import { Suspense } from "react";
import Link from "next/link";
import {
  Globe, AlertTriangle, Activity, ShieldCheck, ShieldAlert, KeyRound,
  Star, ExternalLink, Users, UserCog, Code2,
} from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ChartCardHeader } from "@/components/charts/chart-card-header";
import { SummaryChunk } from "@/components/charts/summary-chunk";
import { FleetHealthDonut } from "@/components/charts/fleet-health-donut";
import { RenewalUrgencyBars } from "@/components/charts/renewal-urgency-bars";
import { UptimeCard } from "@/components/charts/uptime-card";
import { FleetChecksRow, type FleetSummary } from "@/components/charts/fleet-checks-row";
import { SetupChecklist, type SetupStep } from "@/components/charts/setup-checklist";
import { AlertsCard } from "@/components/charts/alerts-card";
import { DashboardFilters } from "@/components/dashboard-filters";
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

interface TeamRow {
  id: string;
  member_count: number;
  my_role?: string | null;
}

interface ClientRow {
  id: string;
  name: string;
  status: string;
}

const ATTENTION_LIMIT = 6;

/** Widest window the trend cards can be asked for. Fetched once; the cards
 *  slice it client-side. */
const MAX_DAYS = 90;

async function getData(token: string) {
  // Always the widest window. The trend cards slice it client-side, so a
  // preset click costs nothing — it used to refetch all ten of these.
  const uptimeQuery = `days=${MAX_DAYS}`;

  // Forms and form-errors used to be fetched here for the Coverage card. That
  // card is gone, so the two requests went with it rather than being left to
  // load data nothing renders.
  const [
    websitesResult, monitorsResult, logsResult,
    sslResult, domainResult, hostingResult,
    changesResult, uptimeResult,
    clientsResult, credentialsResult, teamsResult, fleetResult,
  ] = await Promise.allSettled([
    api.getAll<Website>("/api/v1/websites/", token),
    // getAll, not get: the list pages at 25, so a plain get silently dropped
    // monitors past the first page and under-reported how many were down.
    api.getAll<Monitor>("/api/v1/monitors/", token),
    api.get<LogEntry[]>("/api/v1/logs/", token),
    // 90 days feeds the renewal forecast; the card's own figure filters to 30.
    api.get<RenewalRow[]>("/api/v1/websites/expiring-ssl/?days=90", token),
    api.get<RenewalRow[]>("/api/v1/websites/expiring-domains/?days=90", token),
    api.get<RenewalRow[]>("/api/v1/websites/expiring-hosting/?days=90", token),
    api.getAll<ScriptChange>("/api/v1/changes/?unacknowledged=true", token),
    api.get<UptimeTrend>(`/api/v1/monitors/uptime-trend/?${uptimeQuery}`, token),
    // These back the summary chunks for the sidebar sections that have no chart
    // of their own, so the dashboard covers the whole product rather than
    // showing the same four website metrics repeatedly.
    api.getAll<ClientRow>("/api/v1/clients/", token),
    api.getAll<{ id: string }>("/api/v1/credentials/", token),
    // /auth/teams/ already carries member_count per team, so the member figure
    // costs nothing extra. This used to fetch /auth/me/ and then, sequentially,
    // that team's members — two round trips in series after the parallel batch,
    // on every page load and every filter change.
    api.get<TeamRow[]>("/api/v1/auth/teams/", token),
    // One aggregate call for fleet-wide SEO / performance / security. Asking per
    // site would be three requests times the site count.
    api.get<FleetSummary>("/api/v1/websites/fleet-summary/", token),
  ]);

  const val = <T,>(r: PromiseSettledResult<T>, fallback: T): T =>
    r.status === "fulfilled" ? r.value : fallback;

  const teams = val(teamsResult, [] as TeamRow[]);
  const allWebsites = val(websitesResult, [] as Website[]);
  // A site is "reporting" if its snippet has phoned home in the last week.
  // Computed here, not during render: Date.now() in a component body is not
  // idempotent, which React's purity rule rightly rejects.
  const staleBefore = Date.now() - 7 * 86400000;
  const reportingCount = allWebsites.filter(
    (w) => w.last_seen_at && new Date(w.last_seen_at).getTime() >= staleBefore
  ).length;

  return {
    websites: allWebsites,
    reportingCount,
    monitors: val(monitorsResult, [] as Monitor[]),
    activity: val(logsResult, [] as LogEntry[]).slice(0, 6),
    expiringSsl: val(sslResult, [] as RenewalRow[]),
    expiringDomains: val(domainResult, [] as RenewalRow[]),
    expiringHosting: val(hostingResult, [] as RenewalRow[]),
    allChanges: val(changesResult, [] as ScriptChange[]),
    uptimePoints: val(uptimeResult, { days: 0, points: [] } as UptimeTrend).points,
    clients: val(clientsResult, [] as ClientRow[]),
    credentialCount: val(credentialsResult, [] as { id: string }[]).length,
    // The active team is the one the sidebar is showing; fall back to the
    // first so the chunk still reads sensibly if `my_role` is absent.
    memberCount: (teams.find((t) => t.my_role) ?? teams[0])?.member_count ?? 0,
    fleet: val(fleetResult, null as FleetSummary | null),
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
const STATUS_BADGE: Record<string, "destructive" | "warning" | "success" | "secondary"> = {
  active: "success", warning: "warning", critical: "destructive", inactive: "secondary",
};

export default async function DashboardPage() {
  const token = await getAccessToken();
  const {
    websites, monitors, activity,
    expiringSsl, expiringDomains, expiringHosting,
    allChanges, uptimePoints, clients, credentialCount, memberCount,
    reportingCount, fleet,
  } = await getData(token ?? "");

  // Digivault's own infra is hidden from the Change Log and can never be
  // acknowledged, so it must not be counted as an alert either.
  const INTERNAL_DOMAINS = ["digilaticsvps", "digivault.digilatics.co", "cdn.digivault.digilatics.co"];
  const isInternal = (c: ScriptChange) => {
    const hit = (s?: string) => s && INTERNAL_DOMAINS.some((d) => s.includes(d));
    return hit(c.script?.src_url) || hit(c.description);
  };
  const visibleChanges = allChanges.filter((c) => !isInternal(c));
  const pending = visibleChanges.filter((c) => !c.is_acknowledged);
  // Composition of the same list the KPI counts, so the two can't disagree.
  const severityCounts = {
    critical: pending.filter((c) => c.severity === "critical").length,
    high: pending.filter((c) => c.severity === "high").length,
    medium: pending.filter((c) => c.severity === "medium").length,
    low: pending.filter((c) => c.severity === "low").length,
  };

  const monitorsDown = monitors.filter(
    (m) => m.status === "down" || m.status === "degraded"
  ).length;
  const uptimeSamples = monitors.map((m) => m.uptime_30d).filter((v): v is number => v != null);
  const avgUptime = uptimeSamples.length
    ? uptimeSamples.reduce((a, b) => a + b, 0) / uptimeSamples.length
    : null;

  const ssl = expiringSsl;
  const domains = expiringDomains;
  const hosting = expiringHosting;

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


  // One row per renewal type, split by urgency — matches the Renewal Center.
  // Time buckets left the near bands empty, because most renewals sit far out.
  const tallyUrgency = (rows: RenewalRow[]) => {
    const d = (r: RenewalRow) => r.days_until_expiry;
    return {
      urgent: rows.filter((r) => d(r) != null && d(r)! <= 7).length,
      soon: rows.filter((r) => d(r) != null && d(r)! > 7 && d(r)! <= 30).length,
      later: rows.filter((r) => d(r) != null && d(r)! > 30 && d(r)! <= 90).length,
    };
  };
  const renewalUrgency = [
    { label: "Domain", ...tallyUrgency(domains) },
    { label: "SSL", ...tallyUrgency(ssl) },
    { label: "Hosting", ...tallyUrgency(hosting) },
  ];

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


  // --- summary chunks for the sidebar sections without a chart -------------
  const activeClients = clients.filter((c) => c.status === "active").length;
  const inactiveClients = clients.length - activeClients;

  const setupSteps: SetupStep[] = [
    { label: "Add a client", hint: "Who the sites belong to", done: clients.length > 0, href: "/clients/new" },
    { label: "Track a website", hint: "Start monitoring a site", done: websites.length > 0, href: "/websites/new" },
    { label: "Install the snippet", hint: "So a site reports its scripts", done: reportingCount > 0, href: "/websites" },
    { label: "Add an uptime monitor", hint: "Know when a site goes down", done: monitors.length > 0, href: "/monitors/new" },
    { label: "Store a credential", hint: "Encrypted logins in the vault", done: credentialCount > 0, href: "/credentials" },
    { label: "Invite a teammate", hint: "Share the workload", done: memberCount > 1, href: "/team" },
  ];

  return (
    <div className="p-6 lg:p-8 space-y-6">
      {/* Header + the single filter row that scopes everything below it */}
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight lg:text-3xl">Dashboard</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Every website your team is watching
          </p>
        </div>
        {/* DashboardFilters calls useSearchParams, which Next requires to sit
            under a Suspense boundary — without one React throws #419 during the
            streamed render. The fallback reserves the row's height so the header
            doesn't jump. */}
        <Suspense fallback={<div className="h-[30px]" />}>
          <DashboardFilters />
        </Suspense>
      </div>

      {/* The sidebar sections that have no chart of their own. One line each —
          a number and the thing you'd act on — so the dashboard covers the whole
          product instead of restating the same four website metrics. */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <SummaryChunk
          label="Clients"
          value={activeClients}
          caption={
            inactiveClients > 0 ? `${inactiveClients} paused or offboarded` : "All active"
          }
          href="/clients"
          icon={<Users className="h-4 w-4" />}
        />
        <SummaryChunk
          label="Credentials"
          value={credentialCount}
          caption="Encrypted in the vault"
          href="/credentials"
          icon={<KeyRound className="h-4 w-4" />}
        />
        <SummaryChunk
          label="Team"
          value={memberCount}
          caption={memberCount === 1 ? "Just you" : "With vault access"}
          href="/team"
          icon={<UserCog className="h-4 w-4" />}
        />
        <SummaryChunk
          label="Snippet reporting"
          value={reportingCount}
          caption={
            websites.length - reportingCount > 0
              ? `${websites.length - reportingCount} site${websites.length - reportingCount === 1 ? "" : "s"} sending nothing`
              : `All ${websites.length} sites sending data`
          }
          captionTone={websites.length - reportingCount > 0 ? "critical" : "good"}
          href="/websites"
          icon={<Code2 className="h-4 w-4" />}
        />
      </div>


      {/* Fleet composition beside alert volume. Each card owns its headline
          figure — the KPI tiles that used to sit above restated exactly these
          four numbers, which is what made the page feel padded. */}
      <div className="grid gap-4 lg:grid-cols-5">
        {/* h-full + flex-col so the donut can claim the height this card gets
            from its taller neighbour, rather than leaving a gap beneath it. */}
        <Card className="lg:col-span-2">
          <CardContent className="flex h-full flex-col">
            <ChartCardHeader
              title="Website health"
              subtitle="Every site by health band"
              value={websites.length}
              caption={`${bands.healthy} healthy · ${bands.warning + bands.critical} need work`}
              captionTone={bands.critical > 0 ? "critical" : "muted"}
              href="/websites"
            />
            <div className="min-h-0 flex-1">
              <FleetHealthDonut counts={bands} />
            </div>
          </CardContent>
        </Card>

        {/* Client-side: re-buckets on a preset click without a navigation. */}
        <AlertsCard
          alerts={pending.map((c) => ({
            id: c.id,
            severity: c.severity,
            created_at: c.created_at,
          }))}
          severityCounts={severityCounts}
        />
      </div>

      {/* Uptime beside the renewal forecast */}
      <div className="grid gap-4 lg:grid-cols-5">
        {/* Client-side: re-slices the 90-day series on a preset click. */}
        <UptimeCard
          points={uptimePoints}
          avgUptime={avgUptime}
          monitorsDown={monitorsDown}
        />

        <Card className="lg:col-span-2">
          <CardContent>
            <ChartCardHeader
              title="Renewals due"
              subtitle="Within 30 days · forecast to 90"
              value={renewalIds.size}
              caption={
                nextRenewalDays != null
                  ? `Next in ${nextRenewalDays} days`
                  : "Nothing due soon"
              }
              captionTone={
                nextRenewalDays != null && nextRenewalDays <= 7 ? "critical" : "muted"
              }
              href="/renewals"
            />
            <RenewalUrgencyBars rows={renewalUrgency} />
          </CardContent>
        </Card>
      </div>

      {/* The two lists close the page, on the same 5-column grid the chart
          rows use. The 2/3 split mirrors the first chart row rather than the
          second, so the three rows alternate instead of the last two reading
          as one repeated block. */}
      <SetupChecklist steps={setupSteps} />

      {/* Fleet-wide SEO / performance / security. These are scanned per site
          already; nothing summarised them, so a site nobody had ever scanned
          looked identical to a healthy one. */}
      {fleet && fleet.total_sites > 0 && <FleetChecksRow s={fleet} />}

      <div className="grid gap-4 lg:grid-cols-5">
        <Card className="lg:col-span-2">
          <CardContent>
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

                      {/* The meter bar that used to sit here is gone. In the
                          narrower column it was the widest fixed element (112px)
                          and pushed site names into an ellipsis — and it was a
                          third encoding of a value the number and the badge
                          already carry. The score keeps its band colour. */}
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
        <Card className="lg:col-span-3">
          <CardContent>
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
      </div>
    </div>
  );
}
