import Link from "next/link";
import { Globe, CheckCircle, AlertTriangle, XCircle } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { getAccessToken } from "@/lib/server-token";
import { api } from "@/lib/api";
import type { StatusPage } from "@/lib/api";
import { CreateStatusPageButton } from "@/components/create-status-page-button";
import { DeleteStatusPageButton } from "@/components/delete-status-page-button";

function statusInfo(s: StatusPage["overall_status"]) {
  switch (s) {
    case "operational":
      return { label: "All Systems Operational", color: "text-emerald-600", icon: <CheckCircle className="h-4 w-4 text-emerald-500" /> };
    case "degraded":
      return { label: "Degraded Performance", color: "text-amber-600", icon: <AlertTriangle className="h-4 w-4 text-amber-500" /> };
    case "outage":
      return { label: "Service Outage", color: "text-red-600", icon: <XCircle className="h-4 w-4 text-red-500" /> };
  }
}

export default async function StatusPagesPage() {
  const token = await getAccessToken();
  const pages = await api
    .get<StatusPage[]>("/api/v1/status-pages/", token ?? "")
    .catch(() => [] as StatusPage[]);

  return (
    <div className="p-8 space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Public Status Pages</h1>
          <p className="text-muted-foreground mt-1">
            Share real-time uptime status with your users
          </p>
        </div>
        <CreateStatusPageButton />
      </div>

      {pages.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center gap-3 text-center py-16">
            <Globe className="h-10 w-10 text-muted-foreground" />
            <p className="text-lg font-medium">No status pages yet</p>
            <p className="text-muted-foreground text-sm">
              Create a public status page to let your users know when services are up or down
            </p>
            <CreateStatusPageButton className="mt-2" />
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {pages.map((page) => {
            const info = statusInfo(page.overall_status);
            return (
              <Card key={page.id} className="flex flex-col">
                <CardHeader>
                  <div className="flex items-start justify-between gap-2">
                    <CardTitle className="text-base leading-snug">{page.name}</CardTitle>
                    <div className="flex items-center gap-1 shrink-0">
                      {info.icon}
                      <DeleteStatusPageButton id={page.id} name={page.name} />
                    </div>
                  </div>
                  <p className={`text-xs font-medium ${info.color}`}>{info.label}</p>
                </CardHeader>
                <CardContent className="flex-1 space-y-3">
                  {page.description && (
                    <p className="text-sm text-muted-foreground line-clamp-2">{page.description}</p>
                  )}
                  <div className="flex items-center gap-2 flex-wrap">
                    <code className="text-xs bg-muted px-2 py-0.5 rounded font-mono">/status/{page.slug}</code>
                    {!page.allow_indexing && (
                      <Badge variant="secondary" className="text-xs">noindex</Badge>
                    )}
                  </div>
                  <div className="flex items-center gap-2 pt-1">
                    <Link href={`/status-pages/${page.id}`} className="flex-1">
                      <Button variant="outline" size="sm" className="w-full">Manage</Button>
                    </Link>
                    <Link href={`/status/${page.slug}`} target="_blank" rel="noopener noreferrer" className="flex-1">
                      <Button variant="ghost" size="sm" className="w-full">
                        <Globe className="h-3.5 w-3.5 mr-1.5" />
                        View public
                      </Button>
                    </Link>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
