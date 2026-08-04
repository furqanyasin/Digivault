"use client";

import { useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { CheckCircle, AlertTriangle, Search } from "lucide-react";
import { AcknowledgeButton } from "@/components/acknowledge-button";
import { fmtDate } from "@/lib/utils";

export interface FeedChange {
  id: string;
  severity: string;
  change_type: string;
  description: string;
  created_at: string;
  scriptUrl: string;
  websiteId: string;
  websiteName: string;
  clientName: string;
}

const SEVERITY_ORDER: Record<string, number> = {
  critical: 0, high: 1, medium: 2, low: 3,
};

/** Critical and high are the band the page paints red — the same "top priority"
 *  treatment the Renewal Center uses, so urgency reads the same way app-wide. */
const isCritical = (s: string) => s === "critical" || s === "high";

function severityVariant(s: string): "destructive" | "warning" | "secondary" {
  if (isCritical(s)) return "destructive";
  if (s === "medium") return "warning";
  return "secondary";
}

const CONTROL =
  "border rounded-md px-2 py-1.5 text-sm bg-background text-foreground";

export function AlertsFeedClient({ changes }: { changes: FeedChange[] }) {
  const [query, setQuery] = useState("");
  const [client, setClient] = useState("");
  const [severity, setSeverity] = useState("");

  // Only clients that actually have an alert — a filter listing options that
  // match nothing is noise.
  const clients = useMemo(
    () => [...new Set(changes.map((c) => c.clientName).filter(Boolean))].sort(),
    [changes]
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return changes
      .filter((c) => {
        if (client && c.clientName !== client) return false;
        if (severity === "critical" && !isCritical(c.severity)) return false;
        if (severity && severity !== "critical" && c.severity !== severity) return false;
        if (!q) return true;
        // Search everything visible in the row, so what you type matches what
        // you can see.
        return [c.websiteName, c.clientName, c.scriptUrl, c.description, c.change_type]
          .join(" ")
          .toLowerCase()
          .includes(q);
      })
      .sort((a, b) => (SEVERITY_ORDER[a.severity] ?? 4) - (SEVERITY_ORDER[b.severity] ?? 4));
  }, [changes, query, client, severity]);

  const criticalShown = filtered.filter((c) => isCritical(c.severity)).length;
  const isFiltered = Boolean(query || client || severity);

  return (
    <Card>
      <CardHeader className="gap-3">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <CardTitle>
            Unacknowledged Changes ({filtered.length}
            {isFiltered && <span className="text-muted-foreground font-normal"> of {changes.length}</span>})
          </CardTitle>
          {criticalShown > 0 && (
            <Badge variant="destructive" className="gap-1">
              <AlertTriangle className="h-3 w-3" aria-hidden />
              {criticalShown} need attention
            </Badge>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <div className="relative flex-1 min-w-[220px]">
            <Search
              className="absolute left-2 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
              aria-hidden
            />
            <input
              type="search"
              aria-label="Search alerts"
              placeholder="Search site, script, or description…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className={`${CONTROL} w-full pl-8`}
            />
          </div>
          <select
            aria-label="Filter by client"
            value={client}
            onChange={(e) => setClient(e.target.value)}
            className={CONTROL}
          >
            <option value="">All clients</option>
            {clients.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
          <select
            aria-label="Filter by severity"
            value={severity}
            onChange={(e) => setSeverity(e.target.value)}
            className={CONTROL}
          >
            <option value="">All severities</option>
            <option value="critical">Critical &amp; high</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </select>
          {isFiltered && (
            <button
              type="button"
              onClick={() => { setQuery(""); setClient(""); setSeverity(""); }}
              className="text-sm text-muted-foreground underline hover:text-foreground"
            >
              Clear
            </button>
          )}
        </div>
      </CardHeader>

      <CardContent className="p-0">
        {changes.length === 0 ? (
          <div className="p-10 flex flex-col items-center gap-2 text-center">
            <CheckCircle className="h-10 w-10 text-emerald-500" />
            <p className="font-medium">All clear!</p>
            <p className="text-sm text-muted-foreground">
              No unacknowledged changes across any of your sites.
            </p>
          </div>
        ) : filtered.length === 0 ? (
          <div className="p-10 text-center text-sm text-muted-foreground">
            No alerts match these filters.
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Severity</TableHead>
                <TableHead>Website</TableHead>
                <TableHead>Client</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Script</TableHead>
                <TableHead>Description</TableHead>
                <TableHead>Detected</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((change) => {
                const crit = isCritical(change.severity);
                return (
                  <TableRow
                    key={change.id}
                    className={
                      crit
                        ? "bg-red-50/70 dark:bg-red-950/25 border-l-2 border-l-red-500 hover:bg-red-50"
                        : undefined
                    }
                  >
                    <TableCell>
                      <Badge variant={severityVariant(change.severity)} className="gap-1">
                        {crit && <AlertTriangle className="h-3 w-3" aria-hidden />}
                        {change.severity}
                      </Badge>
                    </TableCell>
                    <TableCell
                      className={`text-sm font-medium max-w-[160px] truncate ${crit ? "text-red-700 dark:text-red-300" : ""}`}
                    >
                      {change.websiteName}
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground max-w-[140px] truncate">
                      {change.clientName || "—"}
                    </TableCell>
                    <TableCell className="capitalize font-medium text-sm">{change.change_type}</TableCell>
                    <TableCell className="font-mono text-xs max-w-[180px] truncate" title={change.scriptUrl}>
                      {change.scriptUrl || "—"}
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground max-w-[200px] truncate" title={change.description}>
                      {change.description}
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground whitespace-nowrap">
                      {fmtDate(change.created_at)}
                    </TableCell>
                    <TableCell><AcknowledgeButton changeId={change.id} /></TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
