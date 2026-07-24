import Link from "next/link";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { getAccessToken } from "@/lib/server-token";
import { api } from "@/lib/api";
import type { Website } from "@/lib/api";
import { WebsitesClient, type MissingClient } from "@/components/websites-client";

interface ClientRow {
  id: string;
  name: string;
  website_url: string;
  domain: string;
}

/** Strip scheme/www/trailing slash the same way Client.domain does server-side. */
function normalizeDomain(raw: string): string {
  let d = (raw || "").toLowerCase().trim();
  for (const p of ["https://", "http://", "www."]) {
    if (d.startsWith(p)) d = d.slice(p.length);
  }
  return d.replace(/\/+$/, "");
}

export default async function WebsitesPage() {
  const token = await getAccessToken();

  const [websitesResult, clientsResult] = await Promise.allSettled([
    api.getAll<Website>("/api/v1/websites/", token ?? ""),
    api.getAll<ClientRow>("/api/v1/clients/", token ?? ""),
  ]);

  const websites = websitesResult.status === "fulfilled" ? websitesResult.value : [];
  const clients = clientsResult.status === "fulfilled" ? clientsResult.value : [];

  // Clients that carry a URL but have no website yet — normally none, since the
  // importer provisions them, but a deleted site or a client added straight
  // through the API can leave a gap. Surfacing it beats it going unnoticed.
  const tracked = new Set(websites.map((w) => normalizeDomain(w.domain)));
  const missingClients: MissingClient[] = clients
    .filter((c) => c.website_url && normalizeDomain(c.domain || c.website_url))
    .filter((c) => !tracked.has(normalizeDomain(c.domain || c.website_url)))
    .map((c) => ({
      id: c.id,
      name: c.name,
      domain: normalizeDomain(c.domain || c.website_url),
    }));

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

      <WebsitesClient websites={websites} missingClients={missingClients} />
    </div>
  );
}
