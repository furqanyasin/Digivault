import Link from "next/link";
import { Search, Gauge, ShieldCheck, BarChart3, ArrowRight, AlertTriangle, CheckCircle2, MinusCircle } from "lucide-react";

export interface FleetSummary {
  total_sites: number;
  tracking: {
    analytics: number; missing_analytics: number; tag_manager: number;
    advertising: number; call_tracking: number; unknown_scripts: number;
    suspicious_sites: number; suspicious_scripts: number;
  };
  seo: {
    checked: number; not_checked: number; indexable: number;
    blocked: number; noindex_pages: number;
  };
  performance: {
    measured: number; not_measured: number;
    avg_mobile: number | null; avg_desktop: number | null;
    poor_mobile: number; good_mobile: number;
  };
  security: {
    checked: number; not_checked: number; avg_score: number | null;
    grades: Record<string, number>; failing: number;
  };
  vulnerabilities: {
    critical: number; high: number; medium: number; low: number; sites_affected: number;
  };
}

type Tone = "good" | "warning" | "critical" | "idle";

const BAR: Record<Tone, string> = {
  good: "bg-emerald-500",
  warning: "bg-amber-500",
  critical: "bg-red-500",
  idle: "bg-muted-foreground/30",
};
const INK: Record<Tone, string> = {
  good: "text-emerald-700 dark:text-emerald-400",
  warning: "text-amber-700 dark:text-amber-400",
  critical: "text-red-700 dark:text-red-400",
  idle: "text-muted-foreground",
};
const ICON: Record<Tone, typeof CheckCircle2> = {
  good: CheckCircle2, warning: AlertTriangle, critical: AlertTriangle, idle: MinusCircle,
};

/** One area of fleet-wide health.
 *
 *  Leads with **coverage** rather than a score: an average over the handful of
 *  sites that happen to have been scanned flatters the fleet and hides the sites
 *  nobody has looked at. The bar is "how much of the fleet do we actually know
 *  about", and the verdict names the gap.
 */
function CheckCard({
  label, icon: Icon, checked, total, headline, headlineUnit, verdict, tone, href,
}: {
  label: string;
  icon: typeof Search;
  checked: number;
  total: number;
  headline: string | number;
  headlineUnit?: string;
  verdict: string;
  tone: Tone;
  href: string;
}) {
  const VerdictIcon = ICON[tone];
  const pct = total > 0 ? Math.round((checked / total) * 100) : 0;
  return (
    <Link
      href={href}
      className="group flex flex-col gap-2.5 rounded-xl border bg-card p-4 shadow-sm transition-all hover:border-foreground/20 hover:shadow-md"
    >
      <span className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
        <Icon className="h-3.5 w-3.5" aria-hidden />
        {label}
        <ArrowRight className="ml-auto h-3.5 w-3.5 opacity-0 transition-opacity group-hover:opacity-60" aria-hidden />
      </span>

      <span className="flex items-baseline gap-1.5">
        <span className="text-2xl font-bold leading-none tabular-nums">{headline}</span>
        {headlineUnit && <span className="text-xs text-muted-foreground">{headlineUnit}</span>}
      </span>

      <span className="flex h-1.5 w-full overflow-hidden rounded-full bg-muted" aria-hidden>
        <span className={`h-full ${BAR[tone]}`} style={{ width: `${pct}%` }} />
      </span>
      <span className="text-xs text-muted-foreground">
        {checked} of {total} site{total === 1 ? "" : "s"} checked
      </span>

      <span className={`flex items-center gap-1.5 text-xs font-medium ${INK[tone]}`}>
        <VerdictIcon className="h-3.5 w-3.5 shrink-0" aria-hidden />
        {verdict}
      </span>
    </Link>
  );
}

/** Fleet-wide SEO, performance and security — the three areas Digivault already
 *  scans per site but never summarised anywhere. */
