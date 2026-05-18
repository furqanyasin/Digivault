"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { useToast } from "@/hooks/use-toast";
import { useRouter } from "next/navigation";

export function AcknowledgeButton({ changeId }: { changeId: string }) {
  const { toast } = useToast();
  const router = useRouter();
  const [loading, setLoading] = useState(false);

  async function handle() {
    setLoading(true);
    try {
      const res = await fetch(`/api/changes/${changeId}/acknowledge`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      if (!res.ok) throw new Error();
      toast({ title: "Change acknowledged" });
      router.refresh();
    } catch {
      toast({ variant: "destructive", title: "Failed to acknowledge" });
    } finally {
      setLoading(false);
    }
  }

  return (
    <Button size="sm" variant="outline" onClick={handle} disabled={loading}>
      {loading ? "…" : "Acknowledge"}
    </Button>
  );
}
