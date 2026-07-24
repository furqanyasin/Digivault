"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useToast } from "@/hooks/use-toast";

/** One-click provisioning for a client whose website was never created.
 *
 * Posts the same payload the importer would, so the Website post_save signals
 * still run (uptime monitor, status page, initial checks).
 */
export function AddClientWebsiteButton({
  clientId,
  clientName,
  domain,
}: {
  clientId: string;
  clientName: string;
  domain: string;
}) {
  const { toast } = useToast();
  const router = useRouter();
  const [loading, setLoading] = useState(false);

  async function handle() {
    setLoading(true);
    try {
      const res = await fetch("/api/websites", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: clientName, domain, client: clientId }),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        const msg = Object.values(d).flat().join(" ") || `Error ${res.status}`;
        toast({ variant: "destructive", title: "Could not add website", description: msg as string });
        return;
      }
      toast({ title: "Website added", description: `${domain} is now being monitored.` });
      router.refresh();
    } catch {
      toast({ variant: "destructive", title: "Network error" });
    } finally {
      setLoading(false);
    }
  }

  return (
    <Button size="sm" variant="outline" onClick={handle} disabled={loading}>
      <Plus className={`h-3.5 w-3.5 mr-1.5 ${loading ? "animate-pulse" : ""}`} />
      {loading ? "Adding…" : "Add"}
    </Button>
  );
}
