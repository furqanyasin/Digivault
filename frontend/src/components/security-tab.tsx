"use client";

import { useState } from "react";
import { ShieldAlert, ShieldCheck, RefreshCw, ExternalLink, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import type { Script, VulnerabilityReport, SiteScanState } from "@/lib/api";
import { fmtDateTime } from "@/lib/utils";

interface Props {
  websiteId: string;
  vulns: VulnerabilityReport[];
  scanState: SiteScanState | null;
  scripts?: Script[];
}

// Known WordPress security plugin slugs (matched against /wp-content/plugins/<slug>/)
// and their display names. Detection is passive — the snippet already reports
// these script URLs; no extra collection needed.
const SECURITY_PLUGINS: Record<string, string> = {
  "wordfence": "Wordfence",
  "sucuri-scanner": "Sucuri Security",
  "better-wp-security": "Solid Security (iThemes)",
  "all-in-one-wp-security-and-firewall": "All-In-One Security",
  "wp-cerber": "WP Cerber",
  "malcare-security": "MalCare",
  "wp-security-audit-log": "WP Activity Log",
  "wps-hide-login": "WPS Hide Login",
  "limit-login-attempts-reloaded": "Limit Login Attempts",
  "jetpack": "Jetpack (Protect)",
};

function detectSecurityPlugins(scripts: Script[]): { slug: string; name: string; wpPlugin: string }[] {
  const found = new Map<string, { slug: string; name: string; wpPlugin: string }>();
  for (const s of scripts) {
    const m = s.src_url.match(/\/wp-content\/plugins\/([^/]+)\//);
    const slug = m?.[1] ?? (s.wp_plugin || "");
    const key = slug.toLowerCase();
    if (key && SECURITY_PLUGINS[key] && !found.has(key)) {
      found.set(key, { slug: key, name: SECURITY_PLUGINS[key], wpPlugin: s.wp_plugin });
    }
  }
  return Array.from(found.values());
}

const SEV_CONFIG: Record<string, { label: string; className: string }> = {
  critical: { label: "Critical", className: "bg-red-100 text-red-800 border-red-300" },
  high:     { label: "High",     className: "bg-orange-100 text-orange-800 border-orange-300" },
  medium:   { label: "Medium",   className: "bg-amber-100 text-amber-800 border-amber-200" },
  low:      { label: "Low",      className: "bg-blue-50 text-blue-700 border-blue-200" },
};

const TYPE_LABEL: Record<string, string> = {
  plugin: "Plugin",
  theme:  "Theme",
  core:   "WP Core",
};

export function SecurityTab({ websiteId, vulns, scanState, scripts = [] }: Props) {
  const securityPlugins = detectSecurityPlugins(scripts);
  const [scanning, setScanning] = useState(false);
  const [state, setState] = useState<SiteScanState | null>(scanState);
  const [localVulns, setLocalVulns] = useState<VulnerabilityReport[]>(vulns);

  async function triggerScan() {
    setScanning(true);
    try {
      await fetch(`/api/websites/${websiteId}/scan`, { method: "POST" });
      // Poll until done
      let attempts = 0;
      const poll = async () => {
        attempts++;
        const res = await fetch(`/api/websites/${websiteId}/scan`);
        const data = await res.json();
        const s: SiteScanState = data?.data ?? data;
        setState(s);
        if (s.scan_status === "running" && attempts < 30) {
          setTimeout(poll, 2000);
        } else {
          // Refresh vulns
          const vRes = await fetch(`/api/websites/${websiteId}/vulnerabilities`);
          const vData = await vRes.json();
          setLocalVulns(vData?.data ?? vData ?? []);
          setScanning(false);
        }
      };
      setTimeout(poll, 1500);
    } catch {
      setScanning(false);
    }
  }

  const criticalCount = localVulns.filter((v) => v.severity === "critical").length;
  const highCount = localVulns.filter((v) => v.severity === "high").length;

  return (
    <div className="space-y-5">
      {/* Scan header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="font-medium text-sm">Security Scan</h3>
          <p className="text-xs text-muted-foreground mt-0.5">
            {state?.last_scanned_at
              ? `Last scanned ${fmtDateTime(state.last_scanned_at)}`
              : "Never scanned"}
            {state?.scan_status === "running" && " · Scan in progress…"}
            {state?.scan_status === "failed" && state.error && (
              <span className="text-red-600"> · {state.error}</span>
            )}
          </p>
          {state?.wp_version && (
            <p className="text-xs text-muted-foreground">
              WordPress {state.wp_version}
              {state.wp_update_available && state.wp_latest_version ? (
                <span className="ml-1.5 inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-amber-100 text-amber-800 font-medium">
                  <ShieldAlert className="h-3 w-3" /> Update available → {state.wp_latest_version}
                </span>
              ) : state.wp_latest_version ? (
                <span className="ml-1.5 text-emerald-600">· up to date</span>
              ) : null}
            </p>
          )}
        </div>
        <Button
          size="sm"
          variant="outline"
          onClick={triggerScan}
          disabled={scanning || state?.scan_status === "running"}
        >
          {scanning || state?.scan_status === "running" ? (
            <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
          ) : (
            <RefreshCw className="h-3.5 w-3.5 mr-1.5" />
          )}
          Run Scan
        </Button>
      </div>

      {/* Security plugins detected from page scripts */}
      <div className="rounded-lg border px-4 py-3">
        <div className="flex items-center gap-2 text-sm font-medium">
          <ShieldCheck className="h-4 w-4 text-muted-foreground" />
          Security plugins
        </div>
        {securityPlugins.length === 0 ? (
          <p className="text-xs text-muted-foreground mt-1">
            No security plugin detected from page scripts yet. Wordfence, Sucuri and
            similar plugins appear here automatically once their scripts load on a page.
          </p>
        ) : (
          <div className="flex flex-wrap gap-2 mt-2">
            {securityPlugins.map((p) => (
              <span
                key={p.slug}
                className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full border text-xs font-medium bg-emerald-50 text-emerald-800 border-emerald-200"
              >
                <ShieldCheck className="h-3 w-3" /> {p.name}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Summary badges */}
      {localVulns.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {criticalCount > 0 && (
            <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full border text-xs font-medium bg-red-100 text-red-800 border-red-300">
              <ShieldAlert className="h-3 w-3" /> {criticalCount} Critical
            </span>
          )}
          {highCount > 0 && (
            <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full border text-xs font-medium bg-orange-100 text-orange-800 border-orange-300">
              <ShieldAlert className="h-3 w-3" /> {highCount} High
            </span>
          )}
          <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full border text-xs font-medium bg-muted text-muted-foreground">
            {localVulns.length} total finding{localVulns.length !== 1 ? "s" : ""}
          </span>
        </div>
      )}

      {/* Vuln list */}
      {localVulns.length === 0 ? (
        <div className="py-12 flex flex-col items-center gap-3 text-center">
          <ShieldCheck className="h-10 w-10 text-emerald-500" />
          <p className="font-medium">
            {state?.scan_status === "never" || !state
              ? "No scan run yet"
              : "No vulnerabilities found"}
          </p>
          <p className="text-sm text-muted-foreground max-w-sm">
            {state?.scan_status === "never" || !state
              ? "Click Run Scan to check detected plugins for known CVEs."
              : "All detected plugins came back clean. Run a new scan any time."}
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {localVulns.map((v) => {
            const sev = SEV_CONFIG[v.severity] ?? SEV_CONFIG.medium;
            return (
              <div key={v.id} className="border rounded-lg px-4 py-3 space-y-1.5">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className={`inline-block px-2 py-0.5 rounded-full border text-xs font-semibold ${sev.className}`}>
                        {sev.label}
                      </span>
                      <span className="text-xs text-muted-foreground border rounded px-1.5 py-0.5">
                        {TYPE_LABEL[v.component_type] ?? v.component_type}
                      </span>
                      {v.source === "heuristic" && (
                        <span className="text-xs text-muted-foreground italic">(heuristic)</span>
                      )}
                    </div>
                    <p className="font-medium text-sm mt-1">{v.title}</p>
                    <p className="text-xs text-muted-foreground">
                      {v.component_name}
                      {v.component_version && ` v${v.component_version}`}
                      {v.fixed_in_version && ` · Fixed in ${v.fixed_in_version}`}
                    </p>
                  </div>
                </div>
                {v.description && (
                  <p className="text-xs text-muted-foreground">{v.description}</p>
                )}
                {v.cve_ids.length > 0 && (
                  <div className="flex flex-wrap gap-1">
                    {v.cve_ids.map((cve) => (
                      <span key={cve} className="font-mono text-xs bg-muted px-1.5 py-0.5 rounded">{cve}</span>
                    ))}
                  </div>
                )}
                {v.references.length > 0 && (
                  <div className="flex flex-wrap gap-2 pt-0.5">
                    {v.references.slice(0, 3).map((ref, i) => (
                      <a
                        key={i}
                        href={ref}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 text-xs text-blue-600 hover:underline"
                      >
                        Reference {i + 1} <ExternalLink className="h-3 w-3" />
                      </a>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
