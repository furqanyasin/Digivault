"use client";

import { useState } from "react";
import { Check, AlertTriangle, X, RefreshCw, Loader2, Wrench, Copy, ClipboardCheck, ChevronDown, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { SecurityHeaderReport } from "@/lib/api";
import { fmtDateTime } from "@/lib/utils";

interface Props {
  websiteId: string;
  report: SecurityHeaderReport | null;
}

// A permissive *starter* CSP. Deliberately broader than the old value, which
// declared only default-src/img/script/style/font/connect: every other fetch
// directive falls back to default-src 'self', so iframes were silently blocked
// — reCAPTCHA, Stripe Checkout, YouTube and Vimeo embeds all need frame-src.
//
// form-action allows https: rather than 'self' alone, because agency sites
// routinely POST to Mailchimp/HubSpot/payment gateways. object-src 'none' and
// base-uri 'self' are the two directives that are safe to lock down outright.
const CSP_STARTER = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline' 'unsafe-eval' https:",
  "style-src 'self' 'unsafe-inline' https:",
  "img-src 'self' data: https:",
  "font-src 'self' data: https:",
  "connect-src 'self' https:",
  "frame-src 'self' https:",
  "media-src 'self' https:",
  "worker-src 'self' blob:",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self' https:",
  "frame-ancestors 'self'",
].join("; ");

// `paste` headers are safe to apply unread. `test` headers can take a working
// site down and must be verified first — the UI labels them differently and the
// guide explains why for each.
type Confidence = "paste" | "test";

interface HeaderGuide {
  name: string;
  value: string;
  key: string; // matches the report key from the backend grader
  priority: "High" | "Medium" | "Low";
  confidence: Confidence;
}

