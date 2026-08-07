"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  CalendarClock, RefreshCw, Globe, ShieldCheck, Server,
  AlertTriangle, Clock, CalendarDays, ListChecks,
} from "lucide-react";
import { RenewalUrgencyBars, type UrgencyRow } from "@/components/charts/renewal-urgency-bars";

/** How far ahead the page looks. The website-sourced endpoints filter by this;
 *  client-entered dates are filtered to the same window here so both sources
 *  describe the same period — otherwise one card silently reaches further than
 *  the others. */
const HORIZON_DAYS = 90;

interface ExpiringItem {
  id: string;
  name: string;
  domain: string;
  days_until_expiry: number | null;
}

interface ClientRow {
  id: string;
  name: string;
  website_url: string;
  hosting_renewal_date: string | null;
  domain_renewal_date: string | null;
}

interface RenewalRow {
  key: string;
  label: string;
  sub: string;
  days: number | null;
  /** Where the date came from — auto lookup or a date typed on the client. */
  source: "auto" | "client";
}

function unwrap(env: unknown): unknown {
  const e = env as { data?: unknown };
  return e?.data ?? env;
}

function asList<T>(value: unknown): T[] {
  if (Array.isArray(value)) return value as T[];
  const v = value as { results?: T[] } | null;
  return v?.results ?? [];
}

