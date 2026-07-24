"use client";

import { useState } from "react";
import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useToast } from "@/hooks/use-toast";
import { useRouter } from "next/navigation";

export function RefreshDomainButton({
  websiteId,
  label = "Refresh domain info",
  variant = "outline",
}: {
  websiteId: string;
  label?: string;
  variant?: "outline" | "default";
}) {
  const { toast } = useToast();
  const router = useRouter();
  const [loading, setLoading] = useState(false);

  async function handle() {
    setLoading(true);
    try {
      const res = await fetch(`/api/websites/${websiteId}/domain`, { method: "POST" });
      if (res.ok) {
        toast({ title: "Domain info updated", description: "WHOIS and SSL data refreshed." });
        router.refresh();
      } else {
        const d = await res.json().catch(() => ({}));
        toast({
          variant: "destructive",
          title: "Domain check failed",
          description: d?.detail ?? `Error ${res.status}`,
        });
      }
    } catch {
      toast({ variant: "destructive", title: "Network error" });
    } finally {
      setLoading(false);
    }
  }

  return (
    <Button variant={variant} size="sm" onClick={handle} disabled={loading}>
      <RefreshCw className={`h-3.5 w-3.5 mr-1.5 ${loading ? "animate-spin" : ""}`} />
      {loading ? "Checking…" : label}
    </Button>
  );
}
