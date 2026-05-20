import Link from "next/link";
import { ArrowLeft, AlertTriangle, CheckCircle, Clock, Code, Globe, Lock, Shield, Settings } from "lucide-react";
import { getAccessToken } from "@/lib/server-token";
import { api } from "@/lib/api";
import type { Website, Script, ScriptChange, DomainInfo, PerformanceReport, CruxReport, DetectedForm, PhpError, SiteEvent, VulnerabilityReport, SiteScanState } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { CopySnippet } from "@/components/copy-snippet";
import { RefreshDomainButton } from "@/components/refresh-domain-button";
import { PerformanceTab } from "@/components/performance-tab";
import { ScriptReviewButton } from "@/components/script-review-button";
import { VerifySnippetButton } from "@/components/verify-snippet-button";
import { ScriptsTab } from "@/components/scripts-tab";
import { PluginsTab } from "@/components/plugins-tab";
import { FormsTab } from "@/components/forms-tab";
import { PhpErrorsTab } from "@/components/php-errors-tab";
import { SiteEventsTab } from "@/components/site-events-tab";
import { SecurityTab } from "@/components/security-tab";
import { BulkPendingChanges } from "@/components/bulk-pending-changes";
import { fmtDate, fmtDateTime } from "@/lib/utils";

async function getData(token: string, id: string) {
  const [website, scripts, changes, domain, perfMobile, perfDesktop, crux, forms, phpErrors, siteEvents, vulns, scanState] = await Promise.allSettled([
    api.get<Website>(`/api/v1/websites/${id}/`, token),
    api.get<Script[]>(`/api/v1/websites/${id}/scripts/`, token),
    api.get<ScriptChange[]>(`/api/v1/websites/${id}/changes/`, token),
    api.get<DomainInfo | null>(`/api/v1/websites/${id}/domain/`, token),
    api.get<PerformanceReport[]>(`/api/v1/websites/${id}/performance/?strategy=mobile&limit=30`, token),
    api.get<PerformanceReport[]>(`/api/v1/websites/${id}/performance/?strategy=desktop&limit=30`, token),
    api.get<CruxReport[]>(`/api/v1/websites/${id}/crux/`, token),
    api.get<DetectedForm[]>(`/api/v1/websites/${id}/forms/`, token),
    api.get<PhpError[]>(`/api/v1/websites/${id}/php-errors/`, token),
    api.get<SiteEvent[]>(`/api/v1/websites/${id}/events/`, token),
    api.get<VulnerabilityReport[]>(`/api/v1/websites/${id}/vulnerabilities/`, token),
    api.get<SiteScanState>(`/api/v1/websites/${id}/scan/`, token),
  ]);
  return {
    website: website.status === "fulfilled" ? website.value : null,
    scripts: scripts.status === "fulfilled" ? scripts.value : [],
    changes: changes.status === "fulfilled" ? changes.value : [],
    domainInfo: domain.status === "fulfilled" ? domain.value : null,
    mobileReports: perfMobile.status === "fulfilled" ? perfMobile.value : [],
    desktopReports: perfDesktop.status === "fulfilled" ? perfDesktop.value : [],
    cruxReports: crux.status === "fulfilled" ? crux.value : [],
    forms: forms.status === "fulfilled" ? forms.value : [],
    phpErrors: phpErrors.status === "fulfilled" ? phpErrors.value : [],
    siteEvents: siteEvents.status === "fulfilled" ? siteEvents.value : [],
    vulns: vulns.status === "fulfilled" ? vulns.value : [],
    scanState: scanState.status === "fulfilled" ? scanState.value : null,
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

function providerVariant(p: string): "destructive" | "outline" {
  return p === "unknown" ? "destructive" : "outline";
}

function isExpiringSoon(date: string | number | null | undefined): boolean {
  if (!date) return false;
  if (typeof date === "number") return date > 0 && date <= 30;
  const diff = new Date(date).getTime() - Date.now();
  return diff > 0 && diff < 30 * 24 * 60 * 60 * 1000;
}

function InfoRow({ label, value, highlight }: { label: string; value: string | null | undefined; highlight?: boolean }) {
  return (
    <div className="flex justify-between gap-2 py-0.5">
      <span className="text-muted-foreground text-sm shrink-0">{label}</span>
      <span className={`text-right text-sm truncate font-mono text-xs ${highlight ? "text-amber-600 font-semibold" : ""}`}>
        {value || "—"}
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
  const { tab = "overview" } = await searchParams;
  const token = await getAccessToken();
  const { website, scripts, changes, domainInfo, mobileReports, desktopReports, cruxReports, forms, phpErrors, siteEvents, vulns, scanState } = await getData(token ?? "", id);

  if (!website) {
    return (
      <div className="p-8">
        <p className="text-muted-foreground">Website not found or failed to load.</p>
      </div>
    );
  }

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
  // Plugins tab: needs digilaticsvps scripts to detect WP plugins
  const allActiveScripts = scripts.filter((s) => s.is_active);

  const visibleChanges = changes.filter((c) => !isInternalChange(c));
  const pendingChanges = visibleChanges.filter((c) => !c.is_acknowledged);
  const unknownScripts = activeScripts.filter((s) => s.provider === "unknown");

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
          <p className="text-muted-foreground font-mono text-sm">{website.domain}</p>
        </div>
        <Badge
          variant={
            website.status === "critical" ? "destructive" :
              website.status === "warning" ? "warning" :
                website.status === "active" ? "success" : "secondary"
          }
          className="text-sm px-3 py-1 mt-2"
        >
          {website.status}
        </Badge>
      </div>

      {/* Stats row — clickable cards jump to filtered tabs */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <Link href={`/websites/${id}?tab=scripts`}>
          <Card className="hover:border-blue-400 border-l-4 border-l-blue-400 transition-colors cursor-pointer">
            <CardContent className="flex items-center gap-3 py-4">
              <Code className="h-7 w-7 text-blue-500 shrink-0" />
              <div>
                <p className="text-2xl font-bold">{activeScripts.length}</p>
                <p className="text-xs text-muted-foreground">Active scripts</p>
              </div>
            </CardContent>
          </Card>
        </Link>
        <Link href={`/websites/${id}?tab=overview`}>
          <Card className={`border-l-4 transition-colors cursor-pointer ${pendingChanges.length > 0 ? "border-l-amber-400 hover:border-amber-500 bg-amber-50/40 dark:bg-amber-950/20" : "border-l-slate-200 dark:border-l-slate-700"}`}>
            <CardContent className="flex items-center gap-3 py-4">
              <Clock className={`h-7 w-7 shrink-0 ${pendingChanges.length > 0 ? "text-amber-500" : "text-muted-foreground"}`} />
              <div>
                <p className="text-2xl font-bold">{pendingChanges.length}</p>
                <p className="text-xs text-muted-foreground">Pending changes</p>
              </div>
            </CardContent>
          </Card>
        </Link>
        <Link href={`/websites/${id}?tab=scripts`}>
          <Card className={`border-l-4 transition-colors cursor-pointer ${unknownScripts.length > 0 ? "border-l-red-500 hover:border-red-600 bg-red-50/40 dark:bg-red-950/20" : "border-l-slate-200 dark:border-l-slate-700"}`}>
            <CardContent className="flex items-center gap-3 py-4">
              <AlertTriangle className={`h-7 w-7 shrink-0 ${unknownScripts.length > 0 ? "text-red-500" : "text-muted-foreground"}`} />
              <div>
                <p className="text-2xl font-bold">{unknownScripts.length}</p>
                <p className="text-xs text-muted-foreground">Unknown scripts</p>
              </div>
            </CardContent>
          </Card>
        </Link>
        <Link href="/credentials">
          <Card className="border-l-4 border-l-emerald-500 hover:border-emerald-600 transition-colors cursor-pointer">
            <CardContent className="flex items-center gap-3 py-4">
              <Lock className="h-7 w-7 text-emerald-500 shrink-0" />
              <div>
                <p className="text-2xl font-bold">Vault</p>
                <p className="text-xs text-muted-foreground">View credentials</p>
              </div>
            </CardContent>
          </Card>
        </Link>
      </div>

      <Tabs defaultValue={tab}>
        <TabsList className="flex-wrap h-auto gap-1">
          <TabsTrigger value="overview" asChild>
            <Link href={`/websites/${id}?tab=overview`} prefetch>Overview</Link>
          </TabsTrigger>
          <TabsTrigger value="scripts" asChild>
            <Link href={`/websites/${id}?tab=scripts`} prefetch>Scripts ({activeScripts.length})</Link>
          </TabsTrigger>
          <TabsTrigger value="plugins" asChild>
            <Link href={`/websites/${id}?tab=plugins`} prefetch>Plugins</Link>
          </TabsTrigger>
          <TabsTrigger value="forms" asChild>
            <Link href={`/websites/${id}?tab=forms`} prefetch>Forms ({forms.length})</Link>
          </TabsTrigger>
          <TabsTrigger value="access" asChild>
            <Link href={`/websites/${id}?tab=access`} prefetch>Access & Domain</Link>
          </TabsTrigger>
          <TabsTrigger value="performance" asChild>
            <Link href={`/websites/${id}?tab=performance`} prefetch>Performance</Link>
          </TabsTrigger>
          <TabsTrigger value="changelog" asChild>
            <Link href={`/websites/${id}?tab=changelog`} prefetch>Change Log ({visibleChanges.length})</Link>
          </TabsTrigger>
          <TabsTrigger value="php-errors" asChild>
            <Link href={`/websites/${id}?tab=php-errors`} prefetch>PHP Errors {phpErrors.length > 0 ? `(${phpErrors.length})` : ""}</Link>
          </TabsTrigger>
          <TabsTrigger value="site-events" asChild>
            <Link href={`/websites/${id}?tab=site-events`} prefetch>Site Events {siteEvents.length > 0 ? `(${siteEvents.length})` : ""}</Link>
          </TabsTrigger>
          <TabsTrigger value="security" asChild>
            <Link href={`/websites/${id}?tab=security`} prefetch>Security {vulns.length > 0 ? `(${vulns.length})` : ""}</Link>
          </TabsTrigger>
          <TabsTrigger value="setup" asChild>
            <Link href={`/websites/${id}?tab=setup`} prefetch>
              <Settings className="h-3.5 w-3.5 mr-1" />Setup
            </Link>
          </TabsTrigger>
        </TabsList>

        {/* ── Overview ── */}
        <TabsContent value="overview" className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="text-base flex items-center justify-between">
                <span>Pending Changes {pendingChanges.length > 0 && <span className="text-amber-500 ml-1">({pendingChanges.length})</span>}</span>
                {pendingChanges.length > 0 && (
                  <Link href={`/websites/${id}?tab=changelog`} className="text-xs font-normal text-muted-foreground hover:text-foreground">
                    View full log →
                  </Link>
                )}
              </CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              <BulkPendingChanges changes={pendingChanges.slice(0, 10)} websiteId={id} />
            </CardContent>
          </Card>

          {activeScripts.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base flex items-center justify-between">
                  Top Scripts
                  <Link href={`/websites/${id}?tab=scripts`} className="text-xs font-normal text-muted-foreground hover:text-foreground">
                    View all {activeScripts.length} →
                  </Link>
                </CardTitle>
              </CardHeader>
              <CardContent className="p-0">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Provider</TableHead>
                      <TableHead>Category</TableHead>
                      <TableHead>URL</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {activeScripts.slice(0, 7).map((script) => (
                      <TableRow key={script.id}>
                        <TableCell><Badge variant={providerVariant(script.provider)}>{script.provider}</Badge></TableCell>
                        <TableCell className="text-sm">{script.category || "—"}</TableCell>
                        <TableCell className="font-mono text-xs max-w-[280px] text-muted-foreground" title={script.src_url}>
                          {smartUrl(script.src_url)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          )}
        </TabsContent>

        {/* ── Scripts ── */}
        <TabsContent value="scripts">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Active Scripts ({activeScripts.length})</CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              <ScriptsTab scripts={activeScripts} websiteId={id} />
            </CardContent>
          </Card>
        </TabsContent>

        {/* ── Plugins ── */}
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

        {/* ── Forms ── */}
        <TabsContent value="forms">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Detected Forms ({forms.length})</CardTitle>
            </CardHeader>
            <CardContent className="p-0 px-4 pb-4">
              <FormsTab forms={forms} />
            </CardContent>
          </Card>
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
                  {domainInfo.last_checked_at && (
                    <InfoRow label="Last checked" value={fmtDateTime(domainInfo.last_checked_at)} />
                  )}
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
              <CardTitle className="text-base">Change Log ({changes.length})</CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              {visibleChanges.length === 0 ? (
                <div className="p-10 flex flex-col items-center gap-2 text-center">
                  <CheckCircle className="h-10 w-10 text-emerald-500" />
                  <p className="font-medium">No changes detected</p>
                  <p className="text-sm text-muted-foreground">Digivault will alert you when scripts are added, removed, or modified.</p>
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
                    {visibleChanges.map((change) => (
                      <TableRow key={change.id} className={`border-l-4 ${SEV_STRIPE[change.severity] ?? "border-l-transparent"}`}>
                        <TableCell className="p-0" />
                        <TableCell><Badge variant={severityVariant(change.severity)} className="capitalize">{change.severity}</Badge></TableCell>
                        <TableCell className="capitalize font-medium text-sm">{change.change_type}</TableCell>
                        <TableCell className="font-mono text-xs max-w-[200px]" title={change.script?.src_url}>
                          {change.script?.src_url ? smartUrl(change.script.src_url) : "—"}
                        </TableCell>
                        <TableCell className="text-sm text-muted-foreground max-w-[200px] truncate">{change.description}</TableCell>
                        <TableCell>
                          {change.is_acknowledged ? (
                            <span className="flex items-center gap-1 text-xs text-emerald-600">
                              <CheckCircle className="h-3 w-3" /> Acknowledged
                            </span>
                          ) : (
                            <span className="text-xs text-amber-600">Pending</span>
                          )}
                        </TableCell>
                        <TableCell className="text-sm text-muted-foreground whitespace-nowrap">{fmtDate(change.created_at)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </TabsContent>


        {/* ── PHP Errors ── */}
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

        {/* ── Site Events ── */}
        <TabsContent value="site-events">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Site Events</CardTitle>
            </CardHeader>
            <CardContent className="p-0 px-4 pb-4">
              <SiteEventsTab events={siteEvents} />
            </CardContent>
          </Card>
        </TabsContent>

        {/* ── Security ── */}
        <TabsContent value="security">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Security &amp; Vulnerability Scan</CardTitle>
            </CardHeader>
            <CardContent className="px-4 pb-4">
              <SecurityTab websiteId={id} vulns={vulns} scanState={scanState} />
            </CardContent>
          </Card>
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