/** Normalise a URL/domain to a bare host for cross-source matching. */
function normDomain(url: string | null): string {
  if (!url) return "";
  return url
    .toLowerCase()
    .trim()
    .replace(/^https?:\/\//, "")
    .replace(/^www\./, "")
    .split("/")[0];
}

function daysUntil(dateStr: string | null): number | null {
  if (!dateStr) return null;
  const ms = new Date(dateStr).getTime() - Date.now();
  return Math.floor(ms / (1000 * 60 * 60 * 24));
}

/** Four urgency states, in the order they matter. `overdue` and `critical` are
 *  the "top priority" band the page paints red. */
type Urgency = "overdue" | "critical" | "soon" | "later";

function urgencyOf(days: number | null): Urgency {
  if (days === null) return "later";
  if (days < 0) return "overdue";
  if (days <= 7) return "critical";
  if (days <= 30) return "soon";
  return "later";
}

const isTopPriority = (u: Urgency) => u === "overdue" || u === "critical";

function urgencyVariant(u: Urgency): "destructive" | "warning" | "secondary" {
  if (isTopPriority(u)) return "destructive";
  if (u === "soon") return "warning";
  return "secondary";
}

function urgencyLabel(days: number | null): string {
  if (days === null) return "—";
  if (days < 0) return `Expired ${Math.abs(days)}d ago`;
  if (days === 0) return "Due today";
  return `${days}d left`;
}

function sortByDays(rows: RenewalRow[]): RenewalRow[] {
  return [...rows].sort((a, b) => {
    if (a.days === null) return 1;
    if (b.days === null) return -1;
    return a.days - b.days;
  });
}

/** Merge an auto-detected list with client-entered dates for the same concept.
 *  The auto lookup wins: it is the registrar's own answer, where the client date
 *  is typed from memory. A client row only appears for a domain the auto source
 *  didn't cover, which is what stops the two showing up as duplicate cards. */
function mergeSources(auto: RenewalRow[], manual: RenewalRow[]): RenewalRow[] {
  const seen = new Set(auto.map((r) => normDomain(r.sub)).filter(Boolean));
  const merged = [...auto];
  for (const row of manual) {
    const key = normDomain(row.sub);
    if (key && seen.has(key)) continue;
    if (key) seen.add(key);
    merged.push(row);
  }
  return merged;
}

/* ------------------------------- presentation ------------------------------ */

/** A headline count. Status colour is carried by an icon and a written label as
 *  well as the tint, so the state never rests on colour alone. */
function StatTile({
  icon: Icon, label, value, tone, hint,
}: {
  icon: typeof Globe;
  label: string;
  value: number;
  tone: "critical" | "warning" | "neutral";
  hint: string;
}) {
  const tones = {
    critical: "border-red-200 bg-red-50 text-red-700 dark:border-red-900/60 dark:bg-red-950/40 dark:text-red-300",
    warning: "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900/60 dark:bg-amber-950/40 dark:text-amber-300",
    neutral: "border-border bg-card text-foreground",
  }[tone];
  return (
    <div className={`rounded-xl border p-4 ${tones}`}>
      <div className="flex items-center gap-2 text-xs font-medium">
        <Icon className="h-4 w-4 shrink-0" aria-hidden />
        {label}
      </div>
      <div className="mt-2 text-3xl font-bold tabular-nums leading-none">{value}</div>
      <div className="mt-1.5 text-xs opacity-70">{hint}</div>
    </div>
  );
}

function RenewalSection({
  title, icon: Icon, rows,
}: {
  title: string;
  icon: typeof Globe;
  rows: RenewalRow[];
}) {
  const urgent = rows.filter((r) => isTopPriority(urgencyOf(r.days))).length;
  return (
    <Card className="flex flex-col">
      <CardHeader>
        <CardTitle className="text-base flex items-center gap-2">
          <Icon className="h-4 w-4 shrink-0" aria-hidden />
          {title}
          <span className="text-muted-foreground font-normal">({rows.length})</span>
          {urgent > 0 && (
            <Badge variant="destructive" className="ml-auto text-xs">
              {urgent} urgent
            </Badge>
          )}
        </CardTitle>
      </CardHeader>
      {/* The three lists are wildly uneven — hosting can run to 25 rows while SSL
          has 7. Capping the body keeps the cards side by side instead of one
          column dragging the page down, and scrolls the overflow in place. */}
      <CardContent className="p-0 flex-1 max-h-[26rem] overflow-y-auto overscroll-contain">
        {rows.length === 0 ? (
          <div className="text-center py-8 text-muted-foreground text-sm">Nothing upcoming.</div>
        ) : (
          <table className="w-full text-sm">
            <tbody>
              {sortByDays(rows).map((r) => {
                const u = urgencyOf(r.days);
                const top = isTopPriority(u);
                return (
                  <tr
                    key={r.key}
                    className={
                      top
                        // Top priority reads red at a glance: a left rule plus a
                        // wash. The badge still spells the state out in words.
                        ? "border-b last:border-0 bg-red-50/70 dark:bg-red-950/25 border-l-2 border-l-red-500"
                        : "border-b last:border-0 hover:bg-muted/30"
                    }
                  >
                    <td className="px-4 py-3">
                      <div className={`font-medium ${top ? "text-red-700 dark:text-red-300" : ""}`}>
                        {r.label}
                      </div>
                      <div className="text-xs text-muted-foreground flex items-center gap-1.5">
                        <span className="truncate">{r.sub}</span>
                        {r.source === "client" && (
                          <span
                            className="shrink-0 rounded border px-1 text-[10px] leading-4 text-muted-foreground"
                            title="Date entered on the client record, not detected automatically"
                          >
                            client
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-right align-top">
                      <Badge variant={urgencyVariant(u)} className="text-xs whitespace-nowrap">
                        {top && <AlertTriangle className="mr-1 h-3 w-3" aria-hidden />}
                        {urgencyLabel(r.days)}
                      </Badge>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </CardContent>
    </Card>
  );
}

/* --------------------------------- page ----------------------------------- */

export function RenewalsClient() {
  const [domains, setDomains] = useState<RenewalRow[]>([]);
  const [ssl, setSsl] = useState<RenewalRow[]>([]);
  const [hosting, setHosting] = useState<RenewalRow[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchAll = useCallback(async () => {
    const q = `?days=${HORIZON_DAYS}`;
    const [domRes, sslRes, hostRes, clientsRes] = await Promise.all([
      fetch(`/api/websites/expiring-domains${q}`),
      fetch(`/api/websites/expiring-ssl${q}`),
      fetch(`/api/websites/expiring-hosting${q}`),
      fetch("/api/clients"),
    ]);

    const readAuto = async (res: Response, prefix: string): Promise<RenewalRow[]> => {
      if (!res.ok) return [];
      const items = asList<ExpiringItem>(unwrap(await res.json()));
      return items.map((i) => ({
        key: `${prefix}-${i.id}`,
        label: i.name || i.domain,
        sub: i.domain,
        days: i.days_until_expiry,
        source: "auto" as const,
      }));
    };

    const autoDomains = await readAuto(domRes, "dom");
    const autoHosting = await readAuto(hostRes, "host");
    setSsl(await readAuto(sslRes, "ssl"));

    let clientDomains: RenewalRow[] = [];
    let clientHosting: RenewalRow[] = [];
    if (clientsRes.ok) {
      // /api/clients returns { clients: [...], count }, not a bare array/envelope.
      const json = await clientsRes.json();
      const clients: ClientRow[] = Array.isArray(json?.clients)
        ? json.clients
        : asList<ClientRow>(unwrap(json));

      // Client dates are unbounded, so trim them to the same horizon the
      // website endpoints use. Overdue rows are always kept.
      const inHorizon = (d: number | null) => d !== null && d <= HORIZON_DAYS;
      const toRow = (c: ClientRow, prefix: string, date: string | null): RenewalRow => ({
        key: `${prefix}-${c.id}`,
        label: c.name,
        sub: c.website_url,
        days: daysUntil(date),
        source: "client" as const,
      });

      clientDomains = clients
        .filter((c) => c.domain_renewal_date)
        .map((c) => toRow(c, "client-dom", c.domain_renewal_date))
        .filter((r) => inHorizon(r.days));
      clientHosting = clients
        .filter((c) => c.hosting_renewal_date)
        .map((c) => toRow(c, "client-host", c.hosting_renewal_date))
        .filter((r) => inHorizon(r.days));
    }

    setDomains(mergeSources(autoDomains, clientDomains));
    setHosting(mergeSources(autoHosting, clientHosting));
    setLoading(false);
  }, []);

  useEffect(() => {
    (async () => {
      await Promise.resolve();
      await fetchAll();
    })();
  }, [fetchAll]);

  const all = useMemo(() => [...domains, ...ssl, ...hosting], [domains, ssl, hosting]);
  const countBy = (u: Urgency) => all.filter((r) => urgencyOf(r.days) === u).length;
  const overdue = countBy("overdue");
  const critical = countBy("critical");
  const soon = countBy("soon");

  /** One row per renewal type, split by urgency. Rows are always populated,
   *  unlike time buckets — most renewals sit far out, which left the near bands
   *  of a column chart empty. */
  const urgencyRows: UrgencyRow[] = useMemo(() => {
    const tally = (rows: RenewalRow[]): Omit<UrgencyRow, "label"> => ({
      urgent: rows.filter((r) => isTopPriority(urgencyOf(r.days))).length,
      soon: rows.filter((r) => urgencyOf(r.days) === "soon").length,
      later: rows.filter((r) => urgencyOf(r.days) === "later").length,
    });
    return [
      { label: "Domain", ...tally(domains) },
      { label: "SSL", ...tally(ssl) },
      { label: "Hosting", ...tally(hosting) },
    ];
  }, [domains, ssl, hosting]);

  return (
    <div className="p-8 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight flex items-center gap-2">
            <CalendarClock className="h-7 w-7" />
            Renewal Center
          </h1>
          <p className="text-muted-foreground mt-1">
            Domain, SSL, and hosting renewals for the next {HORIZON_DAYS} days — most urgent first.
          </p>
        </div>
        <button
          onClick={fetchAll}
          className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground"
        >
          <RefreshCw className="h-4 w-4" />
          Refresh
        </button>
      </div>

      {loading ? (
        <div className="text-center py-12 text-muted-foreground text-sm">Loading…</div>
      ) : (
        <>
          {/* Headline counts — what needs doing now, before the detail. */}
          <div className="grid gap-4 grid-cols-2 lg:grid-cols-4">
            <StatTile
              icon={AlertTriangle} label="Overdue" value={overdue}
              tone={overdue > 0 ? "critical" : "neutral"}
              hint="Already past the renewal date"
            />
            <StatTile
              icon={Clock} label="Due within 7 days" value={critical}
              tone={critical > 0 ? "critical" : "neutral"}
              hint="Top priority this week"
            />
            <StatTile
              icon={CalendarDays} label="Due in 8–30 days" value={soon}
              tone={soon > 0 ? "warning" : "neutral"}
              hint="Plan these in"
            />
            <StatTile
              icon={ListChecks} label="Tracked total" value={all.length}
              tone="neutral"
              hint={`Across the next ${HORIZON_DAYS} days`}
            />
          </div>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Renewals by urgency</CardTitle>
              <p className="text-sm text-muted-foreground">
                How much of each renewal type needs attention now.
              </p>
            </CardHeader>
            <CardContent>
              <RenewalUrgencyBars rows={urgencyRows} />
            </CardContent>
          </Card>

          {/* One card per renewal type — three across on a wide screen. */}
          <div className="grid gap-6 md:grid-cols-2 xl:grid-cols-3">
            <RenewalSection title="Domain Renewal" icon={Globe} rows={domains} />
            <RenewalSection title="SSL Renewal" icon={ShieldCheck} rows={ssl} />
            <RenewalSection title="Hosting Renewal" icon={Server} rows={hosting} />
          </div>
        </>
      )}
    </div>
  );
}
