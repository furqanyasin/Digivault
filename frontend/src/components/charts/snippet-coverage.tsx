import Link from "next/link";
import { AlertTriangle, CheckCircle2, Clock } from "lucide-react";
import type { Website } from "@/lib/api";
import { fmtDate } from "@/lib/utils";

const STALE_DAYS = 7;

/** How much of the fleet is actually reporting.
 *
 *  A single ratio against a limit, so this is a METER, not a chart — a two-slice
 *  pie or a one-bar bar chart would both be the wrong form. The track is
 *  segmented because "silent" splits into two genuinely different problems:
 *  a site that never reported (snippet probably not installed) and one that
 *  stopped (installed, then broke or lost traffic).
 *
 *  Ingest is traffic-driven, so this is the honest measure of how much of the
 *  dashboard's data is current at all.
 */
export function SnippetCoverage({
  websites,
  nowMs,
}: {
  websites: Website[];
  /** Passed in rather than read here: reading the clock during render makes the
   *  component impure, so the caller supplies the reference instant. */
  nowMs: number;
}) {
  const cutoff = nowMs - STALE_DAYS * 24 * 60 * 60 * 1000;

  const never = websites.filter((w) => !w.last_seen_at);
  const stale = websites.filter(
    (w) => w.last_seen_at && new Date(w.last_seen_at).getTime() < cutoff
  );
  const live = websites.filter(
    (w) => w.last_seen_at && new Date(w.last_seen_at).getTime() >= cutoff
  );
  const total = websites.length;

  if (total === 0) {
    return <p className="py-10 text-center text-sm text-muted-foreground">No websites yet.</p>;
  }

  const pct = (n: number) => (n / total) * 100;
  const segments = [
    { key: "live", label: "Reporting", n: live.length, bar: "bg-emerald-500", dot: "bg-emerald-500" },
    { key: "stale", label: `Silent >${STALE_DAYS}d`, n: stale.length, bar: "bg-amber-400", dot: "bg-amber-400" },
    { key: "never", label: "Never reported", n: never.length, bar: "bg-slate-400", dot: "bg-slate-400" },
  ].filter((s) => s.n > 0);

  // Worst first: never-reported outranks stale, then oldest contact.
  const needsSnippet = [...never, ...stale].slice(0, 4);

  return (
    <div className="space-y-4">
      <div>
        <div className="flex items-end justify-between gap-2">
          <p className="text-2xl font-semibold leading-none">
            {Math.round(pct(live.length))}%
            <span className="ml-1.5 text-sm font-normal text-muted-foreground">
              of {total} reporting
            </span>
          </p>
        </div>

        {/* Segmented meter. 2px surface gaps do the separating, not borders. */}
        <div
          className="mt-2 flex h-2 w-full gap-0.5 overflow-hidden rounded-full bg-muted"
          role="progressbar"
          aria-valuenow={live.length}
          aria-valuemin={0}
          aria-valuemax={total}
          aria-label={`${live.length} of ${total} websites reporting`}
        >
          {segments.map((s) => (
            <div key={s.key} className={s.bar} style={{ width: `${pct(s.n)}%` }} />
          ))}
        </div>

        <ul className="mt-2.5 flex flex-wrap gap-x-4 gap-y-1">
          {segments.map((s) => (
            <li key={s.key} className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <span className={`h-2 w-2 shrink-0 rounded-full ${s.dot}`} aria-hidden />
              {s.label}
              <span className="font-semibold tabular-nums text-foreground">{s.n}</span>
            </li>
          ))}
        </ul>
      </div>

      {needsSnippet.length === 0 ? (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-500" />
          Every site has reported in the last {STALE_DAYS} days.
        </p>
      ) : (
        <div className="border-t pt-3">
          <p className="mb-2 text-xs font-medium text-muted-foreground">
            Not sending data
          </p>
          <ul className="divide-y">
            {needsSnippet.map((site) => (
              <li key={site.id} className="flex items-center gap-2 py-1.5 first:pt-0 last:pb-0">
                {site.last_seen_at ? (
                  <Clock className="h-3.5 w-3.5 shrink-0 text-amber-500" aria-hidden />
                ) : (
                  <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-slate-400" aria-hidden />
                )}
                <Link
                  href={`/websites/${site.id}`}
                  className="min-w-0 flex-1 truncate text-sm hover:underline"
                >
                  {site.name || site.domain}
                </Link>
                <span className="shrink-0 text-xs text-muted-foreground">
                  {site.last_seen_at ? `last seen ${fmtDate(site.last_seen_at)}` : "no data yet"}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
