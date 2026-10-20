"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { AlertTriangle, ArrowRight, CheckCircle2, Loader2, Search, XCircle } from "lucide-react";

type Kind = "ssl" | "domain" | "uptime" | "scripts";
type Result = Record<string, unknown>;

// Browser calls Django directly (nginx routes /api/v1/ there), so the rate
// limit sees the visitor's own IP rather than the Next.js server's.
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

function fmtDate(v: unknown) {
  if (typeof v !== "string") return "Unknown";
  return new Date(v).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export function ToolRunner({ kind, param, placeholder }: { kind: Kind; param: "domain" | "url"; placeholder: string }) {
  const [value, setValue] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<Result | null>(null);

  async function run(target: string) {
    const v = target.trim();
    if (!v) return;
    setLoading(true);
    setError("");
    setResult(null);
    try {
      const res = await fetch(`${API_BASE}/api/v1/public/tools/${kind}/?${param}=${encodeURIComponent(v)}`);
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(
          res.status === 429
            ? "You have run a lot of checks. Please wait a few minutes, or create a free account to monitor sites automatically."
            : body?.data?.detail ?? body?.errors?.[0]?.message ?? "The check failed. Please try again.",
        );
        return;
      }
      setResult(body?.data ?? body);
      const url = new URL(window.location.href);
      url.searchParams.set(param, v);
      window.history.replaceState(null, "", url.toString());
    } catch {
      setError("Could not reach our servers. Check your connection and try again.");
    } finally {
      setLoading(false);
    }
  }

  // A shared link like /tools/ssl-checker?domain=example.com runs straight away.
  useEffect(() => {
    const initial = new URLSearchParams(window.location.search).get(param);
    if (!initial) return;
    (async () => {
      await Promise.resolve();
      setValue(initial);
      run(initial);
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="mx-auto max-w-3xl">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          run(value);
        }}
        className="flex flex-col gap-3 rounded-[var(--radius-panel)] border border-[var(--ds-line)] bg-[var(--ds-surface-raised)] p-3 shadow-[var(--shadow-card)] sm:flex-row"
      >
        <label htmlFor="tool-input" className="sr-only">{param === "domain" ? "Domain" : "Website address"}</label>
        <input
          id="tool-input"
          className="ds-input border-0 shadow-none focus:shadow-none"
          placeholder={placeholder}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          inputMode="url"
          autoComplete="off"
          autoCapitalize="off"
          spellCheck={false}
          required
        />
        <button type="submit" disabled={loading} className="ds-btn ds-btn-primary ds-btn-lg shrink-0 disabled:opacity-60">
          {loading ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <Search className="h-4 w-4" aria-hidden />}
          {loading ? "Checking" : "Check"}
        </button>
      </form>

      <div aria-live="polite" className="mt-6">
        {error && (
          <div className="flex gap-3 rounded-[var(--radius-card)] border border-red-200 bg-red-50 p-4 text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-200">
            <XCircle className="h-5 w-5 shrink-0" aria-hidden />
            <p>{error}</p>
          </div>
        )}
        {result && <ResultView kind={kind} r={result} />}
      </div>
    </div>
  );
}

function Verdict({ tone, title, detail }: { tone: "good" | "warn" | "bad"; title: string; detail?: string }) {
  const styles = {
    good: "border-emerald-200 bg-emerald-50 text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-200",
    warn: "border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200",
    bad: "border-red-200 bg-red-50 text-red-900 dark:border-red-900 dark:bg-red-950/40 dark:text-red-200",
  }[tone];
  const Icon = tone === "good" ? CheckCircle2 : tone === "warn" ? AlertTriangle : XCircle;
  return (
    <div className={`flex gap-3 rounded-[var(--radius-card)] border p-4 ${styles}`}>
      <Icon className="mt-0.5 h-5 w-5 shrink-0" aria-hidden />
      <div>
        <p className="font-semibold">{title}</p>
        {detail && <p className="mt-1 text-small opacity-90">{detail}</p>}
      </div>
    </div>
  );
}

function Rows({ rows }: { rows: [string, React.ReactNode][] }) {
  return (
    <dl className="mt-4 divide-y divide-[var(--ds-line)] rounded-[var(--radius-card)] border border-[var(--ds-line)] bg-[var(--ds-surface-raised)]">
      {rows.map(([k, v]) => (
        <div key={k} className="grid gap-1 px-4 py-3 sm:grid-cols-[180px_1fr] sm:gap-4">
          <dt className="text-small font-medium text-[var(--ds-text-muted)]">{k}</dt>
          <dd className="min-w-0 break-words text-small text-[var(--ds-heading)]">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

function Upsell({ text }: { text: string }) {
  return (
    <div className="mt-6 flex flex-col items-start gap-3 rounded-[var(--radius-card)] bg-[var(--ds-surface-brand)] p-5 sm:flex-row sm:items-center sm:justify-between">
      <p className="text-small font-medium text-[var(--accent-foreground)]">{text}</p>
      <Link href="/signup" className="ds-btn ds-btn-primary ds-btn-sm shrink-0">
        Monitor it free <ArrowRight className="h-4 w-4" aria-hidden />
      </Link>
    </div>
  );
}

function ResultView({ kind, r }: { kind: Kind; r: Result }) {
  const days = typeof r.days_left === "number" ? (r.days_left as number) : null;

  if (kind === "ssl") {
    if (!r.valid) {
      return (
        <>
          <Verdict tone="bad" title={`No valid certificate on ${r.domain}`} detail={String(r.error || "")} />
          <Upsell text="Get an alert the moment a certificate breaks or is about to expire." />
        </>
      );
    }
    const tone = days === null ? "warn" : days <= 7 ? "bad" : days <= 30 ? "warn" : "good";
    return (
      <>
        <Verdict tone={tone} title={days === null ? "Certificate found" : `Certificate valid, expires in ${days} days`} detail={`${r.domain} serves a trusted certificate.`} />
        <Rows
          rows={[
            ["Issued to", String(r.subject || r.domain)],
            ["Issuer", String(r.issuer || "Unknown")],
            ["Valid from", fmtDate(r.valid_from)],
            ["Expires", fmtDate(r.valid_to)],
            ["Protocol", String(r.protocol || "Unknown")],
            ["Server IP", <span key="ip" className="dv-code">{String(r.ip)}</span>],
            ["Covers", ((r.san as string[]) || []).join(", ") || "None listed"],
          ]}
        />
        <Upsell text="We can check this certificate every day and remind you 30 and 7 days before it expires." />
      </>
    );
  }

  if (kind === "domain") {
    const tone = r.error ? "warn" : days === null ? "warn" : days <= 14 ? "bad" : days <= 60 ? "warn" : "good";
    return (
      <>
        <Verdict
          tone={tone}
          title={r.error ? `Partial result for ${r.domain}` : `${r.domain} expires in ${days} days`}
          detail={r.error ? String(r.error) : `Renewal date: ${fmtDate(r.expires_at)}`}
        />
        <Rows
          rows={[
            ["Registrar", String(r.registrar || "Unknown")],
            ["Registered", fmtDate(r.registered_at)],
            ["Expires", fmtDate(r.expires_at)],
            ["Nameservers", ((r.nameservers as string[]) || []).join(", ") || "Unknown"],
            ["Cloudflare DNS", r.uses_cloudflare ? "Yes" : "No"],
          ]}
        />
        <Upsell text="Track every client domain and get reminders from 90 days before renewal." />
      </>
    );
  }

  if (kind === "uptime") {
    const state = String(r.status);
    const tone = state === "up" ? "good" : state === "down" ? "bad" : "warn";
    const title =
      state === "up" ? "It's up. The site answered normally." :
      state === "down" ? "It's down for us too." :
      state === "blocked" ? "A firewall answered instead of the site" : "We could not tell right now";
    return (
      <>
        <Verdict tone={tone} title={title} detail={String(r.error || "")} />
        <Rows
          rows={[
            ["Checked URL", <span key="u" className="dv-code">{String(r.final_url || r.url)}</span>],
            ["HTTP status", r.status_code ? String(r.status_code) : "No answer"],
            ["Response time", r.response_time_ms ? `${r.response_time_ms} ms` : "n/a"],
          ]}
        />
        <Upsell text="Get an alert within minutes the next time this site goes down." />
      </>
    );
  }

  // scripts
  const scripts = (r.scripts as { url: string; host: string; provider: string; category: string; first_party: boolean }[]) || [];
  if (r.error) {
    return <Verdict tone="warn" title="We could not scan this page" detail={String(r.error)} />;
  }
  const third = scripts.filter((s) => !s.first_party);
  return (
    <>
      <Verdict
        tone={(r.unknown_count as number) > 0 ? "warn" : "good"}
        title={`${third.length} third-party script${third.length === 1 ? "" : "s"} found`}
        detail={(r.unknown_count as number) > 0 ? `${r.unknown_count} could not be matched to a known provider.` : "Every third-party script matched a known provider."}
      />
      {scripts.length > 0 && (
        <ul className="mt-4 divide-y divide-[var(--ds-line)] rounded-[var(--radius-card)] border border-[var(--ds-line)] bg-[var(--ds-surface-raised)]">
          {scripts.map((s) => (
            <li key={s.url} className="flex flex-col gap-1 px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
              <div className="min-w-0">
                <p className="text-small font-semibold text-[var(--ds-heading)]">
                  {s.provider || (s.first_party ? "Site's own script" : "Unknown provider")}
                </p>
                <p className="dv-code truncate text-caption text-[var(--ds-text-muted)]" title={s.url}>{s.url}</p>
              </div>
              <span className={`w-fit shrink-0 rounded-full px-2.5 py-0.5 text-caption font-medium ${s.first_party ? "bg-[var(--ds-surface-sunken)] text-[var(--ds-text-muted)]" : s.provider ? "bg-[var(--ds-surface-brand)] text-[var(--accent-foreground)]" : "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300"}`}>
                {s.first_party ? "first party" : s.category.replace(/_/g, " ")}
              </span>
            </li>
          ))}
        </ul>
      )}
      <Upsell text="Our snippet sees scripts added in the browser too, and alerts you when any of them change." />
    </>
  );
}
