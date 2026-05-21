"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Trash2 } from "lucide-react";
import { useToast } from "@/hooks/use-toast";

export function DeleteStatusPageButton({ id, name }: { id: string; name: string }) {
  const router = useRouter();
  const { toast } = useToast();
  const [loading, setLoading] = useState(false);

  async function handleDelete(e: React.MouseEvent) {
    e.preventDefault();
    if (!confirm(`Delete "${name}"? This cannot be undone.`)) return;
    setLoading(true);
    try {
      const res = await fetch(`/api/status-pages/${id}`, { method: "DELETE" });
      if (res.ok || res.status === 204) {
        toast({ title: "Deleted", description: `"${name}" has been removed.` });
        router.refresh();
      } else {
        toast({ variant: "destructive", title: "Error", description: "Could not delete status page." });
      }
    } catch {
      toast({ variant: "destructive", title: "Network error" });
    } finally {
      setLoading(false);
    }
  }

  return (
    <button
      onClick={handleDelete}
      disabled={loading}
      className="p-1.5 rounded text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-colors disabled:opacity-40"
      title="Delete status page"
    >
      <Trash2 className="h-4 w-4" />
    </button>
  );
}
