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
  runFullCheck = false,
}: {
  websiteId: string;
  label?: string;
  variant?: "outline" | "default";
  runFullCheck?: boolean;
}) {
  const { toast } = useToast();
  const router = useRouter();
  const [loading, setLoading] = useState(false);

  async function handle() {
    setLoading(true);
    try {
      const calls = [
        fetch(`/api/websites/${websiteId}/domain`, { method: "POST" }),
      ];
      if (runFullCheck) {
        calls.push(fetch(`/api/websites/${websiteId}/scan`, { method: "POST" }));
      }
      const [domainRes, scanRes] = await Promise.all(calls);

      const failures: string[] = [];
      if (!domainRes.ok) failures.push(`domain refresh (${domainRes.status})`);
      if (scanRes && !scanRes.ok) failures.push(`scan (${scanRes.status})`);

      if (failures.length === 0) {
        toast({
          title: runFullCheck ? "Check complete" : "Domain info updated",
          description: runFullCheck
            ? "Scripts, forms, WHOIS and SSL data refreshed."
            : "WHOIS and SSL data refreshed.",
        });
        if (runFullCheck) {
          // The scan's ingest runs asynchronously in Celery — give it a moment
          // to process, then reload the page so freshly-detected data shows.
          setTimeout(() => router.refresh(), 2500);
        } else {
          router.refresh();
        }
      } else {
        toast({
          variant: "destructive",
          title: runFullCheck ? "Check failed" : "Domain check failed",
          description: `Could not complete ${failures.join(", ")}.`,
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
