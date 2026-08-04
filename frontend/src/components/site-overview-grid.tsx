import Link from "next/link";
import {
  Activity, Code2, FileInput, Gauge, History, ShieldCheck, Search,
  ArrowRight, AlertTriangle, CheckCircle2, MinusCircle,
} from "lucide-react";

/** State of one area. Drives the rail colour AND the written verdict — the
 *  colour is reinforcement, never the only signal. */
export type ChunkState = "good" | "warning" | "critical" | "idle";

const RAIL: Record<ChunkState, string> = {
  good: "bg-emerald-500",
  warning: "bg-amber-500",
  critical: "bg-red-500",
  idle: "bg-muted-foreground/25",
};

const VERDICT_INK: Record<ChunkState, string> = {
  good: "text-emerald-700 dark:text-emerald-400",
  warning: "text-amber-700 dark:text-amber-400",
  critical: "text-red-700 dark:text-red-400",
  idle: "text-muted-foreground",
};

const VERDICT_ICON: Record<ChunkState, typeof CheckCircle2> = {
  good: CheckCircle2,
  warning: AlertTriangle,
  critical: AlertTriangle,
  idle: MinusCircle,
};

/** A radial gauge for the headline score. Uses one SVG arc rather than a flat
 *  bar so the Health chunk reads as the anchor of the grid; stroke-dasharray on
 *  a circle needs no library and stays crisp at any size. */
function ScoreGauge({ value, state }: { value: number; state: ChunkState }) {
  const r = 26;
  const circumference = 2 * Math.PI * r;
  const filled = (Math.max(0, Math.min(100, value)) / 100) * circumference;
  return (
    <svg viewBox="0 0 64 64" className="h-16 w-16 shrink-0 -rotate-90" aria-hidden>
      <circle cx="32" cy="32" r={r} fill="none" strokeWidth="6" className="stroke-muted" />
      <circle
        cx="32" cy="32" r={r} fill="none" strokeWidth="6" strokeLinecap="round"
        className={GAUGE_STROKE[state]}
        strokeDasharray={`${filled} ${circumference - filled}`}
      />
    </svg>
  );
}

const GAUGE_STROKE: Record<ChunkState, string> = {
  good: "stroke-emerald-500",
  warning: "stroke-amber-500",
  critical: "stroke-red-500",
  idle: "stroke-muted-foreground/30",
};

/** Recent check results, oldest to newest — the actual samples, not a summary. */
function StatusStrip({ statuses }: { statuses: string[] }) {
  const tone = (s: string) =>
    s === "up" ? "bg-emerald-500"
    : s === "down" ? "bg-red-500"
    : s === "degraded" ? "bg-amber-500"
    : "bg-muted";
  return (
    <span className="flex h-4 items-end gap-[2px]" aria-hidden>
      {statuses.slice(-24).map((st, i) => (
        <span
          key={i}
          className={`w-full rounded-sm ${tone(st)} ${st === "up" ? "h-2.5" : "h-4"}`}
          title={st}
        />
      ))}
    </span>
  );
}

/** A meter, used where the value is a 0–100 score. */
function Meter({ value, state }: { value: number; state: ChunkState }) {
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted" role="presentation">
      <div
        className={`h-full rounded-full ${RAIL[state]}`}
        style={{ width: `${Math.max(2, Math.min(100, value))}%` }}
      />
    </div>
  );
}

/** Part-to-whole across a handful of buckets, e.g. severity mix. Segments carry
 *  their own colour and the caller labels them in text underneath. */
function SplitBar({ parts }: { parts: { value: number; className: string; label: string }[] }) {
  const total = parts.reduce((s, p) => s + p.value, 0);
  if (total === 0) return <div className="h-1.5 w-full rounded-full bg-muted" />;
  return (
    <div className="flex h-1.5 w-full gap-[2px] overflow-hidden rounded-full">
      {parts
        .filter((p) => p.value > 0)
        .map((p) => (
          <div
            key={p.label}
            className={`h-full ${p.className}`}
            style={{ flexGrow: p.value, flexBasis: 0 }}
            title={`${p.label}: ${p.value}`}
          />
        ))}
    </div>
  );
}

