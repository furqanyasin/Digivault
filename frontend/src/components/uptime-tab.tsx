import Link from "next/link";
import { Activity, ExternalLink, MonitorCheck } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { MonitorSparkline } from "@/components/monitor-sparkline";
import type { Monitor } from "@/lib/api";
import { fmtDateTime } from "@/lib/utils";

const STATUS_VARIANT: Record<string, "success" | "destructive" | "warning" | "secondary"> = {
  up: "success",
  down: "destructive",
  degraded: "warning",
  paused: "secondary",
  pending: "secondary",
};

function pct(v: number | null): string {
  return v === null || v === undefined ? "—" : `${v}%`;
}

export function UptimeTab({ monitors, websiteId }: { monitors: Monitor[]; websiteId: string }) {
  if (monitors.length === 0) {
    return (
      <div className="py-16 flex flex-col items-center gap-3 text-center">
        <Activity className="h-10 w-10 text-muted-foreground" />
        <p className="font-medium">No uptime monitors for this website yet</p>
        <p className="text-sm text-muted-foreground max-w-sm">
          Add an HTTP, ping, port, or SSL monitor to track this site&apos;s availability.
        </p>
        <Link
          href={`/monitors/new?website=${websiteId}`}
          className="text-sm text-blue-600 hover:underline inline-flex items-center gap-1"
        >
          <MonitorCheck className="h-4 w-4" /> Add a monitor
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Monitor</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Last 20 checks</TableHead>
            <TableHead className="text-right">24h</TableHead>
            <TableHead className="text-right">7d</TableHead>
            <TableHead className="text-right">30d</TableHead>
            <TableHead>Last checked</TableHead>
            <TableHead />
          </TableRow>
        </TableHeader>
        <TableBody>
          {monitors.map((m) => (
            <TableRow key={m.id}>
              <TableCell>
                <div className="font-medium text-sm">{m.name}</div>
                <div className="font-mono text-xs text-muted-foreground truncate max-w-[220px]" title={m.url}>
                  {m.monitor_type.toUpperCase()} · {m.url}
                </div>
              </TableCell>
              <TableCell>
                <Badge variant={STATUS_VARIANT[m.status] ?? "secondary"} className="capitalize">
                  {m.status}
                </Badge>
              </TableCell>
              <TableCell><MonitorSparkline statuses={m.recent_statuses} /></TableCell>
              <TableCell className="text-right text-sm">{pct(m.uptime_24h)}</TableCell>
              <TableCell className="text-right text-sm">{pct(m.uptime_7d)}</TableCell>
              <TableCell className="text-right text-sm">{pct(m.uptime_30d)}</TableCell>
              <TableCell className="text-xs text-muted-foreground whitespace-nowrap">
                {m.last_checked_at ? fmtDateTime(m.last_checked_at) : "—"}
              </TableCell>
              <TableCell>
                <Link
                  href={`/monitors/${m.id}`}
                  className="text-xs text-muted-foreground hover:text-foreground underline inline-flex items-center gap-1"
                >
                  Details <ExternalLink className="h-3 w-3" />
                </Link>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <div className="px-1">
        <Link
          href={`/monitors/new?website=${websiteId}`}
          className="text-sm text-blue-600 hover:underline inline-flex items-center gap-1"
        >
          <MonitorCheck className="h-4 w-4" /> Add another monitor
        </Link>
      </div>
    </div>
  );
}
