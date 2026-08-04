"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Globe, LayoutGrid, List, Search, AlertTriangle, Clock, ChevronLeft, ChevronRight, Star, X } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { WebsiteRowMenu } from "@/components/website-row-menu";
import { AddClientWebsiteButton } from "@/components/add-client-website-button";
import type { Website } from "@/lib/api";
import { fmtDate, fmtDateTime } from "@/lib/utils";
import { cn } from "@/lib/utils";

const STATUS_LABEL: Record<string, string> = {
  active: "Healthy",
  warning: "Warning",
  critical: "Critical",
  inactive: "Inactive",
};

const STATUS_BADGE: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  active: "default",
  warning: "secondary",
  critical: "destructive",
  inactive: "outline",
};

const STATUS_DOT: Record<string, string> = {
  active: "bg-emerald-500",
  warning: "bg-amber-500",
  critical: "bg-red-500",
  inactive: "bg-slate-400",
};

const STATUS_BAR: Record<string, string> = {
  active: "bg-emerald-500",
  warning: "bg-amber-400",
  critical: "bg-red-500",
  inactive: "bg-slate-300",
};

function formatUptime(v: number | null): string {
  if (v == null) return "—";
  return Number.isInteger(v) ? `${v}%` : `${v.toFixed(2)}%`;
}

function formatSslDays(v: number | null): string {
  if (v == null) return "—";
  if (v < 0) return "Expired";
  return `${v}d`;
}

export interface MissingClient {
  id: string;
  name: string;
  domain: string;
}

const PAGE_SIZES = [25, 50, 100] as const;

