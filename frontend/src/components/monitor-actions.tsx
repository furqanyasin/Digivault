"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Pause, Play, Zap, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { Monitor } from "@/lib/api";

interface Props {
  monitor: Monitor;
}

export function MonitorActions({ monitor }: Props) {
  const router = useRouter();
  const [loading, setLoading] = useState<string | null>(null);

  async function act(action: string, method = "POST") {
    setLoading(action);
    try {
      if (action === "delete") {
        if (!confirm(`Delete monitor "${monitor.name}"? This cannot be undone.`)) return;
        await fetch(`/api/monitors/${monitor.id}`, { method: "DELETE" });
        router.refresh();
        return;
      }
      await fetch(`/api/monitors/${monitor.id}/${action}`, { method });
      router.refresh();
    } finally {
      setLoading(null);
    }
  }

  const isChecking = loading === "check-now";

  return (
    <div className="flex items-center gap-1 justify-end">
      {monitor.status === "paused" ? (
        <Button size="sm" variant="ghost" disabled={loading === "resume"} onClick={() => act("resume")} title="Resume">
          <Play className="h-3.5 w-3.5" />
        </Button>
      ) : (
        <Button size="sm" variant="ghost" disabled={loading === "pause"} onClick={() => act("pause")} title="Pause">
          <Pause className="h-3.5 w-3.5" />
        </Button>
      )}
      <Button
        size="sm" variant="ghost"
        disabled={isChecking}
        onClick={() => act("check-now")}
        title={isChecking ? "Checking…" : "Check now"}
      >
        <Zap className={`h-3.5 w-3.5 ${isChecking ? "animate-pulse text-amber-500" : ""}`} />
      </Button>
      <Button
        size="sm" variant="ghost"
        className="text-red-500 hover:text-red-600"
        disabled={loading === "delete"}
        onClick={() => act("delete", "DELETE")}
        title="Delete"
      >
        <Trash2 className="h-3.5 w-3.5" />
      </Button>
    </div>
  );
}
