import Link from "next/link";
import { ArrowLeft, AlertTriangle, CheckCircle, Clock, Code, Globe, Lock, Shield } from "lucide-react";
import { getAccessToken } from "@/lib/server-token";
import { api } from "@/lib/api";
import type { Website, Script, ScriptChange, Credential, DomainInfo, PerformanceReport, CruxReport } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { CopySnippet } from "@/components/copy-snippet";
import { AcknowledgeButton } from "@/components/acknowledge-button";
import { CredentialsTab } from "@/components/credentials-tab";
import { RefreshDomainButton } from "@/components/refresh-domain-button";
import { PerformanceTab } from "@/components/performance-tab";
import { ScriptReviewButton } from "@/components/script-review-button";
import { VerifySnippetButton } from "@/components/verify-snippet-button";
import { ScriptsTab } from "@/components/scripts-tab";
import { PluginsTab } from "@/components/plugins-tab";

async function getData(token: string, id: string) {
  const [website, scripts, changes, credentials, domain, perfMobile, perfDesktop, crux] = await Promise.allSettled([
    api.get<Website>(`/api/v1/websites/${id}/`, token),
    api.get<Script[]>(`/api/v1/websites/${id}/scripts/`, token),
    api.get<ScriptChange[]>(`/api/v1/websites/${id}/changes/`, token),
    api.get<Credential[]>(`/api/v1/websites/${id}/credentials/`, token),
    api.get<DomainInfo | null>(`/api/v1/websites/${id}/domain/`, token),
    api.get<PerformanceReport[]>(`/api/v1/websites/${id}/performance/?strategy=mobile&limit=30`, token),
    api.get<PerformanceReport[]>(`/api/v1/websites/${id}/performance/?strategy=desktop&limit=30`, token),
    api.get<CruxReport[]>(`/api/v1/websites/${id}/crux/`, token),
  ]);
  return {
    website: website.status === "fulfilled" ? website.value : null,
    scripts: scripts.status === "fulfilled" ? scripts.value : [],
    changes: changes.status === "fulfilled" ? changes.value : [],
    credentials: credentials.status === "fulfilled" ? credentials.value : [],
    domainInfo: domain.status === "fulfilled" ? domain.value : null,
    mobileReports: perfMobile.status === "fulfilled" ? perfMobile.value : [],
    desktopReports: perfDesktop.status === "fulfilled" ? perfDesktop.value : [],
    cruxReports: crux.status === "fulfilled" ? crux.value : [],
  };
}