export function WebsitesClient({
  websites,
  missingClients = [],
}: {
  websites: Website[];
  missingClients?: MissingClient[];
}) {
  const [query, setQuery] = useState("");
  const [view, setView] = useState<"table" | "cards">("table");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState<25 | 50 | 100>(25);

  // The dashboard's VIP section links here with ?vip=1. Held in state rather
  // than read straight from the URL so the chip's clear button works without a
  // navigation.
  const searchParams = useSearchParams();
  const [vipOnly, setVipOnly] = useState(searchParams.get("vip") === "1");

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    let rows = vipOnly ? websites.filter((w) => w.is_vip) : websites;
    if (q) {
      rows = rows.filter((w) =>
        w.domain?.toLowerCase().includes(q) ||
        w.name?.toLowerCase().includes(q) ||
        w.client_name?.toLowerCase().includes(q)
      );
    }
    return rows;
  }, [websites, query, vipOnly]);

  const missingFiltered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return missingClients;
    return missingClients.filter(
      (c) => c.domain.toLowerCase().includes(q) || c.name.toLowerCase().includes(q)
    );
  }, [missingClients, query]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
  // Searching or resizing can leave `page` past the end of the new result set.
  // Clamp during render rather than correcting it in an effect, which would
  // paint an empty page first and then re-render.
  const safePage = Math.min(page, totalPages);
  const paged = filtered.slice((safePage - 1) * pageSize, safePage * pageSize);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-4">
        <div className="relative w-full max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search websites..."
            value={query}
            onChange={(e) => { setQuery(e.target.value); setPage(1); }}
            className="pl-9"
          />
        </div>
        <button
          type="button"
          onClick={() => { setVipOnly((v) => !v); setPage(1); }}
          aria-pressed={vipOnly}
          className={cn(
            "flex shrink-0 items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition-colors",
            vipOnly
              ? "border-amber-400 bg-amber-50 text-amber-900 dark:bg-amber-950/40 dark:text-amber-200"
              : "text-muted-foreground hover:bg-muted"
          )}
        >
          <Star className={cn("h-3.5 w-3.5", vipOnly && "fill-amber-400 text-amber-500")} />
          VIP only
          {vipOnly && <X className="h-3 w-3" />}
        </button>

        <div className="flex items-center gap-2 text-xs ml-auto mr-2">
          <span className="text-muted-foreground">Per page:</span>
          {PAGE_SIZES.map((ps) => (
            <button
              key={ps}
              type="button"
              onClick={() => { setPageSize(ps); setPage(1); }}
              className={`px-2 py-1 rounded border text-xs ${pageSize === ps ? "bg-primary text-primary-foreground border-primary" : "hover:bg-muted"}`}
            >
              {ps}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-1 rounded-lg border bg-muted/40 p-1">
          <button
            onClick={() => setView("table")}
            className={cn(
              "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
              view === "table" ? "bg-background shadow-sm" : "text-muted-foreground hover:text-foreground"
            )}
          >
            <List className="h-3.5 w-3.5" />
            Table
          </button>
          <button
            onClick={() => setView("cards")}
            className={cn(
              "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
              view === "cards" ? "bg-background shadow-sm" : "text-muted-foreground hover:text-foreground"
            )}
          >
            <LayoutGrid className="h-3.5 w-3.5" />
            Cards
          </button>
        </div>
      </div>

      {missingFiltered.length > 0 && (
        <Card className="border-amber-300 bg-amber-50/40 dark:bg-amber-950/10">
          <CardContent className="p-0">
            <div className="flex items-center gap-2 px-4 py-3 border-b border-amber-200">
              <AlertTriangle className="h-4 w-4 text-amber-600 shrink-0" />
              <p className="text-sm font-medium">
                {missingFiltered.length} client{missingFiltered.length !== 1 ? "s" : ""} not yet
                monitored
              </p>
              <span className="text-xs text-muted-foreground">
                — they have a website URL but no site here.
              </span>
            </div>
            <Table>
              <TableBody>
                {missingFiltered.map((c) => (
                  <TableRow key={c.id}>
                    <TableCell>
                      <span className="flex items-center gap-2 font-medium">
                        <Globe className="h-4 w-4 text-muted-foreground shrink-0" />
                        {c.domain}
                      </span>
                    </TableCell>
                    <TableCell>
                      <Link href={`/clients/${c.id}`} className="text-primary hover:underline text-sm">
                        {c.name}
                      </Link>
                    </TableCell>
                    <TableCell>
                      <Badge variant="warning">Not added</Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      <AddClientWebsiteButton clientId={c.id} clientName={c.name} domain={c.domain} />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      {filtered.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16 gap-2 text-center">
            <p className="text-lg font-medium">No websites found</p>
            <p className="text-muted-foreground text-sm">
              {query ? "Try a different search term." : "Add your first website to start monitoring scripts."}
            </p>
          </CardContent>
        </Card>
      ) : view === "table" ? (
        <Card>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Website</TableHead>
                  <TableHead>Client</TableHead>
                  <TableHead>Uptime (30d)</TableHead>
                  <TableHead>Scripts</TableHead>
                  <TableHead>SSL expires</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {paged.map((site) => (
                  <TableRow key={site.id}>
                    <TableCell>
                      <Link href={`/websites/${site.id}`} className="flex items-center gap-2 font-medium hover:text-primary">
                        <Globe className="h-4 w-4 text-muted-foreground shrink-0" />
                        {site.domain}
                      </Link>
                    </TableCell>
                    <TableCell>
                      {site.client_name ? (
                        <Link href={`/clients/${site.client}`} className="text-primary hover:underline text-sm">
                          {site.client_name}
                        </Link>
                      ) : (
                        <span className="text-muted-foreground text-sm">—</span>
                      )}
                    </TableCell>
                    <TableCell className="text-sm">{formatUptime(site.uptime_30d)}</TableCell>
                    <TableCell className="text-sm">{site.script_count ?? 0}</TableCell>
                    <TableCell className="text-muted-foreground text-sm">
                      {formatSslDays(site.ssl_days_until_expiry)}
                    </TableCell>
                    <TableCell>
                      <Badge variant={STATUS_BADGE[site.status] ?? "outline"}>
                        {STATUS_LABEL[site.status] ?? site.status ?? "Unknown"}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <WebsiteRowMenu id={site.id} name={site.name || site.domain} />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {paged.map((site) => (
            <Card key={site.id} className="hover:border-primary/50 hover:shadow-md transition-all">
              <CardContent className="p-5 space-y-3">
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-2 min-w-0">
                    <span className={`h-2.5 w-2.5 rounded-full shrink-0 ${STATUS_DOT[site.status] ?? "bg-slate-400"}`} />
                    <div className="min-w-0">
                      <Link href={`/websites/${site.id}`} className="font-semibold text-sm truncate hover:text-primary block">
                        {site.name || site.domain}
                      </Link>
                      <p className="text-xs text-muted-foreground font-mono truncate">{site.domain}</p>
                    </div>
                  </div>
                  <WebsiteRowMenu id={site.id} name={site.name || site.domain} />
                </div>

                {site.client_name && (
                  <Link href={`/clients/${site.client}`} className="text-xs text-primary hover:underline block truncate">
                    {site.client_name}
                  </Link>
                )}

                <div className="space-y-1">
                  <div className="flex items-center justify-between text-xs text-muted-foreground">
                    <span>Health</span>
                    <Badge variant={STATUS_BADGE[site.status] ?? "outline"} className="text-xs h-5">
                      {STATUS_LABEL[site.status] ?? site.status ?? "Unknown"}
                    </Badge>
                  </div>
                  <div className="h-1.5 rounded-full bg-muted overflow-hidden">
                    <div
                      className={`h-full rounded-full transition-all ${STATUS_BAR[site.status] ?? "bg-slate-300"}`}
                      style={{ width: `${site.health_score ?? 100}%` }}
                    />
                  </div>
                </div>

                <div className="flex items-center gap-3 text-xs text-muted-foreground flex-wrap">
                  <span>{formatUptime(site.uptime_30d)} uptime</span>
                  <span>{site.script_count ?? 0} scripts</span>
                  <span>SSL {formatSslDays(site.ssl_days_until_expiry)}</span>
                </div>

                <div className="flex items-center gap-3 text-xs text-muted-foreground">
                  {(site.unknown_script_count ?? 0) > 0 && (
                    <span className="flex items-center gap-1 text-red-600 font-semibold">
                      <AlertTriangle className="h-3 w-3" />
                      {site.unknown_script_count} unknown
                    </span>
                  )}
                  {site.last_seen_at && (
                    <span className="ml-auto flex items-center gap-1" title={fmtDateTime(site.last_seen_at)}>
                      <Clock className="h-3 w-3" />
                      {fmtDate(site.last_seen_at)}
                    </span>
                  )}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {totalPages > 1 && (
        <div className="flex items-center justify-between text-sm">
          <span className="text-muted-foreground">
            Page {safePage} of {totalPages} &middot; {filtered.length} total
          </span>
          <div className="flex items-center gap-1">
            <Button variant="outline" size="sm" onClick={() => setPage(1)} disabled={safePage === 1}>«</Button>
            <Button variant="outline" size="sm" onClick={() => setPage(safePage - 1)} disabled={safePage === 1}>
              <ChevronLeft className="h-4 w-4" />
            </Button>
            {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
              const start = Math.max(1, Math.min(safePage - 2, totalPages - 4));
              const p = start + i;
              return (
                <button
                  key={p}
                  type="button"
                  onClick={() => setPage(p)}
                  className={`w-8 h-8 rounded border text-xs ${p === safePage ? "bg-primary text-primary-foreground border-primary" : "hover:bg-muted"}`}
                >
                  {p}
                </button>
              );
            })}
            <Button variant="outline" size="sm" onClick={() => setPage(safePage + 1)} disabled={safePage === totalPages}>
              <ChevronRight className="h-4 w-4" />
            </Button>
            <Button variant="outline" size="sm" onClick={() => setPage(totalPages)} disabled={safePage === totalPages}>»</Button>
          </div>
        </div>
      )}
    </div>
  );
}
