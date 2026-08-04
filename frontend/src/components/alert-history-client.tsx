"use client";

import { useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { History, AlertTriangle, Search } from "lucide-react";
import { fmtDateTime } from "@/lib/utils";
import type { Notification } from "@/lib/api";

const PAGE = 25;

const isCritical = (s: string) => s === "critical" || s === "high";

function severityVariant(s: string): "destructive" | "warning" | "secondary" {
  if (isCritical(s)) return "destructive";
  if (s === "medium") return "warning";
  return "secondary";
}

function deliveryVariant(s: string): "success" | "destructive" | "secondary" {
  if (s === "sent" || s === "delivered") return "success";
  if (s === "failed" || s === "error") return "destructive";
  return "secondary";
}

const CONTROL = "border rounded-md px-2 py-1.5 text-sm bg-background text-foreground";

/** Every alert that was actually delivered, newest first — the audit trail for
 *  "did we tell anyone about this?", which the unacknowledged feed above can't
 *  answer because it drops rows as soon as they are acknowledged. */
export function AlertHistoryClient({
  notifications,
  clientByWebsite,
}: {
  notifications: Notification[];
  clientByWebsite: Record<string, string>;
}) {
  const [query, setQuery] = useState("");
  const [client, setClient] = useState("");
  const [limit, setLimit] = useState(PAGE);

  const rows = useMemo(
    () =>
      notifications.map((n) => ({
        ...n,
        clientName: (n.website && clientByWebsite[n.website]) || "",
      })),
    [notifications, clientByWebsite]
  );

  const clients = useMemo(
    () => [...new Set(rows.map((r) => r.clientName).filter(Boolean))].sort(),
    [rows]
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return rows.filter((r) => {
      if (client && r.clientName !== client) return false;
      if (!q) return true;
      return [r.website_name, r.clientName, r.change_description, r.channel, r.delivery_status]
        .join(" ")
        .toLowerCase()
        .includes(q);
    });
  }, [rows, query, client]);

  const isFiltered = Boolean(query || client);
  const visible = filtered.slice(0, limit);

  return (
    <Card>
      <CardHeader className="gap-3">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <CardTitle className="flex items-center gap-2">
            <History className="h-4 w-4" aria-hidden />
            Alert History ({filtered.length}
            {isFiltered && (
              <span className="text-muted-foreground font-normal"> of {rows.length}</span>
            )}
            )
          </CardTitle>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative flex-1 min-w-[220px]">
            <Search
              className="absolute left-2 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
              aria-hidden
            />
            <input
              type="search"
              aria-label="Search alert history"
              placeholder="Search site, description, or channel…"
              value={query}
              onChange={(e) => { setQuery(e.target.value); setLimit(PAGE); }}
              className={`${CONTROL} w-full pl-8`}
            />
          </div>
          <select
            aria-label="Filter history by client"
            value={client}
            onChange={(e) => { setClient(e.target.value); setLimit(PAGE); }}
            className={CONTROL}
          >
            <option value="">All clients</option>
            {clients.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
          {isFiltered && (
            <button
              type="button"
              onClick={() => { setQuery(""); setClient(""); setLimit(PAGE); }}
              className="text-sm text-muted-foreground underline hover:text-foreground"
            >
              Clear
            </button>
          )}
        </div>
      </CardHeader>

      <CardContent className="p-0">
        {rows.length === 0 ? (
          <div className="p-10 text-center text-sm text-muted-foreground">
            No alerts have been delivered yet. Alerts appear here once a rule fires.
          </div>
        ) : filtered.length === 0 ? (
          <div className="p-10 text-center text-sm text-muted-foreground">
            No history matches these filters.
          </div>
        ) : (
          <>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Severity</TableHead>
                  <TableHead>Website</TableHead>
                  <TableHead>Client</TableHead>
                  <TableHead>What happened</TableHead>
                  <TableHead>Channel</TableHead>
                  <TableHead>Delivery</TableHead>
                  <TableHead>Sent</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {visible.map((n) => {
                  const crit = isCritical(n.change_severity);
                  return (
                    <TableRow
                      key={n.id}
                      className={
                        crit
                          ? "bg-red-50/70 dark:bg-red-950/25 border-l-2 border-l-red-500 hover:bg-red-50"
                          : undefined
                      }
                    >
                      <TableCell>
                        {n.change_severity ? (
                          <Badge variant={severityVariant(n.change_severity)} className="gap-1">
                            {crit && <AlertTriangle className="h-3 w-3" aria-hidden />}
                            {n.change_severity}
                          </Badge>
                        ) : (
                          <span className="text-muted-foreground text-sm">—</span>
                        )}
                      </TableCell>
                      <TableCell
                        className={`text-sm font-medium max-w-[160px] truncate ${crit ? "text-red-700 dark:text-red-300" : ""}`}
                      >
                        {n.website_name || "—"}
                      </TableCell>
                      <TableCell className="text-sm text-muted-foreground max-w-[140px] truncate">
                        {n.clientName || "—"}
                      </TableCell>
                      <TableCell
                        className="text-sm text-muted-foreground max-w-[260px] truncate"
                        title={n.change_description}
                      >
                        {n.change_description || "—"}
                      </TableCell>
                      <TableCell className="capitalize text-sm">{n.channel}</TableCell>
                      <TableCell>
                        <Badge variant={deliveryVariant(n.delivery_status)}>
                          {n.delivery_status || "unknown"}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-muted-foreground text-sm whitespace-nowrap">
                        {fmtDateTime(n.delivered_at ?? n.created_at)}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
            {filtered.length > visible.length && (
              <div className="border-t p-3 text-center">
                <button
                  type="button"
                  onClick={() => setLimit((l) => l + PAGE)}
                  className="text-sm text-muted-foreground underline hover:text-foreground"
                >
                  Show {Math.min(PAGE, filtered.length - visible.length)} more
                  <span className="ml-1">({visible.length} of {filtered.length})</span>
                </button>
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
