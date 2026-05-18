"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Plus, Trash2, AlertCircle, ArrowUp, ArrowDown, Minus, Circle } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { Monitor, StatusPage, StatusPageMonitor } from "@/lib/api";

function statusIcon(status: Monitor["status"]) {
  switch (status) {
    case "up": return <ArrowUp className="h-3.5 w-3.5 text-emerald-500" />;
    case "down": return <ArrowDown className="h-3.5 w-3.5 text-red-500" />;
    case "degraded": return <Minus className="h-3.5 w-3.5 text-amber-500" />;
    default: return <Circle className="h-3.5 w-3.5 text-slate-400" />;
  }
}

interface Props {
  page: StatusPage;
  initialEntries: StatusPageMonitor[];
  availableMonitors: Monitor[];
}

export function StatusPageManagerClient({ page, initialEntries, availableMonitors }: Props) {
  const router = useRouter();
  const [entries, setEntries] = useState(initialEntries);
  const [selectedMonitorId, setSelectedMonitorId] = useState("");
  const [adding, setAdding] = useState(false);
  const [removing, setRemoving] = useState<string | null>(null);
  const [error, setError] = useState("");

  const addedIds = new Set(entries.map((e) => e.monitor_detail.id));
  const candidates = availableMonitors.filter((m) => !addedIds.has(m.id));

  async function addMonitor() {
    if (!selectedMonitorId) return;
    setError("");
    setAdding(true);
    try {
      const res = await fetch(`/api/status-pages/${page.id}/monitors`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ monitor_id: selectedMonitorId }),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        setError(d?.detail ?? `Error ${res.status}`);
        return;
      }
      const entry: StatusPageMonitor = await res.json();
      setEntries((prev) => [...prev, entry]);
      setSelectedMonitorId("");
      router.refresh();
    } finally {
      setAdding(false);
    }
  }

  async function removeEntry(entryId: string) {
    setRemoving(entryId);
    try {
      await fetch(`/api/status-pages/${page.id}/monitors/${entryId}`, { method: "DELETE" });
      setEntries((prev) => prev.filter((e) => e.id !== entryId));
      router.refresh();
    } finally {
      setRemoving(null);
    }
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Monitors on this page</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Add monitor row */}
          <div className="flex items-center gap-3">
            <Select value={selectedMonitorId} onValueChange={setSelectedMonitorId}>
              <SelectTrigger className="flex-1">
                <SelectValue placeholder={candidates.length ? "Select a monitor to add…" : "All monitors already added"} />
              </SelectTrigger>
              <SelectContent>
                {candidates.map((m) => (
                  <SelectItem key={m.id} value={m.id}>
                    <span className="flex items-center gap-2">
                      {statusIcon(m.status)}
                      {m.name}
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button
              disabled={!selectedMonitorId || adding}
              onClick={addMonitor}
            >
              <Plus className="h-4 w-4 mr-1.5" />
              {adding ? "Adding…" : "Add"}
            </Button>
          </div>

          {error && (
            <div className="flex items-center gap-2 text-sm text-red-600">
              <AlertCircle className="h-4 w-4 shrink-0" />
              {error}
            </div>
          )}

          {entries.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-8">
              No monitors added yet. Select one above to include it on the public status page.
            </p>
          ) : (
            <div className="divide-y rounded-md border">
              {entries.map((entry) => {
                const m = entry.monitor_detail;
                return (
                  <div key={entry.id} className="flex items-center justify-between px-4 py-3">
                    <div className="flex items-center gap-3">
                      {statusIcon(m.status)}
                      <div>
                        <p className="text-sm font-medium">{entry.effective_name}</p>
                        <p className="text-xs text-muted-foreground font-mono">{m.url}</p>
                      </div>
                    </div>
                    <div className="flex items-center gap-3">
                      <Badge
                        variant="outline"
                        className={`text-xs capitalize ${
                          m.status === "up" ? "text-emerald-600 border-emerald-300" :
                          m.status === "down" ? "text-red-600 border-red-300" :
                          m.status === "degraded" ? "text-amber-600 border-amber-300" :
                          "text-slate-500"
                        }`}
                      >
                        {m.status}
                      </Badge>
                      {m.uptime_30d !== null && (
                        <span className="text-xs text-muted-foreground font-mono">
                          {m.uptime_30d.toFixed(1)}% 30d
                        </span>
                      )}
                      <Button
                        size="sm"
                        variant="ghost"
                        className="text-red-500 hover:text-red-600"
                        disabled={removing === entry.id}
                        onClick={() => removeEntry(entry.id)}
                        title="Remove from page"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
