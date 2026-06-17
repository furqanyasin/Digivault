"use client";

import { useState } from "react";
import { Check, AlertTriangle, X, RefreshCw, Loader2, Wrench, Copy, ClipboardCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { SecurityHeaderReport } from "@/lib/api";
import { fmtDateTime } from "@/lib/utils";

interface Props {
  websiteId: string;
  report: SecurityHeaderReport | null;
}

// Recommended directives for the headers Digivault grades, ordered to match the
// checklist. The CSP is a permissive *starter* — a strict policy must be tuned
// per-site or it will block legitimate scripts/styles (see the caveat below).
const RECOMMENDED: { name: string; value: string }[] = [
  { name: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains; preload" },
  { name: "X-Frame-Options", value: "SAMEORIGIN" },
  { name: "X-Content-Type-Options", value: "nosniff" },
  { name: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { name: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
  { name: "Cross-Origin-Opener-Policy", value: "same-origin" },
  { name: "Content-Security-Policy", value: "default-src 'self'; img-src 'self' data: https:; script-src 'self' 'unsafe-inline' 'unsafe-eval' https:; style-src 'self' 'unsafe-inline' https:; font-src 'self' data: https:; connect-src 'self' https:; frame-ancestors 'self'" },
];

type Platform = "nginx" | "apache" | "wordpress" | "cloudflare";

const PLATFORMS: { key: Platform; label: string }[] = [
  { key: "nginx", label: "Nginx" },
  { key: "apache", label: "Apache" },
  { key: "wordpress", label: "WordPress" },
  { key: "cloudflare", label: "Cloudflare" },
];

function buildSnippet(platform: Platform): string {
  if (platform === "nginx") {
    return (
      "# Add inside the server { } block, then: nginx -t && systemctl reload nginx\n" +
      RECOMMENDED.map((h) => `add_header ${h.name} "${h.value}" always;`).join("\n")
    );
  }
  if (platform === "apache") {
    return (
      "# Add to .htaccess or the <VirtualHost> (needs mod_headers)\n" +
      "<IfModule mod_headers.c>\n" +
      RECOMMENDED.map((h) => `  Header always set ${h.name} "${h.value}"`).join("\n") +
      "\n</IfModule>"
    );
  }
  if (platform === "wordpress") {
    return (
      "// Drop in the theme's functions.php or a small mu-plugin\n" +
      "add_action('send_headers', function () {\n" +
      RECOMMENDED.map((h) => `    header('${h.name}: ${h.value}');`).join("\n") +
      "\n});"
    );
  }
  // cloudflare
  return (
    "Cloudflare → Rules → Transform Rules → Modify Response Header → Create rule\n" +
    'Apply to: Hostname equals your domain, then "Set static" for each:\n\n' +
    RECOMMENDED.map((h) => `${h.name}: ${h.value}`).join("\n")
  );
}

function HeaderFixGuide({ failCount }: { failCount: number }) {
  const [platform, setPlatform] = useState<Platform>("nginx");
  const [copied, setCopied] = useState(false);
  const snippet = buildSnippet(platform);

  async function copy() {
    try {
      await navigator.clipboard.writeText(snippet);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable — user can select manually */
    }
  }

  return (
    <div className="flex-1 min-w-0 rounded-lg border bg-muted/30 p-3 space-y-2.5">
      <div className="flex items-center gap-2">
        <Wrench className="h-4 w-4 text-muted-foreground shrink-0" />
        <h4 className="text-sm font-medium">How to fix {failCount > 0 ? `the ${failCount} missing header${failCount > 1 ? "s" : ""}` : "these"}</h4>
      </div>
      <p className="text-xs text-muted-foreground">
        These are set by the <span className="font-medium">web server / CDN</span> — not in page content. Pick the
        client&apos;s stack and add the block once; it covers every header above.
      </p>

      <div className="flex flex-wrap gap-1">
        {PLATFORMS.map((p) => (
          <button
            key={p.key}
            type="button"
            onClick={() => setPlatform(p.key)}
            className={`px-2.5 py-1 rounded text-xs border transition-colors ${
              platform === p.key ? "bg-primary text-primary-foreground border-primary" : "hover:bg-muted"
            }`}
          >
            {p.label}
          </button>
        ))}
      </div>

      <div className="relative">
        <pre className="text-[11px] leading-relaxed bg-background border rounded-md p-3 pr-10 overflow-x-auto font-mono whitespace-pre">
          {snippet}
        </pre>
        <button
          type="button"
          onClick={copy}
          className="absolute top-2 right-2 p-1.5 rounded border bg-background hover:bg-muted"
          title="Copy snippet"
        >
          {copied ? <ClipboardCheck className="h-3.5 w-3.5 text-emerald-600" /> : <Copy className="h-3.5 w-3.5 text-muted-foreground" />}
        </button>
      </div>

      <p className="text-[11px] text-amber-600 dark:text-amber-500 leading-relaxed">
        <span className="font-medium">Heads-up on Content-Security-Policy:</span> the value above is a permissive
        starter so it won&apos;t break the site. Tighten it gradually (remove <code className="font-mono">&apos;unsafe-inline&apos;</code>/
        <code className="font-mono">&apos;unsafe-eval&apos;</code>, allowlist real third-party domains) and re-test —
        a too-strict CSP can block analytics, chat widgets and fonts. After deploying, click <span className="font-medium">Check Headers</span> to re-grade.
      </p>
    </div>
  );
}

const GRADE_COLOR: Record<string, string> = {
  "A+": "bg-emerald-500 text-white border-emerald-600",
  A: "bg-emerald-500 text-white border-emerald-600",
  B: "bg-lime-500 text-white border-lime-600",
  C: "bg-amber-400 text-amber-950 border-amber-500",
  D: "bg-orange-500 text-white border-orange-600",
  F: "bg-red-500 text-white border-red-600",
};

const STATUS_ICON = {
  pass: <Check className="h-4 w-4 text-emerald-600 shrink-0" />,
  warn: <AlertTriangle className="h-4 w-4 text-amber-500 shrink-0" />,
  fail: <X className="h-4 w-4 text-red-500 shrink-0" />,
} as const;

export function SecurityHeadersPanel({ websiteId, report }: Props) {
  const [checking, setChecking] = useState(false);
  const [data, setData] = useState<SecurityHeaderReport | null>(report);

  async function runCheck() {
    setChecking(true);
    try {
      await fetch(`/api/websites/${websiteId}/security-headers`, { method: "POST" });
      let attempts = 0;
      const poll = async () => {
        attempts++;
        const res = await fetch(`/api/websites/${websiteId}/security-headers`);
        const json = await res.json();
        const s: SecurityHeaderReport = json?.data ?? json;
        setData(s);
        if (s.check_status === "running" && attempts < 20) {
          setTimeout(poll, 1500);
        } else {
          setChecking(false);
        }
      };
      setTimeout(poll, 1200);
    } catch {
      setChecking(false);
    }
  }

  const hasResult = data && data.check_status === "done" && data.headers?.length > 0;
  const running = checking || data?.check_status === "running";

  return (
    <div className="border rounded-lg p-4 space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="font-medium text-sm">Security Headers</h3>
          <p className="text-xs text-muted-foreground mt-0.5">
            HTTP response headers that protect against XSS, clickjacking & protocol downgrade.
            {data?.last_checked_at && ` · Checked ${fmtDateTime(data.last_checked_at)}`}
            {data?.check_status === "failed" && data.error && (
              <span className="text-red-600"> · {data.error}</span>
            )}
          </p>
        </div>
        <Button size="sm" variant="outline" onClick={runCheck} disabled={running}>
          {running ? (
            <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
          ) : (
            <RefreshCw className="h-3.5 w-3.5 mr-1.5" />
          )}
          Check Headers
        </Button>
      </div>

      {!hasResult ? (
        <p className="text-sm text-muted-foreground py-6 text-center">
          {data?.check_status === "running"
            ? "Checking headers…"
            : "No header check run yet. Click Check Headers to grade this site."}
        </p>
      ) : (
        <div className="flex flex-col lg:flex-row gap-5">
          {/* Grade badge */}
          <div className="flex lg:flex-col items-center gap-3 lg:gap-1.5 shrink-0">
            <div
              className={`flex items-center justify-center h-20 w-20 rounded-xl border text-3xl font-bold ${
                GRADE_COLOR[data.grade] ?? "bg-muted text-foreground border-border"
              }`}
            >
              {data.grade}
            </div>
            <div className="text-center">
              <div className="text-lg font-semibold leading-none">{data.score}<span className="text-xs text-muted-foreground">/100</span></div>
              <div className="text-xs text-muted-foreground mt-1">
                {data.pass_count} pass · {data.warn_count} warn · {data.fail_count} fail
              </div>
            </div>
          </div>

          {/* Header checklist */}
          <div className="lg:w-[44%] space-y-2 min-w-0 shrink-0">
            {data.headers.map((h) => (
              <div key={h.key} className="flex items-start gap-2.5">
                {STATUS_ICON[h.status]}
                <div className="min-w-0 flex-1">
                  <div className="flex items-baseline gap-2 flex-wrap">
                    <span className="text-sm font-medium">{h.name}</span>
                    {!h.present && (
                      <span className="text-xs text-red-600 font-medium">missing</span>
                    )}
                  </div>
                  {h.present && h.value && (
                    <p className="font-mono text-xs text-muted-foreground break-all">{h.value}</p>
                  )}
                  {h.recommendation && (
                    <p className="text-xs text-muted-foreground mt-0.5">{h.recommendation}</p>
                  )}
                </div>
              </div>
            ))}
          </div>

          {/* How-to-fix guide — fills the space beside the checklist */}
          {data.fail_count + data.warn_count > 0 ? (
            <HeaderFixGuide failCount={data.fail_count} />
          ) : (
            <div className="flex-1 min-w-0 rounded-lg border border-emerald-200 dark:border-emerald-900 bg-emerald-50/40 dark:bg-emerald-950/20 p-3 flex items-center gap-2">
              <Check className="h-4 w-4 text-emerald-600 shrink-0" />
              <p className="text-sm text-muted-foreground">All graded headers are present — nothing to fix right now.</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
