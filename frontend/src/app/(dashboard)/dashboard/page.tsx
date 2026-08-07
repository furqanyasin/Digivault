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
import { AlertsCard } from "@/components/charts/alerts-card";
import { ClientPortfolio, type ClientPortfolioRow } from "@/components/charts/client-portfolio";
import { DashboardFilters } from "@/components/dashboard-filters";
import { getAccessToken } from "@/lib/server-token";
import { api } from "@/lib/api";
import { healthBand } from "@/lib/chart-theme";
import type { Website, ScriptChange, Monitor, User } from "@/lib/api";
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
  my_features?: string[];
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
    clientsResult, credentialsResult, teamsResult, meResult,
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
    // Which of those teams is the active one — the role and feature grants that
    // decide what this page may show hang off it. In the same parallel batch,
    // so it costs no extra round trip.
    api.get<User>("/api/v1/auth/me/", token),
  ]);

  const val = <T,>(r: PromiseSettledResult<T>, fallback: T): T =>
    r.status === "fulfilled" ? r.value : fallback;

  const teams = val(teamsResult, [] as TeamRow[]);
  const me = val(meResult, null as User | null);
  const activeTeam = teams.find((t) => t.id === me?.active_team) ?? teams[0] ?? null;
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
    memberCount: activeTeam?.member_count ?? 0,
    // Lowest privilege wins when the role can't be read — a dashboard that
    // shows a member less than they're entitled to is recoverable; one that
    // shows them a section they'll be bounced out of is not.
    role: activeTeam?.my_role ?? "viewer",
    features: activeTeam?.my_features ?? [],
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
    reportingCount, role, features,
  } = await getData(token ?? "");

  // Same rules the sidebar nav applies (see (dashboard)/layout.tsx): owner sees
  // everything, manager-only sections stay role-gated, everything else follows
  // the member's feature grants. Without this a viewer got cards linking into
  // pages the FeatureGuard immediately bounced them back out of.
  const isOwner = role === "owner";
  const isManager = isOwner || role === "manager";
  const can = (feature: string) => isOwner || features.includes(feature);

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

  // Clients a non-manager actually has sites for. Derived from `websites`, not
  // from the client list: the websites endpoint narrows to a member's
  // assignments, the clients endpoint does not — so counting off the client
  // list would tell an assigned viewer about accounts they can't see a site of.
  const clientRows: ClientPortfolioRow[] = Object.values(
    websites.reduce<Record<string, ClientPortfolioRow>>((acc, w) => {
      const key = w.client ?? "unassigned";
      const row = (acc[key] ??= {
        id: w.client,
        name: w.client_name || "No client",
        siteCount: 0,
        needsWork: 0,
      });
      row.siteCount += 1;
      if (w.status !== "inactive" && (w.status === "critical" || w.status === "warning" || (w.health_score ?? 100) < 85)) {
        row.needsWork += 1;
      }
      return acc;
    }, {})
  ).sort((a, b) => b.needsWork - a.needsWork || b.siteCount - a.siteCount);

  // The tiles a member is allowed to open. Rendered from an array so a hidden
  // one closes the gap instead of leaving a blank column.
  const chunks = [
    can("clients") && (
      <SummaryChunk
        key="clients"
        label="Active clients"
        value={activeClients}
        caption={
          inactiveClients > 0 ? `${inactiveClients} paused or offboarded` : "All active"
        }
        href="/clients"
        icon={<Users className="h-4 w-4" />}
      />
    ),
    can("credentials") && (
      <SummaryChunk
        key="credentials"
        label="Credentials"
        value={credentialCount}
        caption="Encrypted in the vault"
        href="/credentials"
        icon={<KeyRound className="h-4 w-4" />}
      />
    ),
    // Team management is manager-only, so the headcount is too.
    isManager && (
      <SummaryChunk
        key="team"
        label="Team"
        value={memberCount}
        caption={memberCount === 1 ? "Just you" : "With vault access"}
        href="/team"
        icon={<UserCog className="h-4 w-4" />}
      />
    ),
    can("websites") && (
      <SummaryChunk
        key="snippet"
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
    ),
  ].filter(Boolean);

  const CHUNK_GRID = ["", "grid-cols-1", "sm:grid-cols-2", "sm:grid-cols-2 lg:grid-cols-3", "sm:grid-cols-2 lg:grid-cols-4"];

  // The Renewal Center is manager-only, so its forecast is too. The slot goes
  // to the client breakdown rather than collapsing — that is the data a viewer
  // came for.
  const sideCard = (isManager && can("renewals")) ? (
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
  ) : can("websites") ? (
    <ClientPortfolio
      rows={clientRows}
      siteCount={websites.length}
      canOpenClients={can("clients")}
    />
  ) : null;

  // Every card row below pairs a 2-column card with a 3-column one. When a
  // member's grants hide one of the pair, the row has to narrow to the survivor's
  // own span — left in a 5-column track it would sit in a 2/5 or 3/5 sliver with
  // the rest of the row blank.
  const rowCols = (wide2: boolean, wide3: boolean) =>
    wide2 && wide3 ? "lg:grid-cols-5" : wide2 ? "lg:grid-cols-2" : "lg:grid-cols-3";

  const healthRowCols = rowCols(can("websites"), can("alerts"));
  const uptimeRowCols = rowCols(Boolean(sideCard), can("websites"));
  const listRowCols = rowCols(can("websites"), can("activity_log"));

  // Nothing on this page survived their grants. Say so, rather than serving a
  // header over an empty page that reads as a broken dashboard.
  const hasAnyCard =
    chunks.length > 0 || can("websites") || can("alerts") || can("activity_log")
    || Boolean(sideCard);

  return (
    <div className="p-6 lg:p-8 space-y-6">
      {/* Header + the single filter row that scopes everything below it */}
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight lg:text-3xl">Dashboard</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {isManager
              ? "Every website your team is watching"
              : "The clients and websites you have access to"}
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
      {chunks.length > 0 && (
        <div className={`grid gap-3 ${CHUNK_GRID[chunks.length]}`}>{chunks}</div>
      )}


      {/* Fleet composition beside alert volume. Each card owns its headline
          figure — the KPI tiles that used to sit above restated exactly these
          four numbers, which is what made the page feel padded. */}
      {/* Grid width follows what actually renders — a hidden neighbour would
          otherwise leave the surviving card stranded in a 5-column track. */}
      {(can("websites") || can("alerts")) && (
        <div className={`grid gap-4 ${healthRowCols}`}>
          {/* h-full + flex-col so the donut can claim the height this card gets
              from its taller neighbour, rather than leaving a gap beneath it. */}
          {can("websites") && (
            <Card className="lg:col-span-2">
              <CardContent className="flex h-full flex-col">
                <ChartCardHeader
                  title="Website health"
                  subtitle={isManager ? "Every site by health band" : "Your sites by health band"}
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
          )}

          {/* Client-side: re-buckets on a preset click without a navigation. */}
          {can("alerts") && (
            <AlertsCard
              alerts={pending.map((c) => ({
                id: c.id,
                severity: c.severity,
                created_at: c.created_at,
              }))}
              severityCounts={severityCounts}
            />
          )}
        </div>
      )}

      {/* Uptime beside the renewal forecast — or, for a member who has no
          Renewal Center to open, the clients their sites belong to. Uptime is
          website data (monitors live in each site's Uptime tab), so it follows
          the websites grant. */}
      {(can("websites") || sideCard) && (
        <div className={`grid gap-4 ${uptimeRowCols}`}>
          {/* Client-side: re-slices the 90-day series on a preset click. */}
          {can("websites") && (
            <UptimeCard
              points={uptimePoints}
              avgUptime={avgUptime}
              monitorsDown={monitorsDown}
            />
          )}
          {sideCard}
        </div>
      )}

      {/* The two lists close the page, on the same 5-column grid the chart
          rows use. The 2/3 split mirrors the first chart row rather than the
          second, so the three rows alternate instead of the last two reading
          as one repeated block. */}
      {(can("websites") || can("activity_log")) && (
      <div className={`grid gap-4 ${listRowCols}`}>
        {can("websites") && (
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
              {can("websites") && (
                <Link href="/websites">
                  <Button variant="outline" size="sm">
                    All {websites.length} sites
                  </Button>
                </Link>
              )}
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

                      {can("websites") && (
                        <Link href={`/websites/${site.id}`} aria-label={`Open ${site.name || site.domain}`}>
                          <Button variant="ghost" size="sm" className="h-7 w-7 shrink-0 p-0">
                            <ExternalLink className="h-3.5 w-3.5" />
                          </Button>
                        </Link>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </CardContent>
        </Card>
        )}
        {can("activity_log") && (
        <Card className="lg:col-span-3">
          <CardContent>
            <div className="mb-3 flex items-center justify-between gap-3">
              <h2 className="text-sm font-semibold">
                {isManager ? "Recent activity" : "Your recent activity"}
              </h2>
              {/* Reachable by anyone granted the feature — the log endpoint
                  scopes a non-manager to their own rows, so the button no
                  longer leads somewhere they'd be bounced out of. */}
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
        )}
      </div>
      )}

      {!hasAnyCard && (
        <Card>
          <CardContent className="py-12 text-center">
            <p className="text-sm font-medium">Nothing&apos;s been shared with you yet</p>
            <p className="mt-1 text-sm text-muted-foreground">
              Ask your team manager to grant you access to the sections you need.
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
