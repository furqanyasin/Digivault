"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Plus, Trash2, Bell, FlaskConical, CheckCircle2, XCircle, Globe } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { NotificationChannel } from "@/lib/api";

const CHANNEL_TYPES = [
  { value: "email", label: "Email" },
  { value: "clickup", label: "ClickUp" },
];

const TYPE_BADGE_COLOR: Record<string, string> = {
  email: "bg-emerald-600 text-white",
  clickup: "bg-[#7B68EE] text-white",
};

function configSummary(channel: NotificationChannel): string {
  const c = channel.config as Record<string, unknown>;
  if (channel.channel_type === "email") {
    const addrs = (c.addresses as string[]) ?? [];
    return addrs.join(", ") || "—";
  }
  if (channel.channel_type === "clickup") {
    return c.chat_url ? "chat channel" : `task: ${c.task_id ?? "—"}`;
  }
  return "—";
}

function ConfigFields({
  channelType,
  config,
  onChange,
}: {
  channelType: string;
  config: Record<string, string>;
  onChange: (k: string, v: string) => void;
}) {
  if (channelType === "email") {
    return (
      <div className="space-y-2">
        <Label>Email addresses (comma-separated)</Label>
        <Input
          value={config.addresses ?? ""}
          onChange={(e) => onChange("addresses", e.target.value)}
          placeholder="alice@example.com, bob@example.com"
          required
        />
      </div>
    );
  }
  if (channelType === "clickup") {
    return (
      <>
        <div className="space-y-2">
          <Label>API Token</Label>
          <Input
            value={config.api_token ?? ""}
            onChange={(e) => onChange("api_token", e.target.value)}
            placeholder="pk_…"
            required
          />
        </div>
        <div className="space-y-2">
          <Label>Chat channel link <span className="text-muted-foreground">(preferred)</span></Label>
          <Input
            value={config.chat_url ?? ""}
            onChange={(e) => onChange("chat_url", e.target.value)}
            placeholder="https://your-team.clickup.com/123456/chat/r/xxxx-000"
            className="text-sm"
          />
          <p className="text-xs text-muted-foreground">
            Posts notifications into a ClickUp Chat channel (group). Open the channel in ClickUp and copy its URL.
          </p>
        </div>
        <div className="space-y-2">
          <Label>Task ID <span className="text-muted-foreground">(or, to comment on a task)</span></Label>
          <Input
            value={config.task_id ?? ""}
            onChange={(e) => onChange("task_id", e.target.value)}
            placeholder="e.g. 86evnnba3"
            className="font-mono text-sm"
          />
          <p className="text-xs text-muted-foreground">
            Used only if no Chat channel link is set. Provide a Chat link or a Task ID.
          </p>
        </div>
      </>
    );
  }
  return null;
}

