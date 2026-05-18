"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Plus, Trash2, Bell } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import type { NotificationChannel, MonitorNotificationRule } from "@/lib/api";

const TYPE_COLOR: Record<string, string> = {
  slack: "bg-[#4A154B] text-white",
  discord: "bg-[#5865F2] text-white",
  webhook: "bg-slate-700 text-white",
  email: "bg-emerald-600 text-white",
  telegram: "bg-[#26A5E4] text-white",
};

interface Props {
  monitorId: string;
  initialRules: MonitorNotificationRule[];
  channels: NotificationChannel[];
}

export function MonitorNotificationPanel({ monitorId, initialRules, channels }: Props) {
  const router = useRouter();
  const [adding, setAdding] = useState(false);
  const [selectedChannel, setSelectedChannel] = useState("");
  const [onDown, setOnDown] = useState(true);
  const [onRecovery, setOnRecovery] = useState(true);
  const [onDegraded, setOnDegraded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [deleting, setDeleting] = useState<string | null>(null);

  const assignedChannelIds = new Set(initialRules.map((r) => r.channel.id));
  const availableChannels = channels.filter((c) => !assignedChannelIds.has(c.id));

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedChannel) return;
    setSaving(true);
    setError("");
    try {
      const res = await fetch(`/api/monitors/${monitorId}/notification-rules`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          channel_id: selectedChannel,
          notify_on_down: onDown,
          notify_on_recovery: onRecovery,
          notify_on_degraded: onDegraded,
        }),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d?.detail ?? `Error ${res.status}`);
      }
      setAdding(false);
      setSelectedChannel("");
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(ruleId: string) {
    setDeleting(ruleId);
    await fetch(`/api/monitors/${monitorId}/notification-rules/${ruleId}`, { method: "DELETE" });
    setDeleting(null);
    router.refresh();
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-3">
        <CardTitle className="text-base flex items-center gap-2">
          <Bell className="h-4 w-4" />
          Notifications
        </CardTitle>
        {availableChannels.length > 0 && !adding && (
          <Button size="sm" variant="outline" onClick={() => setAdding(true)}>
            <Plus className="h-3.5 w-3.5 mr-1" />
            Add
          </Button>
        )}
      </CardHeader>
      <CardContent className="space-y-3">
        {adding && (
          <form onSubmit={handleAdd} className="space-y-3 border rounded-md p-3 bg-muted/20">
            <div className="space-y-1.5">
              <Label className="text-xs">Channel</Label>
              <Select value={selectedChannel} onValueChange={setSelectedChannel} required>
                <SelectTrigger className="h-8 text-xs"><SelectValue placeholder="Select channel…" /></SelectTrigger>
                <SelectContent>
                  {availableChannels.map((c) => (
                    <SelectItem key={c.id} value={c.id}>{c.name} ({c.channel_type})</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex gap-3 text-xs">
              <label className="flex items-center gap-1 cursor-pointer">
                <input type="checkbox" checked={onDown} onChange={(e) => setOnDown(e.target.checked)} />
                On down
              </label>
              <label className="flex items-center gap-1 cursor-pointer">
                <input type="checkbox" checked={onRecovery} onChange={(e) => setOnRecovery(e.target.checked)} />
                On recovery
              </label>
              <label className="flex items-center gap-1 cursor-pointer">
                <input type="checkbox" checked={onDegraded} onChange={(e) => setOnDegraded(e.target.checked)} />
                On degraded
              </label>
            </div>
            {error && <p className="text-xs text-red-600">{error}</p>}
            <div className="flex gap-2">
              <Button type="submit" size="sm" disabled={saving || !selectedChannel}>
                {saving ? "Saving…" : "Assign"}
              </Button>
              <Button type="button" size="sm" variant="ghost" onClick={() => { setAdding(false); setError(""); }}>
                Cancel
              </Button>
            </div>
          </form>
        )}

        {initialRules.length === 0 && !adding ? (
          <p className="text-xs text-muted-foreground text-center py-4">
            No channels assigned.{" "}
            {channels.length === 0 ? (
              <a href="/monitors/channels" className="underline">Create a channel first.</a>
            ) : (
              <button className="underline" onClick={() => setAdding(true)}>Add one.</button>
            )}
          </p>
        ) : (
          <div className="space-y-2">
            {initialRules.map((rule) => (
              <div key={rule.id} className="flex items-center justify-between text-sm">
                <div className="flex items-center gap-2 min-w-0">
                  <span className={`px-1.5 py-0.5 rounded text-xs font-semibold ${TYPE_COLOR[rule.channel.channel_type] ?? "bg-slate-200"}`}>
                    {rule.channel.channel_type.toUpperCase()}
                  </span>
                  <span className="font-medium truncate">{rule.channel.name}</span>
                  <span className="text-xs text-muted-foreground">
                    {[
                      rule.notify_on_down && "down",
                      rule.notify_on_recovery && "recovery",
                      rule.notify_on_degraded && "degraded",
                    ].filter(Boolean).join(", ")}
                  </span>
                </div>
                <Button
                  size="sm"
                  variant="ghost"
                  className="text-red-500 hover:text-red-600 shrink-0 h-6 w-6 p-0"
                  disabled={deleting === rule.id}
                  onClick={() => handleDelete(rule.id)}
                >
                  <Trash2 className="h-3 w-3" />
                </Button>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
