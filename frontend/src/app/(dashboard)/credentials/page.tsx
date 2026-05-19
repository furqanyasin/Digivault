import { getAccessToken } from "@/lib/server-token";
import { api } from "@/lib/api";
import type { Website, Credential } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { KeyRound, ExternalLink, Lock } from "lucide-react";
import Link from "next/link";
import { Button } from "@/components/ui/button";

const TYPE_COLORS: Record<string, string> = {
  wordpress:  "bg-blue-50 text-blue-700 border-blue-200",
  cpanel:     "bg-orange-50 text-orange-700 border-orange-200",
  godaddy:    "bg-green-50 text-green-700 border-green-200",
  cloudflare: "bg-amber-50 text-amber-700 border-amber-200",
  ftp:        "bg-purple-50 text-purple-700 border-purple-200",
  shopify:    "bg-emerald-50 text-emerald-700 border-emerald-200",
};

const CREDENTIAL_TYPE_LABELS: Record<string, string> = {
  wordpress: "WordPress Admin", cpanel: "cPanel", godaddy: "GoDaddy",
  namecheap: "Namecheap", hostinger: "Hostinger", cloudflare: "Cloudflare",
  ftp: "FTP / SFTP", wix: "Wix", webflow: "Webflow", shopify: "Shopify", custom: "Custom",
};

export default async function CredentialsPage() {
  const token = await getAccessToken();
  let websites: Website[] = [];
  try {
    websites = await api.get<Website[]>("/api/v1/websites/", token ?? "");
  } catch { /* ignore */ }

  // Fetch credentials for each site in parallel
  const credsByWebsite: Record<string, Credential[]> = {};
  if (websites.length > 0) {
    const results = await Promise.allSettled(
      websites.map((s) => api.get<Credential[]>(`/api/v1/websites/${s.id}/credentials/`, token ?? ""))
    );
    results.forEach((r, i) => {
      credsByWebsite[websites[i].id] = r.status === "fulfilled" ? r.value : [];
    });
  }

  const totalCreds = Object.values(credsByWebsite).reduce((sum, arr) => sum + arr.length, 0);
  const sitesWithCreds = websites.filter((s) => (credsByWebsite[s.id]?.length ?? 0) > 0);
  const sitesWithout = websites.filter((s) => (credsByWebsite[s.id]?.length ?? 0) === 0);

  return (
    <div className="p-8 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Credentials</h1>
          <p className="text-muted-foreground mt-1">Securely stored logins — managed per website</p>
        </div>
        <div className="text-right">
          <p className="text-2xl font-bold">{totalCreds}</p>
          <p className="text-xs text-muted-foreground">total stored</p>
        </div>
      </div>

      {websites.length === 0 ? (
        <div className="border rounded-xl py-16 flex flex-col items-center gap-3 text-center">
          <KeyRound className="h-10 w-10 text-muted-foreground opacity-40" />
          <p className="font-medium">No websites yet</p>
          <p className="text-sm text-muted-foreground">Add a website first, then manage its credentials from the site detail page.</p>
          <Link href="/websites/new">
            <Button variant="outline" size="sm" className="mt-1">Add website</Button>
          </Link>
        </div>
      ) : (
        <div className="space-y-6">
          {/* Sites with credentials */}
          {sitesWithCreds.length > 0 && (
            <div className="space-y-3">
              <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">Stored credentials</h2>
              <div className="space-y-3">
                {sitesWithCreds.map((site) => {
                  const creds = credsByWebsite[site.id] ?? [];
                  return (
                    <div key={site.id} className="border rounded-lg overflow-hidden">
                      {/* Site header */}
                      <div className="flex items-center gap-3 px-4 py-2.5 bg-muted/30 border-b">
                        <Lock className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                        <span className="font-semibold text-sm">{site.name || site.domain}</span>
                        <span className="text-xs text-muted-foreground font-mono">{site.domain}</span>
                        <Badge
                          variant={site.status === "critical" ? "destructive" : site.status === "warning" ? "warning" : site.status === "active" ? "success" : "secondary"}
                          className="ml-auto text-xs"
                        >
                          {site.status}
                        </Badge>
                        <Link href={`/websites/${site.id}?tab=credentials`}>
                          <Button size="sm" variant="ghost" className="h-7 px-2 text-xs gap-1">
                            <ExternalLink className="h-3 w-3" />Manage
                          </Button>
                        </Link>
                      </div>
                      {/* Credential rows */}
                      <div className="divide-y">
                        {creds.map((cred) => {
                          const colorClass = TYPE_COLORS[cred.credential_type] ?? "bg-slate-50 text-slate-600 border-slate-200";
                          const typeLabel = CREDENTIAL_TYPE_LABELS[cred.credential_type] ?? cred.credential_type;
                          return (
                            <div key={cred.id} className="flex items-center gap-3 px-4 py-2">
                              <span className={`shrink-0 text-xs font-medium px-2 py-0.5 rounded-full border ${colorClass}`}>
                                {typeLabel}
                              </span>
                              <span className="text-sm font-medium flex-1 truncate">{cred.label}</span>
                              {cred.login_url && (
                                <a
                                  href={cred.login_url}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="text-xs text-muted-foreground hover:text-foreground font-mono truncate max-w-[200px] hidden sm:block"
                                >
                                  {cred.login_url.replace(/^https?:\/\//, "")}
                                </a>
                              )}
                              <span className="text-xs text-muted-foreground shrink-0">••••••••</span>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Sites without credentials */}
          {sitesWithout.length > 0 && (
            <div className="space-y-3">
              <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">No credentials yet</h2>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                {sitesWithout.map((site) => (
                  <div key={site.id} className="border rounded-lg px-4 py-3 flex items-center gap-3">
                    <Lock className="h-4 w-4 text-muted-foreground/40 shrink-0" />
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate">{site.name || site.domain}</p>
                      <p className="text-xs text-muted-foreground font-mono truncate">{site.domain}</p>
                    </div>
                    <Link href={`/websites/${site.id}?tab=credentials`}>
                      <Button size="sm" variant="outline" className="h-7 px-2 text-xs shrink-0">Add</Button>
                    </Link>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
