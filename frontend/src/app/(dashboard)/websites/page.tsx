import Link from "next/link";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { getAccessToken } from "@/lib/server-token";
import { api } from "@/lib/api";
import type { Website } from "@/lib/api";
import { WebsitesClient } from "@/components/websites-client";

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

      <WebsitesClient websites={websites} />
    </div>
  );
}