/** One area of the site, as a card that opens its own tab.
 *
 *  A link rather than a Radix TabsTrigger: a Trigger has to sit inside TabsList,
 *  which supplies the RovingFocusGroup it depends on, and throws anywhere else.
 *  The page already reads ?tab= into `defaultValue`, so a link is the mechanism
 *  the rest of this page uses to jump between tabs.
 */
function Chunk({
  websiteId, tab, label, icon: Icon, value, unit, state, verdict, children, aside,
}: {
  websiteId: string;
  tab: string;
  label: string;
  icon: typeof Activity;
  value: string | number;
  unit?: string;
  state: ChunkState;
  verdict: string;
  children?: React.ReactNode;
  /** Sits to the right of the value — for the Health gauge. */
  aside?: React.ReactNode;
}) {
  const VerdictIcon = VERDICT_ICON[state];
  return (
    <Link
      href={`/websites/${websiteId}?tab=${tab}`}
      scroll={false}
      className="group relative flex flex-col items-stretch gap-2.5 overflow-hidden rounded-xl border bg-card p-4 pl-5 text-left shadow-sm transition-all hover:shadow-md hover:border-foreground/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      {/* The status rail — read the grid's left edge to see where to look. */}
      <span className={`absolute inset-y-0 left-0 w-[3px] ${RAIL[state]}`} aria-hidden />

      <span className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
        <Icon className="h-3.5 w-3.5" aria-hidden />
        {label}
        <ArrowRight className="ml-auto h-3.5 w-3.5 opacity-0 transition-opacity group-hover:opacity-60" aria-hidden />
      </span>

      <span className="flex items-center justify-between gap-3">
        <span className="flex items-baseline gap-1.5">
          <span className="text-3xl font-bold leading-none tabular-nums">{value}</span>
          {unit && <span className="text-xs text-muted-foreground">{unit}</span>}
        </span>
        {aside}
      </span>

      {children}

      <span className={`flex items-center gap-1.5 text-xs font-medium ${VERDICT_INK[state]}`}>
        <VerdictIcon className="h-3.5 w-3.5 shrink-0" aria-hidden />
        {verdict}
      </span>
    </Link>
  );
}

export interface OverviewMetrics {
  health: { score: number; status: string };
  scripts: { total: number; unknown: number; categories: number };
  forms: { total: number; broken: number };
  uptime: { pct: number | null; up: number; down: number; degraded: number; monitors: number; recent: string[] };
  performance: { mobile: number | null; desktop: number | null };
  changelog: { pending: number; critical: number; high: number; medium: number; low: number };
  security: { critical: number; high: number; other: number; grade: string; phpErrors: number };
  seo: { checked: boolean; indexable: boolean | null; noindex: number; sitemapPages: number; robotsBlocked: boolean };
}

/** Score bands mirror Website.HEALTH_* on the backend. */
function scoreBand(score: number): ChunkState {
  if (score >= 85) return "good";
  if (score >= 60) return "warning";
  return "critical";
}

const SEVERITY_RANK: Record<ChunkState, number> = {
  idle: 0, good: 1, warning: 2, critical: 3,
};

/** The rail follows whichever of the two is worse.
 *
 *  Score and status answer different questions — the score is how healthy the
 *  site is overall, the status is how urgent the worst open issue is — so they
 *  can legitimately disagree. A site scoring 67 (warning band) can be `critical`
 *  because a monitor is down. Taking the worse of the two stops the rail
 *  contradicting the verdict text printed right beneath it.
 */
function healthState(score: number, status: string): ChunkState {
  const fromStatus: ChunkState =
    status === "critical" ? "critical"
    : status === "warning" ? "warning"
    : status === "active" ? "good"
    : "idle";
  const fromScore = scoreBand(score);
  return SEVERITY_RANK[fromStatus] >= SEVERITY_RANK[fromScore] ? fromStatus : fromScore;
}

