"use client";

import { useCallback, useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { CalendarClock, RefreshCw, Globe, ShieldCheck, Server, FileSignature } from "lucide-react";

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
  contract_renewal_date: string | null;
}

interface RenewalRow {
  key: string;
  label: string;
  sub: string;
  days: number | null;
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

function daysUntil(dateStr: string | null): number | null {
  if (!dateStr) return null;
  const ms = new Date(dateStr).getTime() - Date.now();
  return Math.floor(ms / (1000 * 60 * 60 * 24));
}

function urgencyVariant(days: number | null): "destructive" | "warning" | "secondary" {
  if (days === null) return "secondary";
  if (days <= 7) return "destructive";
  if (days <= 30) return "warning";
  return "secondary";
}

function urgencyLabel(days: number | null): string {
  if (days === null) return "—";
  if (days < 0) return `Expired ${Math.abs(days)}d ago`;
  return `${days}d left`;
}

function sortByDays(rows: RenewalRow[]): RenewalRow[] {
  return [...rows].sort((a, b) => {
    if (a.days === null) return 1;
    if (b.days === null) return -1;
    return a.days - b.days;
  });
}

function RenewalSection({
  title,
  icon: Icon,
  rows,
}: {
  title: string;
  icon: typeof Globe;
  rows: RenewalRow[];
}) {
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base flex items-center gap-2">
          <Icon className="h-4 w-4" />
          {title}
          <span className="text-muted-foreground font-normal">({rows.length})</span>
        </CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        {rows.length === 0 ? (
          <div className="text-center py-8 text-muted-foreground text-sm">Nothing upcoming.</div>
        ) : (
          <table className="w-full text-sm">
            <tbody>
              {sortByDays(rows).map((r) => (
                <tr key={r.key} className="border-b last:border-0 hover:bg-muted/30">
                  <td className="px-4 py-3">
                    <div className="font-medium">{r.label}</div>
                    <div className="text-xs text-muted-foreground">{r.sub}</div>
                  </td>
                  <td className="px-4 py-3 text-right">
                    <Badge variant={urgencyVariant(r.days)} className="text-xs">
                      {urgencyLabel(r.days)}
                    </Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </CardContent>
    </Card>
  );
}

export default function RenewalsPage() {
  const [domains, setDomains] = useState<RenewalRow[]>([]);
  const [ssl, setSsl] = useState<RenewalRow[]>([]);
  const [hosting, setHosting] = useState<RenewalRow[]>([]);
  const [contracts, setContracts] = useState<RenewalRow[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchAll = useCallback(async () => {
    const [domRes, sslRes, clientsRes] = await Promise.all([
      fetch("/api/websites/expiring-domains"),
      fetch("/api/websites/expiring-ssl"),
      fetch("/api/clients"),
    ]);

    if (domRes.ok) {
      const items = asList<ExpiringItem>(unwrap(await domRes.json()));
      setDomains(
        items.map((i) => ({
          key: `dom-${i.id}`,
          label: i.name || i.domain,
          sub: i.domain,
          days: i.days_until_expiry,
        }))
      );
    }
    if (sslRes.ok) {
      const items = asList<ExpiringItem>(unwrap(await sslRes.json()));
      setSsl(
        items.map((i) => ({
          key: `ssl-${i.id}`,
          label: i.name || i.domain,
          sub: i.domain,
          days: i.days_until_expiry,
        }))
      );
    }
    if (clientsRes.ok) {
      const clients = asList<ClientRow>(unwrap(await clientsRes.json()));
      setHosting(
        clients
          .filter((c) => c.hosting_renewal_date)
          .map((c) => ({
            key: `host-${c.id}`,
            label: c.name,
            sub: c.website_url,
            days: daysUntil(c.hosting_renewal_date),
          }))
      );
      setContracts(
        clients
          .filter((c) => c.contract_renewal_date)
          .map((c) => ({
            key: `contract-${c.id}`,
            label: c.name,
            sub: c.website_url,
            days: daysUntil(c.contract_renewal_date),
          }))
      );
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    (async () => {
      await Promise.resolve();
      await fetchAll();
    })();
  }, [fetchAll]);

  return (
    <div className="p-8 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight flex items-center gap-2">
            <CalendarClock className="h-7 w-7" />
            Renewal Center
          </h1>
          <p className="text-muted-foreground mt-1">
            Domains, SSL, hosting, and contracts — sorted by urgency.
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
        <div className="grid gap-6 md:grid-cols-2">
          <RenewalSection title="Domains" icon={Globe} rows={domains} />
          <RenewalSection title="SSL Certificates" icon={ShieldCheck} rows={ssl} />
          <RenewalSection title="Hosting" icon={Server} rows={hosting} />
          <RenewalSection title="Contracts" icon={FileSignature} rows={contracts} />
        </div>
      )}
    </div>
  );
}