export function FleetChecksRow({ s }: { s: FleetSummary }) {
  const total = s.total_sites;

  const seoTone: Tone =
    s.seo.checked === 0 ? "idle"
    : s.seo.blocked > 0 ? "critical"
    : s.seo.not_checked > s.seo.checked ? "warning"
    : "good";

  const perfTone: Tone =
    s.performance.measured === 0 ? "idle"
    : s.performance.poor_mobile > 0 ? "critical"
    : (s.performance.avg_mobile ?? 0) < 90 ? "warning"
    : "good";

  const secTone: Tone =
    s.tracking.suspicious_scripts > 0 ? "critical"
    : s.vulnerabilities.critical > 0 ? "critical"
    : s.security.checked === 0 ? "idle"
    : s.security.failing > 0 || s.vulnerabilities.high > 0 ? "warning"
    : "good";

  const trackTone: Tone =
    s.tracking.analytics === 0 ? "idle"
    : s.tracking.missing_analytics > 0 ? "warning"
    : s.tracking.unknown_scripts > 0 ? "warning"
    : "good";

  const openVulns =
    s.vulnerabilities.critical + s.vulnerabilities.high
    + s.vulnerabilities.medium + s.vulnerabilities.low;

  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <CheckCard
        label="Search & SEO" icon={Search} href="/websites"
        checked={s.seo.checked} total={total}
        headline={s.seo.checked === 0 ? "—" : s.seo.indexable}
        headlineUnit={s.seo.checked === 0 ? undefined : "indexable"}
        tone={seoTone}
        verdict={
          s.seo.checked === 0 ? "No site has been scanned yet"
          : s.seo.blocked > 0 ? `${s.seo.blocked} blocked from search`
          : s.seo.noindex_pages > 0 ? `${s.seo.noindex_pages} noindex page${s.seo.noindex_pages === 1 ? "" : "s"}`
          : "All scanned sites indexable"
        }
      />

      <CheckCard
        label="Performance" icon={Gauge} href="/websites"
        checked={s.performance.measured} total={total}
        headline={s.performance.avg_mobile ?? "—"}
        headlineUnit={s.performance.avg_mobile === null ? undefined : "avg mobile"}
        tone={perfTone}
        verdict={
          s.performance.measured === 0 ? "No PageSpeed run recorded"
          : s.performance.poor_mobile > 0 ? `${s.performance.poor_mobile} scoring under 50`
          : s.performance.good_mobile === s.performance.measured ? "All measured sites fast"
          : `${s.performance.good_mobile} of ${s.performance.measured} scoring 90+`
        }
      />

      <CheckCard
        label="Trust & Security" icon={ShieldCheck} href="/websites"
        checked={s.security.checked} total={total}
        headline={openVulns}
        headlineUnit={openVulns === 1 ? "vulnerability" : "vulnerabilities"}
        tone={secTone}
        verdict={
          s.tracking.suspicious_scripts > 0
            ? `${s.tracking.suspicious_scripts} suspicious script${s.tracking.suspicious_scripts === 1 ? "" : "s"} on ${s.tracking.suspicious_sites} site${s.tracking.suspicious_sites === 1 ? "" : "s"}`
          : s.vulnerabilities.critical > 0
            ? `${s.vulnerabilities.critical} critical on ${s.vulnerabilities.sites_affected} site${s.vulnerabilities.sites_affected === 1 ? "" : "s"}`
          : s.security.checked === 0 ? "No header check recorded"
          : s.security.failing > 0 ? `${s.security.failing} site${s.security.failing === 1 ? "" : "s"} grading C or worse`
          : "Headers passing, no known CVEs"
        }
      />
      <CheckCard
        label="Tracking" icon={BarChart3} href="/websites"
        checked={s.tracking.analytics} total={total}
        headline={s.tracking.analytics}
        headlineUnit="with analytics"
        tone={trackTone}
        verdict={
          s.tracking.analytics === 0 ? "No analytics detected anywhere"
          : s.tracking.missing_analytics > 0
            ? `${s.tracking.missing_analytics} site${s.tracking.missing_analytics === 1 ? "" : "s"} measuring nothing`
          : s.tracking.unknown_scripts > 0
            ? `${s.tracking.unknown_scripts} site${s.tracking.unknown_scripts === 1 ? "" : "s"} with unknown scripts`
          : "Every site is measured"
        }
      />
    </div>
  );
}
