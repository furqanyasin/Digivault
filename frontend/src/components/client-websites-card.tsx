import Link from "next/link";
import { Globe, Plus } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import type { Website } from "@/lib/api";

// Same wording and variants the Websites list uses — a site should not read as
// "Healthy" on one page and "active" on another.
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

function formatUptime(v: number | null): string {
  if (v == null) return "—";
  return Number.isInteger(v) ? `${v}%` : `${v.toFixed(2)}%`;
}

/**
 * The monitored sites belonging to one client. Read-only: this is the page a
 * viewer opens to see what is actually being watched for a client, so it links
 * through to each website's detail rather than offering edits of its own.
 */
export function ClientWebsitesCard({ websites }: { websites: Website[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Websites ({websites.length})</CardTitle>
        <p className="text-xs text-muted-foreground mt-0.5">
          Sites monitored for this client
        </p>
      </CardHeader>

      {websites.length === 0 ? (
        <CardContent className="flex flex-col items-center gap-3 py-8 text-center">
          <Globe className="h-8 w-8 text-muted-foreground/50" />
          <p className="text-sm text-muted-foreground">
            No monitored website is linked to this client yet.
          </p>
          <Link href="/websites/new">
            <Button variant="outline" size="sm">
              <Plus className="h-4 w-4 mr-1" />
              Add website
            </Button>
          </Link>
        </CardContent>
      ) : (
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Website</TableHead>
                <TableHead>Uptime (30d)</TableHead>
                <TableHead>Scripts</TableHead>
                <TableHead>Health</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {websites.map((site) => (
                <TableRow key={site.id}>
                  <TableCell>
                    <Link
                      href={`/websites/${site.id}`}
                      className="flex items-center gap-2 font-medium hover:text-primary"
                    >
                      <Globe className="h-4 w-4 text-muted-foreground shrink-0" />
                      {site.name || site.domain}
                    </Link>
                    {site.name && (
                      <p className="text-xs text-muted-foreground font-mono pl-6">{site.domain}</p>
                    )}
                  </TableCell>
                  <TableCell className="text-sm">{formatUptime(site.uptime_30d)}</TableCell>
                  <TableCell className="text-sm">{site.script_count ?? 0}</TableCell>
                  <TableCell className="text-sm">{site.health_score ?? "—"}</TableCell>
                  <TableCell>
                    <Badge variant={STATUS_BADGE[site.status] ?? "outline"}>
                      {STATUS_LABEL[site.status] ?? site.status ?? "Unknown"}
                    </Badge>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      )}
    </Card>
  );
}
