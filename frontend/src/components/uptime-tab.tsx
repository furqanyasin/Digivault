import Link from "next/link";
import { Activity, ExternalLink, Globe, MonitorCheck } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { MonitorSparkline } from "@/components/monitor-sparkline";
import type { Monitor } from "@/lib/api";
import { fmtDateTime } from "@/lib/utils";

type StatusPageSummary = { slug: string; name: string; status: string; monitor_count: number };

const STATUS_VARIANT: Record<string, "success" | "destructive" | "warning" | "secondary"> = {
  up: "success",
  down: "destructive",
  degraded: "warning",
  paused: "secondary",
  pending: "secondary",
};

const PAGE_STATUS_STYLE: Record<string, string> = {
  operational: "text-emerald-600",
  degraded: "text-amber-600",
  outage: "text-red-600",
};

function pct(v: number | null): string {
  return v === null || v === undefined ? "—" : `${v}%`;
}

function PublicStatusPages({ statusPage }: { statusPage: StatusPageSummary | null }) {
  return (
    <div className="border-t px-4 py-4 space-y-2">
      <div className="flex items-center gap-2 text-sm font-medium">
        <Globe className="h-4 w-4 text-muted-foreground" />
        Public Status Pages
      </div>
      {statusPage ? (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
          <Link
            href={`/status/${statusPage.slug}`}
            target="_blank"
            className="inline-flex items-center gap-1 text-blue-600 hover:underline font-mono"
          >
            /status/{statusPage.slug} <ExternalLink className="h-3 w-3" />
          </Link>
          <span className="text-muted-foreground">{statusPage.name}</span>
          <span className={`capitalize ${PAGE_STATUS_STYLE[statusPage.status] ?? "text-muted-foreground"}`}>
            · {statusPage.status}
          </span>
          <span className="text-muted-foreground">
            · {statusPage.monitor_count} monitor{statusPage.monitor_count !== 1 ? "s" : ""}
          </span>
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">
          This website isn&apos;t on a public status page yet.{" "}
          <Link href="/status-pages" className="text-blue-600 hover:underline">
            Create one
          </Link>{" "}
          to share live uptime with clients.
        </p>
      )}
    </div>
  );
}

export function UptimeTab({
  monitors,
  websiteId,
  statusPage = null,
}: {
  monitors: Monitor[];
  websiteId: string;
  statusPage?: StatusPageSummary | null;
}) {
  if (monitors.length === 0) {
    return (
      <div>
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
        <PublicStatusPages statusPage={statusPage} />
      </div>
    );
  }

  return (
    <div>
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
      <PublicStatusPages statusPage={statusPage} />
    </div>
  );
}