export function SiteOverviewGrid({ m, websiteId }: { m: OverviewMetrics; websiteId: string }) {
  const perfState = (v: number | null): ChunkState =>
    v === null ? "idle" : v >= 90 ? "good" : v >= 50 ? "warning" : "critical";

  const uptimeState: ChunkState =
    m.uptime.monitors === 0 ? "idle"
    : m.uptime.down > 0 ? "critical"
    : m.uptime.degraded > 0 || (m.uptime.pct !== null && m.uptime.pct < 99) ? "warning"
    : "good";

  const changeState: ChunkState =
    m.changelog.critical + m.changelog.high > 0 ? "critical"
    : m.changelog.medium > 0 ? "warning"
    : m.changelog.pending > 0 ? "warning"
    : "good";

  const securityState: ChunkState =
    m.security.critical > 0 ? "critical"
    : m.security.high > 0 || m.security.phpErrors > 0 ? "warning"
    : m.security.grade && !["A", "A+", "B"].includes(m.security.grade) ? "warning"
    : "good";

  const seoState: ChunkState =
    !m.seo.checked ? "idle"
    : m.seo.robotsBlocked || m.seo.indexable === false ? "critical"
    : m.seo.noindex > 0 ? "warning"
    : "good";

  const scriptsState: ChunkState =
    m.scripts.total === 0 ? "idle" : m.scripts.unknown > 0 ? "warning" : "good";

  const formsState: ChunkState =
    m.forms.total === 0 ? "idle" : m.forms.broken > 0 ? "critical" : "good";

  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <Chunk
        websiteId={websiteId} tab="overview" label="Health" icon={Activity}
        value={m.health.score} unit="/ 100"
        state={healthState(m.health.score, m.health.status)}
        verdict={`Site is ${m.health.status}`}
        aside={<ScoreGauge value={m.health.score} state={healthState(m.health.score, m.health.status)} />}
      />

      <Chunk
        websiteId={websiteId} tab="scripts" label="Scripts" icon={Code2}
        value={m.scripts.total} unit={m.scripts.total === 1 ? "script" : "scripts"}
        state={scriptsState}
        verdict={
          m.scripts.total === 0 ? "Nothing detected yet"
          : m.scripts.unknown > 0 ? `${m.scripts.unknown} unrecognised`
          : "All recognised"
        }
      >
        <SplitBar parts={[
          { value: m.scripts.total - m.scripts.unknown, className: "bg-emerald-500", label: "Recognised" },
          { value: m.scripts.unknown, className: "bg-amber-500", label: "Unrecognised" },
        ]} />
        <span className="text-xs text-muted-foreground">
          {m.scripts.categories} categor{m.scripts.categories === 1 ? "y" : "ies"}
        </span>
      </Chunk>

      <Chunk
        websiteId={websiteId} tab="forms" label="Forms" icon={FileInput}
        value={m.forms.total} unit={m.forms.total === 1 ? "form" : "forms"}
        state={formsState}
        verdict={
          m.forms.total === 0 ? "None detected"
          : m.forms.broken > 0 ? `${m.forms.broken} failing in last 7d`
          : "All submitting"
        }
      >
        <SplitBar parts={[
          { value: Math.max(0, m.forms.total - m.forms.broken), className: "bg-emerald-500", label: "Working" },
          { value: m.forms.broken, className: "bg-red-500", label: "Failing" },
        ]} />
      </Chunk>

      <Chunk
        websiteId={websiteId} tab="uptime" label="Uptime & Downtime" icon={Activity}
        value={m.uptime.pct === null ? "—" : `${m.uptime.pct.toFixed(1)}%`}
        unit={m.uptime.pct === null ? undefined : "30 days"}
        state={uptimeState}
        verdict={
          m.uptime.monitors === 0 ? "No monitors yet"
          : m.uptime.down > 0 ? `${m.uptime.down} down now`
          : m.uptime.degraded > 0 ? `${m.uptime.degraded} degraded`
          : "All responding"
        }
      >
        {m.uptime.recent.length > 0
          ? <StatusStrip statuses={m.uptime.recent} />
          : <div className="h-1.5 w-full rounded-full bg-muted" />}
        <span className="text-xs text-muted-foreground">
          {m.uptime.monitors} monitor{m.uptime.monitors === 1 ? "" : "s"}
          {m.uptime.recent.length > 0 && " · last 24 checks"}
        </span>
      </Chunk>

      <Chunk
        websiteId={websiteId} tab="performance" label="Performance" icon={Gauge}
        value={m.performance.mobile ?? "—"} unit={m.performance.mobile === null ? undefined : "mobile"}
        state={perfState(m.performance.mobile)}
        verdict={
          m.performance.mobile === null ? "Not measured yet"
          : m.performance.mobile >= 90 ? "Fast on mobile"
          : m.performance.mobile >= 50 ? "Needs work on mobile"
          : "Slow on mobile"
        }
      >
        <div className="space-y-1.5">
          <Meter value={m.performance.mobile ?? 0} state={perfState(m.performance.mobile)} />
          <span className="flex items-center justify-between text-xs text-muted-foreground">
            Desktop
            <span className="font-semibold tabular-nums text-foreground">
              {m.performance.desktop ?? "—"}
            </span>
          </span>
        </div>
      </Chunk>

      <Chunk
        websiteId={websiteId} tab="changelog" label="Change Log" icon={History}
        value={m.changelog.pending} unit="pending"
        state={changeState}
        verdict={
          m.changelog.pending === 0 ? "Nothing to review"
          : m.changelog.critical + m.changelog.high > 0
            ? `${m.changelog.critical + m.changelog.high} need attention`
            : `${m.changelog.pending} awaiting review`
        }
      >
        <SplitBar parts={[
          { value: m.changelog.critical, className: "bg-red-600", label: "Critical" },
          { value: m.changelog.high, className: "bg-red-400", label: "High" },
          { value: m.changelog.medium, className: "bg-amber-500", label: "Medium" },
          { value: m.changelog.low, className: "bg-blue-400", label: "Low" },
        ]} />
      </Chunk>

      <Chunk
        websiteId={websiteId} tab="security" label="Security" icon={ShieldCheck}
        value={m.security.critical + m.security.high + m.security.other}
        unit="vulnerabilities"
        state={securityState}
        verdict={
          m.security.critical > 0 ? `${m.security.critical} critical`
          : m.security.high > 0 ? `${m.security.high} high severity`
          : m.security.phpErrors > 0 ? `${m.security.phpErrors} PHP errors`
          : "No known issues"
        }
      >
        <SplitBar parts={[
          { value: m.security.critical, className: "bg-red-600", label: "Critical" },
          { value: m.security.high, className: "bg-red-400", label: "High" },
          { value: m.security.other, className: "bg-amber-500", label: "Medium/Low" },
        ]} />
        <span className="flex items-center justify-between text-xs text-muted-foreground">
          Security headers
          <span className="font-semibold text-foreground">{m.security.grade || "—"}</span>
        </span>
      </Chunk>

      <Chunk
        websiteId={websiteId} tab="seo" label="SEO" icon={Search}
        value={m.seo.checked ? m.seo.sitemapPages : "—"}
        unit={m.seo.checked ? "sitemap pages" : undefined}
        state={seoState}
        verdict={
          !m.seo.checked ? "Not scanned yet"
          : m.seo.robotsBlocked ? "robots.txt blocks crawlers"
          : m.seo.indexable === false ? "Homepage not indexable"
          : m.seo.noindex > 0 ? `${m.seo.noindex} noindex page${m.seo.noindex === 1 ? "" : "s"}`
          : "Indexable"
        }
      >
        <span className="flex items-center justify-between text-xs text-muted-foreground">
          Homepage
          <span className="font-semibold text-foreground">
            {m.seo.indexable === null ? "—" : m.seo.indexable ? "Indexable" : "Blocked"}
          </span>
        </span>
      </Chunk>
    </div>
  );
}
