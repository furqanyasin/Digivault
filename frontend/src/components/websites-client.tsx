"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { Globe, LayoutGrid, List, Search, AlertTriangle, Clock } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { WebsiteRowMenu } from "@/components/website-row-menu";
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

export function WebsitesClient({ websites }: { websites: Website[] }) {
  const [query, setQuery] = useState("");
  const [view, setView] = useState<"table" | "cards">("table");

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return websites;
    return websites.filter((w) =>
      w.domain?.toLowerCase().includes(q) ||
      w.name?.toLowerCase().includes(q) ||
      w.client_name?.toLowerCase().includes(q)
    );
  }, [websites, query]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-4">
        <div className="relative w-full max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search websites..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="pl-9"
          />
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
                {filtered.map((site) => (
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
          {filtered.map((site) => (
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
    </div>
  );
}
