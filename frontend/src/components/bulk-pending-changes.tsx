"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { CheckCircle, CheckSquare } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useToast } from "@/hooks/use-toast";
import type { ScriptChange } from "@/lib/api";
import { fmtDate } from "@/lib/utils";

const SEV_STRIPE: Record<string, string> = {
  critical: "border-l-red-600",
  high:     "border-l-red-400",
  medium:   "border-l-amber-400",
  low:      "border-l-blue-400",
};

const SEV_BADGE: Record<string, string> = {
  critical: "destructive",
  high:     "destructive",
  medium:   "warning",
  low:      "secondary",
};

function smartUrl(url: string): string {
  try {
    const u = new URL(url);
    const parts = u.pathname.split("/").filter(Boolean);
    const filename = parts[parts.length - 1] ?? "";
    return `${u.hostname}${filename ? `/${filename}` : ""}`;
  } catch {
    return url.length > 60 ? url.slice(0, 57) + "…" : url;
  }
}

export function BulkPendingChanges({ changes, websiteId }: { changes: ScriptChange[]; websiteId?: string }) {
  const { toast } = useToast();
  const router = useRouter();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [, startTransition] = useTransition();
  const [acking, setAcking] = useState(false);

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  function toggleAll() {
    setSelected((prev) =>
      prev.size === changes.length ? new Set() : new Set(changes.map((c) => c.id))
    );
  }

  async function acknowledgeSelected() {
    if (selected.size === 0) return;
    setAcking(true);
    try {
      await Promise.all(
        [...selected].map((id) =>
          fetch(`/api/changes/${id}/acknowledge`, { method: "POST" })
        )
      );
      toast({ title: `${selected.size} change${selected.size > 1 ? "s" : ""} acknowledged` });
      setSelected(new Set());
      startTransition(() => router.refresh());
    } catch {
      toast({ variant: "destructive", title: "Some acknowledgements failed" });
    } finally {
      setAcking(false);
    }
  }

  if (changes.length === 0) {
    return (
      <div className="p-8 flex flex-col items-center gap-2 text-center">
        <CheckCircle className="h-8 w-8 text-emerald-500" />
        <p className="font-medium text-sm">No pending changes</p>
        <p className="text-xs text-muted-foreground">All changes have been acknowledged</p>
      </div>
    );
  }

  const allSelected = selected.size === changes.length;

  return (
    <div>
      {/* Bulk action bar */}
      <div className="flex items-center justify-between px-4 py-2 border-b bg-muted/40">
        <label className="flex items-center gap-2 text-xs text-muted-foreground cursor-pointer select-none">
          <input
            type="checkbox"
            checked={allSelected}
            onChange={toggleAll}
            className="rounded"
          />
          {selected.size > 0 ? `${selected.size} selected` : "Select all"}
        </label>
        {selected.size > 0 && (
          <Button size="sm" variant="outline" onClick={acknowledgeSelected} disabled={acking} className="h-7 text-xs">
            <CheckSquare className="h-3.5 w-3.5 mr-1" />
            {acking ? "Acknowledging…" : `Acknowledge ${selected.size}`}
          </Button>
        )}
      </div>

      <div className="divide-y">
        {changes.map((change) => (
          <div
            key={change.id}
            className={`flex items-center gap-3 px-4 py-3 border-l-4 hover:bg-muted/30 transition-colors ${SEV_STRIPE[change.severity] ?? "border-l-border"} ${selected.has(change.id) ? "bg-muted/40" : ""}`}
          >
            <input
              type="checkbox"
              checked={selected.has(change.id)}
              onChange={() => toggle(change.id)}
              className="rounded shrink-0"
            />
            <div className="flex-1 min-w-0 grid grid-cols-[auto_1fr_auto_auto] gap-x-3 gap-y-0.5 items-center">
              <Badge variant={SEV_BADGE[change.severity] as "destructive" | "warning" | "secondary"} className="text-xs capitalize shrink-0">
                {change.severity}
              </Badge>
              <div className="min-w-0">
                <p className="text-xs font-mono truncate text-muted-foreground" title={change.script?.src_url}>
                  {change.script?.src_url ? smartUrl(change.script.src_url) : "—"}
                </p>
                <p className="text-xs text-muted-foreground truncate">{change.description}</p>
              </div>
              <span className="text-xs font-medium capitalize text-foreground shrink-0">{change.change_type}</span>
              <span className="text-xs text-muted-foreground shrink-0 text-right">{fmtDate(change.created_at)}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
