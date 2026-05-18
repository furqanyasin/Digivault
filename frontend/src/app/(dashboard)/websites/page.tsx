import Link from "next/link";
import { Plus, ExternalLink } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { getAccessToken } from "@/lib/server-token";
import { api } from "@/lib/api";
import type { Website } from "@/lib/api";
import { DeleteWebsiteButton } from "@/components/delete-website-button";

export default async function WebsitesPage() {
  const token = await getAccessToken();
  let websites: Website[] = [];
  try {
    websites = await api.get<Website[]>("/api/v1/websites/", token ?? "");
  } catch {
    // will show empty state
  }

  return (
    <div className="p-8 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Websites</h1>
          <p className="text-muted-foreground mt-1">Manage the sites you&apos;re monitoring</p>
        </div>
        <Link href="/websites/new">
          <Button>
            <Plus className="h-4 w-4 mr-2" />
            Add website
          </Button>
        </Link>
      </div>

      {websites.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16 gap-3 text-center">
            <p className="text-lg font-medium">No websites yet</p>
            <p className="text-muted-foreground text-sm">Add your first website to start monitoring scripts</p>
            <Link href="/websites/new">
              <Button variant="outline" className="mt-2">
                <Plus className="h-4 w-4 mr-2" />
                Add website
              </Button>
            </Link>
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>All sites ({websites.length})</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Domain</TableHead>
                  <TableHead>Name</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Scripts</TableHead>
                  <TableHead>Added</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {websites.map((site) => (
                  <TableRow key={site.id}>
                    <TableCell className="font-mono text-sm">{site.domain}</TableCell>
                    <TableCell>{site.name || "—"}</TableCell>
                    <TableCell>
                      <Badge variant={
                        site.status === "critical" ? "destructive" :
                        site.status === "warning" ? "warning" :
                        site.status === "active" ? "success" : "secondary"
                      }>
                        {site.status ?? "unknown"}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-sm">{site.script_count ?? 0}</TableCell>
                    <TableCell className="text-muted-foreground text-sm">
                      {new Date(site.created_at).toLocaleDateString()}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1">
                        <Link href={`/websites/${site.id}`}>
                          <Button variant="ghost" size="sm">
                            <ExternalLink className="h-4 w-4" />
                          </Button>
                        </Link>
                        <DeleteWebsiteButton id={site.id} name={site.name || site.domain} />
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
