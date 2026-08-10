import Link from "next/link";
import { ArrowLeft, AlertTriangle, CheckCircle, Code, ExternalLink, Globe, Shield, Settings, Bell } from "lucide-react";
import { getAccessToken } from "@/lib/server-token";
import { api } from "@/lib/api";
import type { Website, Script, ScriptChange, DomainInfo, Monitor, PerformanceReport, CruxReport, DetectedForm, FormSubmissionError, PhpError, SiteEvent, VulnerabilityReport } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { CopySnippet } from "@/components/copy-snippet";
import { RefreshDomainButton } from "@/components/refresh-domain-button";
import { PerformanceTab } from "@/components/performance-tab";
import { VerifySnippetButton } from "@/components/verify-snippet-button";
import { ScriptsTab } from "@/components/scripts-tab";
import { countScriptDomains } from "@/lib/script-domains";
import { countManagedForms } from "@/lib/detected-forms";
import { PluginsTab } from "@/components/plugins-tab";
import { FormsTab } from "@/components/forms-tab";
import { PhpErrorsTab } from "@/components/php-errors-tab";
import { SeoTab, type SeoReport } from "@/components/seo-tab";
import { WebsiteAlertsStatus } from "@/components/website-alerts-status";
import { UptimeTab } from "@/components/uptime-tab";
import { ReportsTab } from "@/components/reports-tab";
import { WebsiteAssignments } from "@/components/website-assignments";
import { HealthScoreInfo } from "@/components/health-score-info";
import { VipToggleButton } from "@/components/vip-toggle-button";
import { SiteOverviewGrid, type OverviewMetrics } from "@/components/site-overview-grid";
import { SiteLoginButton } from "@/components/site-login-card";
import { fmtDate, fmtDateTime } from "@/lib/utils";

interface SiteActivityEntry {
  id: string;
  actor_email?: string | null;
  actor_name?: string | null;
  action: string;
  description: string;
  created_at: string;
}

async function getData(token: string, id: string) {
  // All tab data is fetched up front so the tabs can switch instantly on the
  // client (no per-tab server navigation). Runs in parallel; the instant
  // loading skeleton (loading.tsx) covers the initial wait.
  const [website, scripts, changes, domain, perfMobile, perfDesktop, crux, forms, formErrors, phpErrors, siteEvents, vulns, seoReport, monitors, siteActivity] = await Promise.allSettled([
    api.get<Website>(`/api/v1/websites/${id}/`, token),
    api.get<Script[]>(`/api/v1/websites/${id}/scripts/`, token),
    api.get<ScriptChange[]>(`/api/v1/websites/${id}/changes/`, token),
    api.get<DomainInfo | null>(`/api/v1/websites/${id}/domain/`, token),
    api.get<PerformanceReport[]>(`/api/v1/websites/${id}/performance/?strategy=mobile&limit=30`, token),
    api.get<PerformanceReport[]>(`/api/v1/websites/${id}/performance/?strategy=desktop&limit=30`, token),
    api.get<CruxReport[]>(`/api/v1/websites/${id}/crux/`, token),
    api.get<DetectedForm[]>(`/api/v1/websites/${id}/forms/`, token),
    api.get<FormSubmissionError[]>(`/api/v1/websites/${id}/form-errors/`, token),
    api.get<PhpError[]>(`/api/v1/websites/${id}/php-errors/`, token),
    api.get<SiteEvent[]>(`/api/v1/websites/${id}/events/`, token),
    // Still fetched with the Security tab gone: the health-score explainer on
    // Overview breaks the score down by open vulnerability.
    api.get<VulnerabilityReport[]>(`/api/v1/websites/${id}/vulnerabilities/`, token),
    api.get<SeoReport>(`/api/v1/websites/${id}/seo/`, token),
    api.get<Monitor[]>(`/api/v1/monitors/?website=${id}`, token),
    api.get<SiteActivityEntry[] | { results: SiteActivityEntry[] }>(`/api/v1/logs/?website_id=${id}`, token),
  ]);
  const resolvedFormErrors =
    formErrors.status === "fulfilled" ? formErrors.value : [];
  // Distinct forms that failed in the last 7 days — one broken form throwing 50
  // errors is still one broken form. Computed here rather than during render,
  // because Date.now() in a component body is not idempotent.
  const weekAgo = Date.now() - 7 * 86400000;
  const brokenForms7d = new Set(
    resolvedFormErrors
      .filter((e) => new Date(e.created_at).getTime() >= weekAgo)
      .map((e) => e.form_id || e.page_url)
  ).size;

  return {
    brokenForms7d,
    website: website.status === "fulfilled" ? website.value : null,
    scripts: scripts.status === "fulfilled" ? scripts.value : [],
    changes: changes.status === "fulfilled" ? changes.value : [],
    domainInfo: domain.status === "fulfilled" ? domain.value : null,
    mobileReports: perfMobile.status === "fulfilled" ? perfMobile.value : [],
    desktopReports: perfDesktop.status === "fulfilled" ? perfDesktop.value : [],
    cruxReports: crux.status === "fulfilled" ? crux.value : [],
    forms: forms.status === "fulfilled" ? forms.value : [],
    formErrors: formErrors.status === "fulfilled" ? formErrors.value : [],
    phpErrors: phpErrors.status === "fulfilled" ? phpErrors.value : [],
    siteEvents: siteEvents.status === "fulfilled" ? siteEvents.value : [],
    vulns: vulns.status === "fulfilled" ? vulns.value : [],
    seoReport: seoReport.status === "fulfilled" ? seoReport.value : null,
    monitors: monitors.status === "fulfilled" ? monitors.value : [],
    siteActivity:
      siteActivity.status === "fulfilled"
        ? (Array.isArray(siteActivity.value) ? siteActivity.value : siteActivity.value?.results ?? [])
        : [],
  };
}