// Two values here are deliberately NOT the strictest option available:
//
//   HSTS omits `preload`. Submission to the browser preload list is effectively
//   permanent and applies to every subdomain — mail., dev., staging., legacy
//   hosts must all serve HTTPS indefinitely or they become unreachable, with no
//   quick way back. It is a verified decision, never a paste-in default.
//
//   COOP is same-origin-allow-popups, not same-origin. Full isolation severs
//   window.opener, which breaks Google/Microsoft/Facebook sign-in and Stripe and
//   PayPal popup checkouts. The grader accepts allow-popups as a pass, so this
//   costs nothing in score.
const RECOMMENDED: HeaderGuide[] = [
  { name: "X-Content-Type-Options", value: "nosniff", key: "x-content-type-options", priority: "High", confidence: "paste" },
  { name: "X-Frame-Options", value: "SAMEORIGIN", key: "x-frame-options", priority: "High", confidence: "paste" },
  { name: "Referrer-Policy", value: "strict-origin-when-cross-origin", key: "referrer-policy", priority: "High", confidence: "paste" },
  { name: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()", key: "permissions-policy", priority: "Medium", confidence: "paste" },
  { name: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains", key: "strict-transport-security", priority: "High", confidence: "test" },
  { name: "Cross-Origin-Opener-Policy", value: "same-origin-allow-popups", key: "cross-origin-opener-policy", priority: "Low", confidence: "test" },
  { name: "Content-Security-Policy", value: CSP_STARTER, key: "content-security-policy", priority: "High", confidence: "test" },
];

// Not exported: this module is "use client", so an exported value imported by a
// server component becomes a client reference and throws only at runtime.
const HEADER_GUIDE = new Map(RECOMMENDED.map((h) => [h.key, h]));

type Platform = "cloudflare" | "nginx" | "apache" | "wordpress";

// Ordered best-first. Headers belong in the edge or the web server: they are
// then sent on every response, including static assets and cached pages, and
// cannot be bypassed. PHP runs only for requests WordPress actually handles.
const PLATFORMS: { key: Platform; label: string; note: string }[] = [
  { key: "cloudflare", label: "Cloudflare", note: "Best: applied at the edge, before a request reaches the origin at all." },
  { key: "nginx", label: "Nginx", note: "Best: one config block, sent on every response including static files." },
  { key: "apache", label: "Apache", note: "Good: same coverage as Nginx, but .htaccess is re-read per request." },
  { key: "wordpress", label: "WordPress", note: "Fallback only, and as an mu-plugin rather than functions.php — PHP misses static assets and full-page-cached responses, and theme code stops working the day the theme changes." },
];

type CspMode = "report" | "enforce";

// PHP double-quoted strings interpolate $ and honour backslash escapes. The old
// snippet used SINGLE quotes, which is a hard parse error the moment a value
// contains one — and the CSP is full of 'self'.
function phpString(s: string): string {
  return s.replace(/\\/g, "\\\\").replace(/"/g, '\\"').replace(/\$/g, "\\$");
}

// The CSP is emitted under whichever header name the chosen mode calls for;
// Report-Only is byte-identical apart from the name, so the same value can be
// promoted to enforcing once the violation reports are clean.
function headersFor(cspMode: CspMode): { name: string; value: string }[] {
  return RECOMMENDED.map((h) =>
    h.key === "content-security-policy" && cspMode === "report"
      ? { name: "Content-Security-Policy-Report-Only", value: h.value }
      : { name: h.name, value: h.value }
  );
}

function buildSnippet(platform: Platform, cspMode: CspMode): string {
  const headers = headersFor(cspMode);
  const modeNote =
    cspMode === "report"
      ? "# CSP is in Report-Only mode: violations are reported, nothing is blocked.\n"
      : "# CSP is ENFORCING. Only switch to this once Report-Only shows no violations.\n";

  if (platform === "nginx") {
    return (
      modeNote +
      "# Add inside the server { } block, then: nginx -t && systemctl reload nginx\n" +
      headers.map((h) => `add_header ${h.name} "${h.value}" always;`).join("\n")
    );
  }
  if (platform === "apache") {
    return (
      modeNote +
      "# Add to .htaccess or the <VirtualHost> (needs mod_headers)\n" +
      "<IfModule mod_headers.c>\n" +
      headers.map((h) => `  Header always set ${h.name} "${h.value}"`).join("\n") +
      "\n</IfModule>"
    );
  }
  if (platform === "wordpress") {
    return (
      "<?php\n" +
      "// Save as wp-content/mu-plugins/security-headers.php — must-use plugins load\n" +
      "// automatically and early, and survive theme switches and theme updates.\n" +
      "// functions.php also works, but the headers vanish the day the theme changes.\n" +
      "// Either way PHP only runs for requests WordPress handles: static assets and\n" +
      "// full-page-cached responses go out without these headers.\n" +
      modeNote.replace("# ", "// ") +
      "add_action('send_headers', function () {\n" +
      "    // wp-admin doesn't need these, and a CSP there fights the editor.\n" +
      "    if (is_admin()) {\n" +
      "        return;\n" +
      "    }\n" +
      "    // A plugin or stray output may have flushed the response already;\n" +
      "    // calling header() after that is a PHP warning, not a header.\n" +
      "    if (headers_sent()) {\n" +
      "        return;\n" +
      "    }\n\n" +
      headers.map((h) => `    header("${phpString(`${h.name}: ${h.value}`)}");`).join("\n") +
      // Priority 20: run after the default send_headers callbacks so these values
      // are the last ones set and win over anything a plugin sent earlier.
      "\n}, 20);"
    );
  }
  // cloudflare
  return (
    modeNote.replace("# ", "") +
    "Cloudflare → Rules → Transform Rules → Modify Response Header → Create rule\n" +
    'Apply to: Hostname equals your domain, then "Set static" for each:\n\n' +
    headers.map((h) => `${h.name}: ${h.value}`).join("\n")
  );
}

function HeaderFixGuide({ failCount }: { failCount: number }) {
  const [platform, setPlatform] = useState<Platform>("cloudflare");
  const [cspMode, setCspMode] = useState<CspMode>("report");
  const [copied, setCopied] = useState(false);
  // Collapsed by default: the guide carries a snippet plus the caveats for HSTS
  // preload, COOP popups and CSP rollout, which together dwarf the grade and
  // checklist people come to this panel to read.
  const [open, setOpen] = useState(false);
  const snippet = buildSnippet(platform, cspMode);
  const activeNote = PLATFORMS.find((p) => p.key === platform)?.note;

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
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls="header-fix-guide"
        className="flex w-full items-center gap-2 text-left"
      >
        <Wrench className="h-4 w-4 text-muted-foreground shrink-0" />
        <h4 className="text-sm font-medium flex-1">How to fix {failCount > 0 ? `the ${failCount} missing header${failCount > 1 ? "s" : ""}` : "these"}</h4>
        {open ? (
          <ChevronDown className="h-4 w-4 text-muted-foreground shrink-0" aria-hidden="true" />
        ) : (
          <ChevronRight className="h-4 w-4 text-muted-foreground shrink-0" aria-hidden="true" />
        )}
      </button>

      {!open && (
        <p className="text-xs text-muted-foreground">
          Copy-paste config for Cloudflare, Nginx, Apache or WordPress — plus which values are safe to apply
          unread and which need testing first.
        </p>
      )}

      {open && (
      <div className="space-y-2.5" id="header-fix-guide">
      <p className="text-xs text-muted-foreground">
        These are set by the <span className="font-medium">web server / CDN</span> — not in page content. Four of the
        seven are safe to paste as-is; three can break a working site and are explained below.
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
      {activeNote && <p className="text-[11px] text-muted-foreground">{activeNote}</p>}

      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-[11px] text-muted-foreground mr-0.5">CSP mode:</span>
        {(
          [
            { key: "report" as CspMode, label: "Report-Only (start here)" },
            { key: "enforce" as CspMode, label: "Enforcing" },
          ]
        ).map((m) => (
          <button
            key={m.key}
            type="button"
            onClick={() => setCspMode(m.key)}
            aria-pressed={cspMode === m.key}
            className={`px-2 py-0.5 rounded text-[11px] border transition-colors ${
              cspMode === m.key ? "bg-foreground text-background border-foreground" : "hover:bg-muted"
            }`}
          >
            {m.label}
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

      <div className="space-y-1.5 text-[11px] leading-relaxed text-amber-600 dark:text-amber-500">
        <p>
          <span className="font-medium">Content-Security-Policy is a starter, not a finished policy.</span> Deploy it in
          Report-Only first and read the violation reports — production sites usually need extra allowlisting for
          analytics, ad pixels, embeds and payment providers (reCAPTCHA needs{" "}
          <code className="font-mono">frame-src https://www.google.com</code>, Stripe{" "}
          <code className="font-mono">https://js.stripe.com</code>). It still carries{" "}
          <code className="font-mono">&apos;unsafe-inline&apos;</code> and <code className="font-mono">&apos;unsafe-eval&apos;</code>,
          which most WordPress themes need but which materially weaken the policy — removing them via nonces or hashes
          is the real win, not merely having the header.
        </p>
        <p>
          <span className="font-medium">HSTS is shown without <code className="font-mono">preload</code> on purpose.</span>{" "}
          Preloading is effectively permanent and covers every subdomain. Add it only once you have confirmed that{" "}
          <em>all</em> of them — mail, dev, staging, legacy hosts — serve valid HTTPS and always will.
        </p>
        <p>
          <span className="font-medium">Cross-Origin-Opener-Policy is optional.</span>{" "}
          <code className="font-mono">same-origin-allow-popups</code> is used here rather than{" "}
          <code className="font-mono">same-origin</code> because full isolation severs{" "}
          <code className="font-mono">window.opener</code> and breaks Google/Microsoft/Facebook sign-in and Stripe and
          PayPal popups. Test those flows before enabling either value.
        </p>
        <p className="text-muted-foreground">
          After deploying, click <span className="font-medium">Check Headers</span> to re-grade.
        </p>
      </div>
      </div>
      )}
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
            {data.headers.map((h) => {
              const guide = HEADER_GUIDE.get(h.key);
              return (
              <div key={h.key} className="flex items-start gap-2.5">
                {STATUS_ICON[h.status]}
                <div className="min-w-0 flex-1">
                  <div className="flex items-baseline gap-2 flex-wrap">
                    <span className="text-sm font-medium">{h.name}</span>
                    {!h.present && (
                      <span className="text-xs text-red-600 font-medium">missing</span>
                    )}
                    {/* Not every missing header is equally urgent, and not every
                        fix is equally safe — the two are independent, so both are
                        labelled rather than collapsed into one severity. */}
                    {guide && (
                      <span className="text-[10px] text-muted-foreground">
                        {guide.priority} priority
                      </span>
                    )}
                    {guide?.confidence === "test" && (
                      <span
                        className="text-[10px] font-medium text-amber-600 dark:text-amber-500"
                        title="Applying this header can break a working site — verify before deploying"
                      >
                        test first
                      </span>
                    )}
                    {guide?.confidence === "paste" && (
                      <span className="text-[10px] text-emerald-600 dark:text-emerald-500">
                        safe default
                      </span>
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
              );
            })}
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