function severityVariant(s: string): "destructive" | "warning" | "secondary" {
  if (s === "high" || s === "critical") return "destructive";
  if (s === "medium") return "warning";
  return "secondary";
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
  const { website, scripts, changes, credentials, domainInfo, mobileReports, desktopReports, cruxReports } = await getData(token ?? "", id);

  if (!website) {
    return (
      <div className="p-8">
        <p className="text-muted-foreground">Website not found or failed to load.</p>
      </div>
    );
  }

  const activeScripts = scripts.filter((s) => s.is_active);
  const pendingChanges = changes.filter((c) => !c.is_acknowledged);
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

      {/* Stats row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        {[
          { icon: Code, value: activeScripts.length, label: "Active scripts", color: "text-blue-500" },
          { icon: Clock, value: pendingChanges.length, label: "Pending changes", color: "text-amber-500" },
          { icon: AlertTriangle, value: unknownScripts.length, label: "Unknown scripts", color: "text-red-500" },
          { icon: Lock, value: credentials.length, label: "Saved credentials", color: "text-emerald-500" },
        ].map(({ icon: Icon, value, label, color }) => (
          <Card key={label}>
            <CardContent className="flex items-center gap-3 py-4">
              <Icon className={`h-7 w-7 ${color} shrink-0`} />
              <div>
                <p className="text-2xl font-bold">{value}</p>
                <p className="text-xs text-muted-foreground">{label}</p>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Tabs - using defaultValue driven by URL searchParam */}
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
          <TabsTrigger value="access" asChild>
            <Link href={`/websites/${id}?tab=access`} prefetch>Access & Domain</Link>
          </TabsTrigger>
          <TabsTrigger value="credentials" asChild>
            <Link href={`/websites/${id}?tab=credentials`} prefetch>Credentials ({credentials.length})</Link>
          </TabsTrigger>
          <TabsTrigger value="performance" asChild>
            <Link href={`/websites/${id}?tab=performance`} prefetch>Performance</Link>
          </TabsTrigger>
          <TabsTrigger value="changelog" asChild>
            <Link href={`/websites/${id}?tab=changelog`} prefetch>Change Log ({changes.length})</Link>
          </TabsTrigger>
        </TabsList>

        {/* ── Overview ── */}
        <TabsContent value="overview" className="space-y-6">
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

          <Card>
            <CardHeader>
              <CardTitle className="text-base">
                Pending Changes {pendingChanges.length > 0 && `(${pendingChanges.length})`}
              </CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              {pendingChanges.length === 0 ? (
                <div className="p-8 flex flex-col items-center gap-2 text-center">
                  <CheckCircle className="h-8 w-8 text-emerald-500" />
                  <p className="font-medium text-sm">No pending changes</p>
                  <p className="text-xs text-muted-foreground">All changes have been acknowledged</p>
                </div>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Type</TableHead>
                      <TableHead>Script</TableHead>
                      <TableHead>Severity</TableHead>
                      <TableHead>Detected</TableHead>
                      <TableHead />
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {pendingChanges.slice(0, 5).map((change) => (
                      <TableRow key={change.id}>
                        <TableCell className="capitalize font-medium text-sm">{change.change_type}</TableCell>
                        <TableCell className="font-mono text-xs max-w-[180px] truncate">{change.script?.src_url ?? "—"}</TableCell>
                        <TableCell><Badge variant={severityVariant(change.severity)}>{change.severity}</Badge></TableCell>
                        <TableCell className="text-sm text-muted-foreground">{new Date(change.created_at).toLocaleDateString()}</TableCell>
                        <TableCell><AcknowledgeButton changeId={change.id} /></TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>

          {activeScripts.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Top Scripts</CardTitle>
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
                        <TableCell className="font-mono text-xs max-w-[280px] truncate text-muted-foreground">{script.src_url}</TableCell>
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
              <PluginsTab scripts={activeScripts} websiteId={id} />
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
                  <InfoRow label="Registered" value={domainInfo.registered_at ? new Date(domainInfo.registered_at).toLocaleDateString() : null} />
                  <InfoRow label="Expires" value={domainInfo.expires_at ? new Date(domainInfo.expires_at).toLocaleDateString() : null} highlight={isExpiringSoon(domainInfo.expires_at)} />
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
                  <InfoRow label="SSL Expires" value={domainInfo.ssl_expires_at ? new Date(domainInfo.ssl_expires_at).toLocaleDateString() : null} highlight={isExpiringSoon(domainInfo.ssl_expires_at)} />
                  {domainInfo.last_checked_at && (
                    <InfoRow label="Last checked" value={new Date(domainInfo.last_checked_at).toLocaleString()} />
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

        {/* ── Credentials ── */}
        <TabsContent value="credentials">
          <CredentialsTab websiteId={id} initialCredentials={credentials} />
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
              {changes.length === 0 ? (
                <div className="p-10 flex flex-col items-center gap-2 text-center">
                  <CheckCircle className="h-10 w-10 text-emerald-500" />
                  <p className="font-medium">No changes detected</p>
                  <p className="text-sm text-muted-foreground">Digivault will alert you when scripts are added, removed, or modified.</p>
                </div>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Severity</TableHead>
                      <TableHead>Type</TableHead>
                      <TableHead>Script</TableHead>
                      <TableHead>Description</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Detected</TableHead>
                      <TableHead />
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {changes.map((change) => (
                      <TableRow key={change.id}>
                        <TableCell><Badge variant={severityVariant(change.severity)}>{change.severity}</Badge></TableCell>
                        <TableCell className="capitalize font-medium text-sm">{change.change_type}</TableCell>
                        <TableCell className="font-mono text-xs max-w-[160px] truncate">{change.script?.src_url ?? "—"}</TableCell>
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
                        <TableCell className="text-sm text-muted-foreground">{new Date(change.created_at).toLocaleDateString()}</TableCell>
                        <TableCell>
                          {!change.is_acknowledged && <AcknowledgeButton changeId={change.id} />}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