function severityVariant(s: string): "destructive" | "warning" | "secondary" {
  if (s === "high" || s === "critical") return "destructive";
  if (s === "medium") return "warning";
  return "secondary";
}

const SEV_STRIPE: Record<string, string> = {
  critical: "border-l-red-600",
  high:     "border-l-red-400",
  medium:   "border-l-amber-400",
  low:      "border-l-blue-400",
};

// Query params that identify WHICH tag this is (GTM container, Google Ads
// conversion ID, reCAPTCHA site key) — kept in the shortened display so
// e.g. gtag/js?id=AW-123456789 stays distinguishable. Everything else is
// cache-buster noise and dropped.
const IDENTIFYING_PARAMS = ["id", "client", "render", "tid", "cx", "l"];

function smartUrl(url: string): string {
  try {
    const u = new URL(url.startsWith("//") ? `https:${url}` : url);
    const parts = u.pathname.split("/").filter(Boolean);
    const filename = parts[parts.length - 1] ?? "";
    const kept = IDENTIFYING_PARAMS
      .filter((p) => u.searchParams.has(p))
      .map((p) => `${p}=${u.searchParams.get(p)}`);
    const query = kept.length ? `?${kept.join("&")}` : "";
    return `${u.hostname}${filename ? `/${filename}` : ""}${query}`;
  } catch {
    return url.length > 55 ? url.slice(0, 52) + "…" : url;
  }
}

function isExpiringSoon(date: string | number | null | undefined): boolean {
  if (!date) return false;
  if (typeof date === "number") return date > 0 && date <= 30;
  const diff = new Date(date).getTime() - Date.now();
  return diff > 0 && diff < 30 * 24 * 60 * 60 * 1000;
}

/** pass / missing / error for an email-auth record. "error" is called out
 *  separately from "missing": a resolver failure is not a misconfiguration, and
 *  telling a client their SPF is missing when DNS simply timed out is worse than
 *  saying nothing. */
function AuthRow({ label, status, detail }: { label: string; status: string; detail?: string }) {
  const tone =
    status === "pass" ? "text-emerald-600"
    : status === "missing" ? "text-amber-600"
    : status === "error" ? "text-red-600"
    : "text-muted-foreground";
  const text =
    status === "pass" ? "Pass"
    : status === "missing" ? "Not set"
    : status === "error" ? "Lookup failed"
    : "Not checked";
  return (
    <div className="flex justify-between gap-2 py-0.5">
      <span className="text-muted-foreground text-sm shrink-0">{label}</span>
      <span className={`text-right text-xs font-mono font-semibold ${tone}`} title={detail || undefined}>
        {text}
        {status === "pass" && detail ? ` (${detail})` : ""}
      </span>
    </div>
  );
}

