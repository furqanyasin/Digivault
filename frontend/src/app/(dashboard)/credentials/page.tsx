import { getAccessToken } from "@/lib/server-token";
import { api } from "@/lib/api";
import type { Website } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Key, Lock, ExternalLink } from "lucide-react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

export default async function CredentialsPage() {
  const token = await getAccessToken();
  let websites: Website[] = [];
  try {
    websites = await api.get<Website[]>("/api/v1/websites/", token ?? "");
  } catch {
    // ignore
  }

  return (
    <div className="p-8 space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Credentials</h1>
        <p className="text-muted-foreground mt-1">
          Securely stored API keys and logins — managed per website
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Key className="h-4 w-4" />
            Credentials are stored per site
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground mb-4">
            Go to any website&apos;s <strong>Credentials tab</strong> to add, view, and manage logins for WordPress, cPanel, GoDaddy, Cloudflare, and more.
          </p>
        </CardContent>
      </Card>

      {websites.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16 gap-3 text-center">
            <Key className="h-10 w-10 text-muted-foreground" />
            <p className="text-lg font-medium">No websites yet</p>
            <p className="text-muted-foreground text-sm">Add a website first, then manage its credentials from the site detail page</p>
            <Link href="/websites/new">
              <Button variant="outline" className="mt-2">Add website</Button>
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
                  <TableHead>Site</TableHead>
                  <TableHead>Domain</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {websites.map((site) => (
                  <TableRow key={site.id}>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <Lock className="h-3.5 w-3.5 text-muted-foreground" />
                        <span className="font-medium">{site.name || site.domain}</span>
                      </div>
                    </TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">{site.domain}</TableCell>
                    <TableCell>
                      <Badge
                        variant={
                          site.status === "critical" ? "destructive" :
                          site.status === "warning" ? "warning" :
                          site.status === "active" ? "success" : "secondary"
                        }
                      >
                        {site.status ?? "unknown"}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Link href={`/websites/${site.id}?tab=credentials`}>
                        <Button variant="outline" size="sm">
                          <ExternalLink className="h-3.5 w-3.5 mr-1" />
                          Manage credentials
                        </Button>
                      </Link>
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
