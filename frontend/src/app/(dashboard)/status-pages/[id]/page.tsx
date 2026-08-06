import { notFound } from "next/navigation";
import Link from "next/link";
import { Globe, ArrowLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { getAccessToken } from "@/lib/server-token";
import { api } from "@/lib/api";
import type { Monitor, StatusPage, StatusPageMonitor } from "@/lib/api";
import { StatusPageManagerClient } from "@/components/status-page-manager-client";
import { StatusPageSettings } from "@/components/status-page-settings";

export default async function StatusPageDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const token = await getAccessToken();

  const [page, entries, monitors] = await Promise.all([
    api.get<StatusPage>(`/api/v1/status-pages/${id}/`, token ?? "").catch(() => null),
    api.get<StatusPageMonitor[]>(`/api/v1/status-pages/${id}/monitors/`, token ?? "").catch(() => [] as StatusPageMonitor[]),
    // getAll: the monitor picker must list every monitor, and the list pages at 25.
    api.getAll<Monitor>("/api/v1/monitors/", token ?? "").catch(() => [] as Monitor[]),
  ]);

  if (!page) notFound();

  return (
    <div className="p-8 space-y-6">
      <div className="flex items-center gap-4">
        <Link href="/status-pages">
          <Button variant="ghost" size="sm">
            <ArrowLeft className="h-4 w-4 mr-1.5" />
            Status Pages
          </Button>
        </Link>
      </div>

      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">{page.name}</h1>
          <div className="flex items-center gap-3 mt-2">
            <code className="text-sm bg-muted px-2 py-0.5 rounded font-mono">/status/{page.slug}</code>
            {!page.allow_indexing && (
              <Badge variant="secondary" className="text-xs">noindex</Badge>
            )}
          </div>
        </div>
        <Link href={`/status/${page.slug}`} target="_blank" rel="noopener noreferrer">
          <Button variant="outline">
            <Globe className="h-4 w-4 mr-2" />
            View public page
          </Button>
        </Link>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium text-muted-foreground">Overall Status</CardTitle>
          </CardHeader>
          <CardContent>
            <div className={`text-lg font-semibold capitalize ${
              page.overall_status === "operational" ? "text-emerald-600" :
              page.overall_status === "degraded" ? "text-amber-600" : "text-red-600"
            }`}>
              {page.overall_status === "operational" ? "All Systems Operational" :
               page.overall_status === "degraded" ? "Degraded Performance" : "Service Outage"}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium text-muted-foreground">Monitors on Page</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{entries.length}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium text-muted-foreground">Search Indexing</CardTitle>
          </CardHeader>
          <CardContent>
            <div className={`text-sm font-medium ${page.allow_indexing ? "text-amber-600" : "text-emerald-600"}`}>
              {page.allow_indexing ? "Allowed (visible to search engines)" : "Blocked (noindex)"}
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <StatusPageManagerClient
          page={page}
          initialEntries={entries}
          availableMonitors={monitors}
        />
        <StatusPageSettings page={page} />
      </div>
    </div>
  );
}