function InfoRow({ label, value, highlight, note }: {
  label: string;
  value: string | null | undefined;
  highlight?: boolean;
  /** Where the value came from, when that isn't obvious — e.g. a date typed on
   *  the client record rather than detected. */
  note?: string;
}) {
  return (
    <div className="flex justify-between gap-2 py-0.5">
      <span className="text-muted-foreground text-sm shrink-0">{label}</span>
      <span className="flex items-center gap-1.5 min-w-0">
        {note && (
          <span className="shrink-0 rounded border px-1 text-[10px] leading-4 text-muted-foreground">
            {note}
          </span>
        )}
        <span className={`text-right text-sm truncate font-mono text-xs ${highlight ? "text-amber-600 font-semibold" : ""}`}>
          {value || "—"}
        </span>
      </span>
    </div>
  );
}

export default async function WebsiteDetailPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ tab?: string }>;
}) {
  const { id } = await params;
  const { tab: rawTab = "overview" } = await searchParams;
  // The Tracking tab merged into Scripts and Security was withdrawn — keep old
  // deep links landing somewhere rather than on an empty tab panel.
  const tab =
    rawTab === "tracking" ? "scripts"
    : rawTab === "security" || rawTab === "js-errors" ? "overview"
    : rawTab;
  const token = await getAccessToken();
  const { brokenForms7d, website, scripts, changes, domainInfo, mobileReports, desktopReports, cruxReports, forms, formErrors, phpErrors, siteEvents, vulns, seoReport, monitors, siteActivity } = await getData(token ?? "", id);

  if (!website) {
    return (
      <div className="p-8">
        <p className="text-muted-foreground">Website not found or failed to load.</p>
      </div>
    );
  }

  // Plugins, PHP Errors and Site Events are WordPress-only concepts — hide them
  // for other platforms (detected via the site scan).
  const isWordPress = website.platform === "wordpress";

  const INTERNAL_DOMAINS = ["digilaticsvps", "digivault.digilatics.co", "cdn.digivault.digilatics.co"];

  function isInternalStr(s: string | undefined): boolean {
    if (!s) return false;
    return INTERNAL_DOMAINS.some((d) => s.includes(d));
  }

  // A change is internal if either its linked script URL or the description text contains an internal domain.
  // WP-core scripts (wp-includes) have no linked Script record so their URL only appears in description.
  function isInternalChange(c: ScriptChange): boolean {
    return isInternalStr(c.script?.src_url) || isInternalStr(c.description);
  }

  // Scripts tab / stats: hide internal infrastructure noise
  const activeScripts = scripts.filter((s) => s.is_active && !isInternalStr(s.src_url));
  // Don't show scripts the classifier never recognised once they've been
  // triaged — they're resolved noise. Unknowns still pending review stay
  // visible so they can be actioned.
  const displayScripts = activeScripts.filter(
    (s) => s.provider !== "unknown" || s.review_status === "pending"
  );
  // Scripts tab additionally shows inactive scripts (with an Inactive badge)
  // so a tracking code that stopped loading is visible, not silently gone.
  const scriptsForTab = scripts.filter(
    (s) =>
      !isInternalStr(s.src_url) &&
      (s.provider !== "unknown" || s.review_status === "pending")
  );
  // Plugins tab: needs digilaticsvps scripts to detect WP plugins
  const allActiveScripts = scripts.filter((s) => s.is_active);

  // WP-only tabs appear only when they actually have something to show —
  // an empty PHP Errors / Site Events / Plugins tab is noise.
  const showPlugins = isWordPress && allActiveScripts.some(
    (s) => s.wp_plugin || /\/wp-content\/plugins\//.test(s.src_url)
  );
  const showPhpErrors = isWordPress && phpErrors.length > 0;

  const visibleChanges = changes.filter((c) => !isInternalChange(c));
  const pendingChanges = visibleChanges.filter((c) => !c.is_acknowledged);

  // One timeline. Script diffs and site events answer the same question — "what
  // changed on this site" — and reading them in two places means correlating a
  // plugin update against a script change by eye, which is exactly the link
  // worth seeing. Script changes carry an acknowledgement state; site events are
  // observations with nothing to decide, so that column reads "—" for them.
  const changeLog = [
    ...visibleChanges.map((change) => ({
      kind: "script" as const,
      id: `change-${change.id}`,
      at: change.created_at,
      change,
    })),
    ...siteEvents.map((event) => ({
      kind: "event" as const,
      id: `event-${event.id}`,
      at: event.occurred_at,
      event,
    })),
  ].sort((a, b) => (a.at < b.at ? 1 : a.at > b.at ? -1 : 0));

  // Overview chunk metrics. Everything here comes from data the page already
  // fetched, so the summary grid costs no extra requests.
  const sevCount = (s: string) => pendingChanges.filter((c) => c.severity === s).length;
  const latestScore = (rows: PerformanceReport[]) =>
    rows.find((r) => r.performance_score != null)?.performance_score ?? null;
  const liveMonitors = monitors.filter((mo) => mo.status !== "paused");
  const uptimeSamples = liveMonitors
    .map((mo) => mo.uptime_30d)
    .filter((v): v is number => v != null);
  // Deduplicated the same way the forms table groups its rows, so the overview
  // tile and the tab badge both match the "Detected forms" count on that tab.
  const managedFormCount = countManagedForms(forms);
  const overviewMetrics: OverviewMetrics = {
    health: { score: website.health_score ?? 100, status: website.status },
    scripts: {
      total: displayScripts.length,
      unknown: displayScripts.filter((sc) => sc.provider === "unknown").length,
      categories: new Set(displayScripts.map((sc) => sc.category).filter(Boolean)).size,
    },
    forms: {
      total: managedFormCount,
      broken: brokenForms7d,
    },
    uptime: {
      pct: uptimeSamples.length
        ? uptimeSamples.reduce((a, b) => a + b, 0) / uptimeSamples.length
        : null,
      up: liveMonitors.filter((mo) => mo.status === "up").length,
      down: liveMonitors.filter((mo) => mo.status === "down").length,
      degraded: liveMonitors.filter((mo) => mo.status === "degraded").length,
      monitors: liveMonitors.length,
      // Real check results from the busiest monitor, oldest first.
      recent: (liveMonitors.find((mo) => (mo.recent_statuses ?? []).length)?.recent_statuses ?? []),
    },
    performance: {
      mobile: latestScore(mobileReports),
      desktop: latestScore(desktopReports),
    },
    changelog: {
      pending: pendingChanges.length,
      critical: sevCount("critical"),
      high: sevCount("high"),
      medium: sevCount("medium"),
      low: sevCount("low"),
    },
    seo: {
      checked: seoReport?.check_status === "done",
      indexable: seoReport?.homepage_indexable ?? null,
      noindex: seoReport?.noindex_count ?? 0,
      sitemapPages: seoReport?.sitemap_url_count ?? 0,
      robotsBlocked: seoReport?.robots_blocks_all ?? false,
    },
  };
  // `domain` is stored bare (no scheme), so build a real URL for the Visit link.
  const siteUrl = /^https?:\/\//.test(website.domain) ? website.domain : `https://${website.domain}`;

  return (
    <div className="p-8 space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div className="space-y-1">
          <Link href="/websites" className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors mb-2">
            <ArrowLeft className="h-3.5 w-3.5" />
            Websites
          </Link>
          <h1 className="text-3xl font-bold tracking-tight">{website.name || website.domain}</h1>
          <p className="text-muted-foreground font-mono text-sm">{siteUrl}</p>
        </div>
        <div className="flex items-center gap-2 mt-2 shrink-0">
          <Badge
            variant={
              website.status === "critical" ? "destructive" :
                website.status === "warning" ? "warning" :
                  website.status === "active" ? "success" : "secondary"
            }
            className="text-sm px-3 py-1"
          >
            {website.status}
          </Badge>
          <VipToggleButton websiteId={id} initialIsVip={website.is_vip ?? false} />
          <Button asChild variant="outline" size="sm">
            <a href={siteUrl} target="_blank" rel="noopener noreferrer">
              <ExternalLink className="h-3.5 w-3.5 mr-1.5" />
              Visit
            </a>
          </Button>
          <SiteLoginButton
            websiteId={id}
            wpSsoConfigured={website.wp_sso_configured ?? false}
          />
          <RefreshDomainButton websiteId={id} label="Run check" variant="default" runFullCheck />
        </div>
      </div>

      {/* defaultValue (from ?tab=) sets the initial tab for deep-links; switching
          is handled client-side by Radix so it's instant — no server navigation. */}
      <Tabs key={tab} defaultValue={tab}>
        <TabsList className="flex-wrap h-auto gap-1">
          <TabsTrigger value="overview">Overview</TabsTrigger>
          {/* Counts distinct third-party domains, matching the rows the table
              renders from the same array — not raw Script records. Three files
              from googletagmanager.com are one service, and counting files made
              the badge read 9 next to a 7-row table. */}
          <TabsTrigger value="scripts">Scripts ({countScriptDomains(scriptsForTab)})</TabsTrigger>
          {showPlugins && <TabsTrigger value="plugins">Plugins</TabsTrigger>}
          <TabsTrigger value="forms">Forms ({managedFormCount})</TabsTrigger>
          <TabsTrigger value="uptime">Uptime &amp; Downtime {monitors.length > 0 ? `(${monitors.length})` : ""}</TabsTrigger>
          <TabsTrigger value="access">Access & Domain</TabsTrigger>
          <TabsTrigger value="performance">Performance</TabsTrigger>
          <TabsTrigger value="changelog">Change Log ({changeLog.length})</TabsTrigger>
          {showPhpErrors && <TabsTrigger value="php-errors">PHP Errors ({phpErrors.length})</TabsTrigger>}
          <TabsTrigger value="seo">SEO</TabsTrigger>
          <TabsTrigger value="reports">Reports</TabsTrigger>
          <TabsTrigger value="setup">
            <Settings className="h-3.5 w-3.5 mr-1" />Setup
          </TabsTrigger>
        </TabsList>

        {/* ── Overview ── */}
        {/* Overview is a hub: one chunk per area of the site, each a Radix
            trigger that opens its own tab. Replaces the old scoring breakdown,
            pending-changes table and top-scripts table, all of which duplicated
            what their own tabs already show. */}
        <TabsContent value="overview" className="space-y-4">
          <SiteOverviewGrid m={overviewMetrics} websiteId={id} />

          {/* The score needs explaining somewhere, and this is the only place it
              appears. Collapsed so it informs without occupying the page. */}
          <details className="rounded-xl border bg-card px-4 py-3 text-sm">
            <summary className="cursor-pointer font-medium">How the health score is worked out</summary>
            <div className="mt-3">
              <HealthScoreInfo
                healthScore={website.health_score ?? 100}
                status={website.status}
                pendingChanges={pendingChanges}
                domainInfo={domainInfo}
                vulns={vulns}
                websiteId={id}
              />
            </div>
          </details>
        </TabsContent>

        {/* ── Scripts ── */}
        <TabsContent value="scripts">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">
                Scripts ({countScriptDomains(scriptsForTab)}
                {scriptsForTab.length !== countScriptDomains(scriptsForTab) &&
                  ` · ${scriptsForTab.length} files`}
                )
              </CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              <ScriptsTab scripts={scriptsForTab} websiteId={id} />
            </CardContent>
          </Card>
        </TabsContent>

        {/* ── Plugins ── */}
        {showPlugins && (
          <TabsContent value="plugins">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">WordPress Plugins</CardTitle>
              </CardHeader>
              <CardContent className="p-0">
                <PluginsTab scripts={allActiveScripts} websiteId={id} />
              </CardContent>
            </Card>
          </TabsContent>
        )}

        {/* ── Forms ── */}
        <TabsContent value="forms" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Detected Forms</CardTitle>
            </CardHeader>
            <CardContent className="p-0 px-4 pb-4">
              <FormsTab forms={forms} formErrors={formErrors} />
            </CardContent>
          </Card>

          {formErrors.length === 0 ? (
            <Card className="border-emerald-200 dark:border-emerald-900">
              <CardContent className="py-4 flex items-center gap-2 text-sm text-muted-foreground">
                <CheckCircle className="h-4 w-4 text-emerald-500 shrink-0" />
                No form submission errors detected.
              </CardContent>
            </Card>
          ) : (
            <Card className="border-red-200 dark:border-red-900">
              <CardHeader>
                <CardTitle className="text-base flex items-center gap-2">
                  <AlertTriangle className="h-4 w-4 text-red-500" />
                  Form Errors ({formErrors.length})
                </CardTitle>
              </CardHeader>
              <CardContent className="p-0">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Source</TableHead>
                      <TableHead>Message</TableHead>
                      <TableHead>Page</TableHead>
                      <TableHead>When</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {formErrors.slice(0, 25).map((err) => (
                      <TableRow key={err.id}>
                        <TableCell className="whitespace-nowrap">
                          <Badge variant="destructive" className="text-xs">{err.source || "unknown"}</Badge>
                          {err.form_id && <span className="block text-[10px] font-mono text-muted-foreground mt-0.5">#{err.form_id}</span>}
                        </TableCell>
                        <TableCell className="text-sm max-w-md">{err.message}</TableCell>
                        <TableCell className="font-mono text-xs text-muted-foreground max-w-[200px] truncate" title={err.page_url}>
                          {err.page_url.replace(/^https?:\/\/[^/]+/, "") || "/"}
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground whitespace-nowrap">{fmtDate(err.created_at)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          )}
        </TabsContent>

        {/* ── Access & Domain ── */}
        <TabsContent value="access" className="space-y-4">
          {domainInfo ? (
            <div className="grid md:grid-cols-2 gap-4">
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm flex items-center gap-2">
                    <Globe className="h-4 w-4" />
                    Domain Registration
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <InfoRow label="Registrar" value={domainInfo.registrar} />
                  <InfoRow label="Registered" value={fmtDate(domainInfo.registered_at)} />
                  <InfoRow label="Expires" value={fmtDate(domainInfo.expires_at)} highlight={isExpiringSoon(domainInfo.expires_at)} />
                  <InfoRow label="Auto-renew" value={domainInfo.auto_renew ? "Yes" : "No"} />
                  <InfoRow label="WHOIS Privacy" value={domainInfo.whois_privacy ? "Enabled" : "Disabled"} />
                  {domainInfo.nameservers?.length > 0 && (
                    <div className="flex justify-between gap-2 py-0.5">
                      <span className="text-muted-foreground text-sm shrink-0">Nameservers</span>
                      <span className="text-right text-xs font-mono truncate">{domainInfo.nameservers.join(", ")}</span>
                    </div>
                  )}
                </CardContent>
              </Card>
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm flex items-center gap-2">
                    <Shield className="h-4 w-4" />
                    Hosting & SSL
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <InfoRow label="Host" value={domainInfo.hosting_provider} />
                  <InfoRow label="Server IP" value={domainInfo.hosting_ip} />
                  <InfoRow label="Location" value={domainInfo.server_location} />
                  <InfoRow label="Cloudflare" value={domainInfo.uses_cloudflare ? "Yes" : "No"} />
                  <InfoRow label="SSL Issuer" value={domainInfo.ssl_issuer} />
                  <InfoRow label="SSL Expires" value={fmtDate(domainInfo.ssl_expires_at)} highlight={isExpiringSoon(domainInfo.ssl_expires_at)} />
                  {/* Hosting expiry is never auto-detected — someone types it on
                      the client record. Prefer that over the mirrored copy on
                      DomainInfo, which only updates when the client is saved and
                      so can fall behind. */}
                  <InfoRow
                    label="Hosting Expires"
                    value={fmtDate(website.client_hosting_renewal_date ?? domainInfo.hosting_expires_at)}
                    highlight={isExpiringSoon(website.client_hosting_renewal_date ?? domainInfo.hosting_expires_at)}
                    note={website.client_hosting_renewal_date ? "from client" : undefined}
                  />
                  {domainInfo.last_checked_at && (
                    <InfoRow label="Last checked" value={fmtDateTime(domainInfo.last_checked_at)} />
                  )}

                  {/* Email authentication. Deliverability is a real support cost
                      for an agency, and SPF/DMARC gaps are invisible until mail
                      starts bouncing. */}
                  <div className="mt-3 border-t pt-2">
                    <p className="mb-1 text-xs font-semibold text-muted-foreground">Email authentication</p>
                    <AuthRow label="SPF" status={domainInfo.spf_status} detail={domainInfo.spf_record} />
                    <AuthRow label="DKIM" status={domainInfo.dkim_status} detail={domainInfo.dkim_selector} />
                    <AuthRow label="DMARC" status={domainInfo.dmarc_status} detail={domainInfo.dmarc_record} />
                  </div>
                </CardContent>
              </Card>
              <Card className="md:col-span-2">
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm flex items-center gap-2">
                    <Bell className="h-4 w-4" />
                    Alerts & Status Page
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <WebsiteAlertsStatus
                    websiteId={id}
                    initialChannelId={website.notification_channel}
                    statusPage={website.status_page}
                  />
                  <div className="border-t mt-4 pt-4">
                    <WebsiteAssignments websiteId={id} />
                  </div>
                </CardContent>
              </Card>
              <div className="md:col-span-2 flex justify-end">
                <RefreshDomainButton websiteId={id} />
              </div>
            </div>
          ) : (
            <Card>
              <CardContent className="py-12 flex flex-col items-center gap-3 text-center">
                <Globe className="h-10 w-10 text-muted-foreground" />
                <p className="font-medium">No domain data yet</p>
                <p className="text-sm text-muted-foreground">Click below to fetch WHOIS, hosting, and SSL info for this domain.</p>
                <RefreshDomainButton websiteId={id} />
              </CardContent>
            </Card>
          )}
        </TabsContent>


        {/* ── Performance ── */}
        <TabsContent value="performance">
          <PerformanceTab
            websiteId={id}
            mobileReports={mobileReports}
            desktopReports={desktopReports}
            cruxReports={cruxReports}
          />
        </TabsContent>

        {/* ── Change Log ── */}
        <TabsContent value="changelog">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Change Log ({changeLog.length})</CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              {changeLog.length === 0 ? (
                <div className="p-10 flex flex-col items-center gap-2 text-center">
                  <CheckCircle className="h-10 w-10 text-emerald-500" />
                  <p className="font-medium">No changes detected</p>
                  <p className="text-sm text-muted-foreground">
                    Digivault will alert you when scripts are added, removed or modified, when a
                    plugin, theme or WordPress core is updated, and when a new page appears.
                  </p>
                </div>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-[5px] p-0" />
                      <TableHead>Severity</TableHead>
                      <TableHead>Type</TableHead>
                      <TableHead>Script</TableHead>
                      <TableHead>Description</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Detected</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {changeLog.map((entry) =>
                      entry.kind === "script" ? (
                      <TableRow key={entry.id} className={`border-l-4 ${SEV_STRIPE[entry.change.severity] ?? "border-l-transparent"}`}>
                        <TableCell className="p-0" />
                        <TableCell><Badge variant={severityVariant(entry.change.severity)} className="capitalize">{entry.change.severity}</Badge></TableCell>
                        <TableCell className="capitalize font-medium text-sm">{entry.change.change_type}</TableCell>
                        <TableCell className="font-mono text-xs max-w-[200px]" title={entry.change.script?.src_url}>
                          {entry.change.script?.src_url ? smartUrl(entry.change.script.src_url) : "—"}
                        </TableCell>
                        <TableCell className="text-sm text-muted-foreground max-w-[200px] truncate">{entry.change.description}</TableCell>
                        <TableCell>
                          {entry.change.is_acknowledged ? (
                            <span className="flex items-center gap-1 text-xs text-emerald-600">
                              <CheckCircle className="h-3 w-3" /> Acknowledged
                              {entry.change.acknowledged_by_email && (
                                <span className="text-muted-foreground">
                                  by {entry.change.acknowledged_by_email.split("@")[0]}
                                </span>
                              )}
                            </span>
                          ) : (
                            <span className="text-xs text-amber-600">Pending</span>
                          )}
                        </TableCell>
                        <TableCell className="text-sm text-muted-foreground whitespace-nowrap">{fmtDate(entry.change.created_at)}</TableCell>
                      </TableRow>
                      ) : (
                      /* Site events (plugin/theme/core updated, new page) have no
                         script and nothing to acknowledge — they are observations,
                         not pending decisions. */
                      <TableRow key={entry.id} className={`border-l-4 ${SEV_STRIPE[entry.event.severity] ?? "border-l-transparent"}`}>
                        <TableCell className="p-0" />
                        <TableCell><Badge variant={severityVariant(entry.event.severity)} className="capitalize">{entry.event.severity}</Badge></TableCell>
                        <TableCell className="capitalize font-medium text-sm">
                          {entry.event.event_type.replace(/_/g, " ")}
                        </TableCell>
                        <TableCell className="text-muted-foreground">—</TableCell>
                        <TableCell className="text-sm text-muted-foreground max-w-[200px] truncate" title={entry.event.summary}>
                          {entry.event.summary}
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">—</TableCell>
                        <TableCell className="text-sm text-muted-foreground whitespace-nowrap">{fmtDate(entry.event.occurred_at)}</TableCell>
                      </TableRow>
                      )
                    )}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>

          {/* Who did what on this site — the human side of the change log. */}
          {siteActivity.length > 0 && (
            <Card className="mt-4">
              <CardHeader>
                <CardTitle className="text-base">User Activity ({siteActivity.length})</CardTitle>
              </CardHeader>
              <CardContent className="p-0">
                <Table>
                  <TableBody>
                    {siteActivity.slice(0, 15).map((entry) => (
                      <TableRow key={entry.id}>
                        <TableCell className="text-sm font-medium whitespace-nowrap">
                          {entry.actor_name || entry.actor_email || "System"}
                        </TableCell>
                        <TableCell className="text-sm text-muted-foreground">{entry.description}</TableCell>
                        <TableCell className="text-xs text-muted-foreground whitespace-nowrap text-right">
                          {fmtDateTime(entry.created_at)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          )}
        </TabsContent>


        {/* ── PHP Errors ── */}
        {showPhpErrors && (
          <TabsContent value="php-errors">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">PHP Error Log</CardTitle>
              </CardHeader>
              <CardContent className="p-0 px-4 pb-4">
                <PhpErrorsTab errors={phpErrors} />
              </CardContent>
            </Card>
          </TabsContent>
        )}

        {/* Site events are folded into the Change Log above rather than living
            in their own tab — see the changeLog timeline. */}

        {/* JS Errors had a tab here. Withdrawn from the UI — collection, the
            JsError model and /js-errors/ are untouched, so restoring it is just
            re-adding the trigger and panel. */}

        {/* ── Uptime ── */}
        <TabsContent value="uptime">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Uptime & Downtime</CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              <UptimeTab monitors={monitors} websiteId={id} statusPage={website.status_page} />
            </CardContent>
          </Card>
        </TabsContent>

        {/* ── SEO ── */}
        <TabsContent value="seo">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">SEO Health</CardTitle>
            </CardHeader>
            <CardContent className="px-4 pb-4">
              <SeoTab websiteId={id} report={seoReport} />
            </CardContent>
          </Card>
        </TabsContent>

        {/* ── Reports ── */}
        <TabsContent value="reports">
          <ReportsTab websiteId={id} />
        </TabsContent>

        {/* ── Setup ── */}
        <TabsContent value="setup" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Code className="h-4 w-4" />
                Tracking Snippet
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <p className="text-sm text-muted-foreground">
                Paste this in the <code className="bg-muted px-1 rounded">&lt;head&gt;</code> of every page you want to monitor.
              </p>
              <CopySnippet snippet={website.snippet_html ?? ""} siteId={website.site_id} />
              <VerifySnippetButton websiteId={website.id} />
            </CardContent>
          </Card>
          {website.last_seen_at && (
            <p className="text-xs text-muted-foreground px-1">
              Last data received: {fmtDateTime(website.last_seen_at)}
            </p>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