function AddChannelForm({ onCreated }: { onCreated: () => void }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [channelType, setChannelType] = useState("slack");
  const [rawConfig, setRawConfig] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  function setConfig(k: string, v: string) {
    setRawConfig((prev) => ({ ...prev, [k]: v }));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      let config: Record<string, unknown> = {};
      if (channelType === "email") {
        config = { addresses: rawConfig.addresses?.split(",").map((s) => s.trim()).filter(Boolean) ?? [] };
      } else {
        config = { ...rawConfig };
      }
      const res = await fetch("/api/notification-channels", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, channel_type: channelType, config }),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d?.detail ?? `Error ${res.status}`);
      }
      setName("");
      setChannelType("slack");
      setRawConfig({});
      setOpen(false);
      onCreated();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  }

  if (!open) {
    return (
      <Button onClick={() => setOpen(true)}>
        <Plus className="h-4 w-4 mr-2" />
        Add channel
      </Button>
    );
  }

  return (
    <Card className="border-primary/30">
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-4">
          <p className="font-semibold text-sm">New notification channel</p>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label>Name</Label>
              <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Email Alerts" required />
            </div>
            <div className="space-y-2">
              <Label>Type</Label>
              <Select value={channelType} onValueChange={(v) => { setChannelType(v); setRawConfig({}); }}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {CHANNEL_TYPES.map((t) => (
                    <SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <ConfigFields channelType={channelType} config={rawConfig} onChange={setConfig} />
          {error && <p className="text-sm text-red-600">{error}</p>}
          <div className="flex gap-2">
            <Button type="submit" size="sm" disabled={loading}>{loading ? "Saving…" : "Save channel"}</Button>
            <Button type="button" size="sm" variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

export function NotificationChannelsClient({ initialChannels }: { initialChannels: NotificationChannel[] }) {
  const router = useRouter();
  const [deleting, setDeleting] = useState<string | null>(null);
  const [testing, setTesting] = useState<string | null>(null);
  const [applying, setApplying] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<Record<string, { success: boolean; message: string } | null>>({});

  async function applyToAllWebsites(id: string, name: string) {
    if (
      !confirm(
        `Send every website's alerts to "${name}"?\n\nThis replaces the channel on all sites, ` +
          `including any site-specific uptime channel. You can still change individual sites afterwards.`
      )
    )
      return;
    setApplying(id);
    setTestResult((prev) => ({ ...prev, [id]: null }));
    try {
      const res = await fetch(`/api/notification-channels/${id}/apply-to-all-websites`, {
        method: "POST",
      });
      const data = await res.json().catch(() => ({}));
      setTestResult((prev) => ({
        ...prev,
        [id]: res.ok
          ? { success: true, message: `Applied to ${data.updated} website${data.updated === 1 ? "" : "s"}` }
          : { success: false, message: data?.detail ?? `Error ${res.status}` },
      }));
      // Website pages read the channel server-side, so refresh rather than
      // leaving stale selects behind.
      if (res.ok) router.refresh();
      setTimeout(() => setTestResult((prev) => ({ ...prev, [id]: null })), 5000);
    } finally {
      setApplying(null);
    }
  }

  async function handleTest(id: string) {
    setTesting(id);
    setTestResult((prev) => ({ ...prev, [id]: null }));
    try {
      const res = await fetch(`/api/notification-channels/${id}/test`, { method: "POST" });
      const data = await res.json().catch(() => ({ success: false, message: "Unknown error" }));
      setTestResult((prev) => ({ ...prev, [id]: { success: data.success, message: data.message } }));
      setTimeout(() => setTestResult((prev) => ({ ...prev, [id]: null })), 4000);
    } finally {
      setTesting(null);
    }
  }

  async function deleteChannel(id: string, name: string) {
    if (!confirm(`Delete "${name}"? This will also remove it from all monitors.`)) return;
    setDeleting(id);
    await fetch(`/api/notification-channels/${id}`, { method: "DELETE" });
    setDeleting(null);
    router.refresh();
  }

  return (
    <div className="space-y-4">
      <AddChannelForm onCreated={() => router.refresh()} />

      {initialChannels.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center gap-3 text-center py-16">
            <Bell className="h-10 w-10 text-muted-foreground" />
            <p className="text-lg font-medium">No channels yet</p>
            <p className="text-muted-foreground text-sm">
              Add an Email or ClickUp channel to get notified when a monitor goes down
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-2">
          {initialChannels.map((ch) => (
            <Card key={ch.id}>
              <CardContent className="flex items-center justify-between">
                <div className="flex items-center gap-3 min-w-0">
                  <span className={`px-2 py-0.5 rounded text-xs font-semibold ${TYPE_BADGE_COLOR[ch.channel_type] ?? "bg-slate-200"}`}>
                    {ch.channel_type.toUpperCase()}
                  </span>
                  <div className="min-w-0">
                    <p className="font-medium text-sm">{ch.name}</p>
                    <p className="text-xs text-muted-foreground font-mono truncate max-w-sm">{configSummary(ch)}</p>
                    {testResult[ch.id] && (
                      <p className={`text-xs mt-0.5 flex items-center gap-1 ${testResult[ch.id]!.success ? "text-emerald-600" : "text-red-600"}`}>
                        {testResult[ch.id]!.success
                          ? <CheckCircle2 className="h-3 w-3" />
                          : <XCircle className="h-3 w-3" />}
                        {testResult[ch.id]!.message.slice(0, 80)}
                      </p>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-7 px-2 text-xs"
                    disabled={applying === ch.id}
                    title="Route every website's alerts to this channel"
                    onClick={() => applyToAllWebsites(ch.id, ch.name)}
                  >
                    <Globe className="h-3.5 w-3.5 mr-1" />
                    {applying === ch.id ? "Applying…" : "Apply to all sites"}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-7 px-2 text-slate-500 hover:text-slate-700"
                    disabled={testing === ch.id}
                    title="Send a test notification"
                    onClick={() => handleTest(ch.id)}
                  >
                    {testing === ch.id ? "…" : <FlaskConical className="h-3.5 w-3.5" />}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="text-red-500 hover:text-red-600"
                    disabled={deleting === ch.id}
                    onClick={() => deleteChannel(ch.id, ch.name)}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
