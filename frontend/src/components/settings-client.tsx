"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useToast } from "@/hooks/use-toast";
import { CheckCircle2, XCircle, Loader2, Eye, EyeOff, ExternalLink } from "lucide-react";

interface TeamSettings {
  id: string;
  name: string;
  clickup_api_token: string;
  clickup_api_token_masked: string;
  clickup_connected: boolean;
  clickup_list_id: string;
  clickup_chat_url: string;
  clickup_chat_connected: boolean;
}

interface MemberMatch {
  user_id: string;
  email: string;
  clickup_user_id?: string;
  clickup_username?: string;
}

interface Props {
  settings: TeamSettings | null;
  activeTeamId: string | null;
}

export function SettingsClient({ settings, activeTeamId }: Props) {
  const { toast } = useToast();
  const [token, setToken] = useState("");
  const [showToken, setShowToken] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [connected, setConnected] = useState<boolean | null>(settings?.clickup_connected ?? null);
  const [clickupUser, setClickupUser] = useState<string | null>(null);
  const maskedToken = settings?.clickup_api_token_masked ?? "";
  const [listId, setListId] = useState(settings?.clickup_list_id ?? "");
  const [savingList, setSavingList] = useState(false);
  const [chatUrl, setChatUrl] = useState(settings?.clickup_chat_url ?? "");
  const [editingChat, setEditingChat] = useState(!settings?.clickup_chat_url);
  const [savingChat, setSavingChat] = useState(false);
  const [creatingChannel, setCreatingChannel] = useState(false);
  const [matched, setMatched] = useState<MemberMatch[]>([]);
  const [unmatched, setUnmatched] = useState<MemberMatch[]>([]);
  const [overrides, setOverrides] = useState<Record<string, string>>({});

  async function handleSaveChatUrl(next: string) {
    if (!activeTeamId) return;
    setSavingChat(true);
    try {
      const res = await fetch(`/api/teams/${activeTeamId}/settings`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ clickup_chat_url: next }),
      });
      const data = await res.json();
      if (!res.ok) {
        toast({ variant: "destructive", title: "Error", description: data?.detail || "Failed to save." });
        return;
      }
      setChatUrl(next);
      setEditingChat(!next);
      toast({
        title: "Saved",
        description: next
          ? "Website problems will be posted to that channel."
          : "Team channel cleared — nothing will be posted.",
      });
    } catch {
      toast({ variant: "destructive", title: "Network error" });
    } finally {
      setSavingChat(false);
    }
  }

  async function handleCreateChannel() {
    if (!activeTeamId) return;
    setCreatingChannel(true);
    try {
      const res = await fetch(`/api/teams/${activeTeamId}/settings/clickup-channel`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: "Digivault — Web Team" }),
      });
      const data = await res.json();
      const payload = data?.data ?? data;
      if (!res.ok) {
        toast({
          variant: "destructive",
          title: "Error",
          description: payload?.detail || "Could not create the channel.",
        });
        return;
      }
      setChatUrl(payload.clickup_chat_url || "");
      setEditingChat(!payload.clickup_chat_url);
      setMatched(payload.matched || []);
      setUnmatched(payload.unmatched || []);
      toast({
        title: "Channel created",
        description: `${(payload.matched || []).length} member(s) added in ClickUp.`,
      });
    } catch {
      toast({ variant: "destructive", title: "Network error" });
    } finally {
      setCreatingChannel(false);
    }
  }

  async function handleSyncMembers() {
    if (!activeTeamId) return;
    const body = {
      overrides: Object.entries(overrides)
        .filter(([, v]) => v.trim())
        .map(([user_id, clickup_user_id]) => ({ user_id, clickup_user_id: clickup_user_id.trim() })),
    };
    try {
      const res = await fetch(`/api/teams/${activeTeamId}/settings/clickup-members`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      const payload = data?.data ?? data;
      if (!res.ok) {
        toast({ variant: "destructive", title: "Error", description: payload?.detail || "Sync failed." });
        return;
      }
      setMatched(payload.matched || []);
      setUnmatched(payload.unmatched || []);
      setOverrides({});
      toast({
        title: "Synced",
        description: `${(payload.matched || []).length} matched, ${(payload.unmatched || []).length} unmatched.`,
      });
    } catch {
      toast({ variant: "destructive", title: "Network error" });
    }
  }

  async function handleSaveListId() {
    if (!activeTeamId) return;
    setSavingList(true);
    try {
      const res = await fetch(`/api/teams/${activeTeamId}/settings`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ clickup_list_id: listId.trim() }),
      });
      const data = await res.json();
      if (!res.ok) {
        toast({ variant: "destructive", title: "Error", description: data?.detail || "Failed to save." });
        return;
      }
      toast({
        title: "Saved",
        description: listId.trim()
          ? "Digivault will open issue tasks in that list."
          : "Issue list cleared — no tasks will be created.",
      });
    } catch {
      toast({ variant: "destructive", title: "Network error" });
    } finally {
      setSavingList(false);
    }
  }

  async function handleSave() {
    if (!activeTeamId) return;
    setSaving(true);
    try {
      const res = await fetch(`/api/teams/${activeTeamId}/settings`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ clickup_api_token: token }),
      });
      const data = await res.json();
      if (!res.ok) {
        toast({ variant: "destructive", title: "Error", description: data?.detail || "Failed to save." });
        return;
      }
      setConnected(data.data?.clickup_connected ?? false);
      setToken("");
      toast({ title: "Saved", description: "ClickUp API token updated." });
    } catch {
      toast({ variant: "destructive", title: "Network error" });
    } finally {
      setSaving(false);
    }
  }

  async function handleTest() {
    if (!activeTeamId) return;
    setTesting(true);
    setClickupUser(null);
    try {
      const res = await fetch(`/api/teams/${activeTeamId}/settings/clickup-test`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(token ? { clickup_api_token: token } : {}),
      });
      const data = await res.json();
      const payload = data?.data ?? data;
      if (payload?.connected) {
        setConnected(true);
        setClickupUser(payload.clickup_user || null);
        toast({ title: "Connected", description: `Authenticated as ${payload.clickup_user || "ClickUp user"}.` });
      } else {
        setConnected(false);
        toast({ variant: "destructive", title: "Connection failed", description: payload?.detail || "Token is invalid or has no access." });
      }
    } catch {
      toast({ variant: "destructive", title: "Network error" });
    } finally {
      setTesting(false);
    }
  }

  async function handleRemove() {
    if (!activeTeamId) return;
    setSaving(true);
    try {
      const res = await fetch(`/api/teams/${activeTeamId}/settings`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ clickup_api_token: "" }),
      });
      if (res.ok) {
        setConnected(false);
        setClickupUser(null);
        toast({ title: "Removed", description: "ClickUp integration disconnected." });
      }
    } catch {
      toast({ variant: "destructive", title: "Network error" });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-6">
      {/* ClickUp Integration */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="flex items-center gap-2">
                ClickUp Integration
              </CardTitle>
              <CardDescription className="mt-1">
                Connect your ClickUp workspace to sync client records automatically.
              </CardDescription>
            </div>
            {connected === true && (
              <Badge className="bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200 gap-1">
                <CheckCircle2 className="h-3 w-3" /> Connected
              </Badge>
            )}
            {connected === false && (
              <Badge variant="secondary" className="gap-1 whitespace-nowrap">
                <XCircle className="h-3 w-3" /> Not connected
              </Badge>
            )}
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* How to get token */}
          <div className="rounded-md bg-muted px-4 py-3 text-sm space-y-1">
            <p className="font-medium">How to get your ClickUp API token:</p>
            <ol className="list-decimal list-inside space-y-1 text-muted-foreground">
              <li>Go to ClickUp → your profile avatar (bottom-left)</li>
              <li>Click <strong>Settings → Apps</strong></li>
              <li>Under <strong>API Token</strong>, click <strong>Generate</strong> or copy the existing token</li>
            </ol>
            <a
              href="https://app.clickup.com/settings/apps"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-primary hover:underline mt-1"
            >
              Open ClickUp Settings <ExternalLink className="h-3 w-3" />
            </a>
          </div>

          {/* Current status */}
          {connected && maskedToken && !token && (
            <div className="text-sm text-muted-foreground">
              Current token: <code className="font-mono bg-muted px-1 rounded">{maskedToken}</code>
              {clickupUser && <span className="ml-2 text-green-600">({clickupUser})</span>}
            </div>
          )}

          {/* Token input */}
          <div className="space-y-2">
            <Label htmlFor="clickup-token">
              {connected ? "Update API token" : "API token"}
            </Label>
            <div className="relative">
              <Input
                id="clickup-token"
                type={showToken ? "text" : "password"}
                placeholder={connected ? "Paste new token to replace…" : "pk_xxxxxxxxxxxxxxxxxxxxxxxx"}
                value={token}
                onChange={(e) => setToken(e.target.value)}
                className="pr-10"
              />
              <button
                type="button"
                onClick={() => setShowToken((v) => !v)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                tabIndex={-1}
              >
                {showToken ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
          </div>

          <div className="flex gap-3 flex-wrap">
            <Button onClick={handleSave} disabled={saving || !token}>
              {saving ? <><Loader2 className="h-4 w-4 mr-2 animate-spin" />Saving…</> : "Save token"}
            </Button>
            <Button variant="outline" onClick={handleTest} disabled={testing}>
              {testing ? <><Loader2 className="h-4 w-4 mr-2 animate-spin" />Testing…</> : "Test connection"}
            </Button>
            {connected && (
              <Button variant="ghost" className="text-destructive hover:text-destructive" onClick={handleRemove} disabled={saving}>
                Disconnect
              </Button>
            )}
          </div>

          {/* Issue list — where Digivault opens tasks. Separate from the token
              because it is a different question: the token says who we are,
              this says where our work goes. */}
          <div className="space-y-2 border-t pt-5">
            <Label htmlFor="clickup-list">Issue list</Label>
            <p className="text-xs text-muted-foreground">
              Digivault opens a task here when a website has a problem. Open the list in
              ClickUp and copy the ID from the URL —{" "}
              <code className="font-mono bg-muted px-1 rounded">app.clickup.com/…/li/901234</code>{" "}
              means the ID is <code className="font-mono bg-muted px-1 rounded">901234</code>.
              Leave it blank and no tasks are created.
            </p>
            <div className="flex gap-3 flex-wrap">
              <Input
                id="clickup-list"
                placeholder="901234"
                value={listId}
                onChange={(e) => setListId(e.target.value)}
                className="max-w-xs"
              />
              <Button
                variant="outline"
                onClick={handleSaveListId}
                disabled={savingList || listId.trim() === (settings?.clickup_list_id ?? "")}
              >
                {savingList ? <><Loader2 className="h-4 w-4 mr-2 animate-spin" />Saving…</> : "Save list"}
              </Button>
            </div>
          </div>

          {/* Team channel — where website problems are announced, with the
              owning developer addressed. Separate from the issue list: that is
              where work is tracked, this is where people are told. */}
          <div className="space-y-3 border-t pt-5">
            <Label htmlFor="clickup-chat">Web team channel</Label>
            <p className="text-xs text-muted-foreground">
              Digivault posts website problems here and addresses the developer assigned to
              that client. Leave it blank and nothing is posted.
            </p>

            {chatUrl && !editingChat ? (
              <div className="flex items-center gap-3 flex-wrap">
                <a
                  href={chatUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="text-sm inline-flex items-center gap-1 underline"
                >
                  Open channel in ClickUp <ExternalLink className="h-3 w-3" />
                </a>
                <Button variant="outline" size="sm" onClick={() => setEditingChat(true)}>
                  Change
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => handleSaveChatUrl("")}
                  disabled={savingChat}
                >
                  Clear
                </Button>
              </div>
            ) : (
              <div className="space-y-3">
                <Button
                  variant="outline"
                  onClick={handleCreateChannel}
                  disabled={creatingChannel || !connected}
                >
                  {creatingChannel ? (
                    <><Loader2 className="h-4 w-4 mr-2 animate-spin" />Creating…</>
                  ) : (
                    "Create web team channel"
                  )}
                </Button>
                <div className="flex gap-3 flex-wrap items-center">
                  <Input
                    id="clickup-chat"
                    placeholder="https://your-team.clickup.com/9001/chat/r/abc-123"
                    value={chatUrl}
                    onChange={(e) => setChatUrl(e.target.value)}
                    className="max-w-md"
                  />
                  <Button
                    variant="outline"
                    onClick={() => handleSaveChatUrl(chatUrl.trim())}
                    disabled={savingChat || !chatUrl.trim()}
                  >
                    {savingChat ? <><Loader2 className="h-4 w-4 mr-2 animate-spin" />Saving…</> : "Save link"}
                  </Button>
                </div>
              </div>
            )}

            {(matched.length > 0 || unmatched.length > 0) && (
              <div className="space-y-2 rounded-md bg-muted/40 p-3">
                <p className="text-xs font-medium">
                  {matched.length} member(s) matched in ClickUp
                  {unmatched.length > 0 && `, ${unmatched.length} not found`}
                </p>
                {unmatched.map((m) => (
                  <div key={m.user_id} className="flex items-center gap-2 flex-wrap">
                    <span className="text-xs text-muted-foreground min-w-48">{m.email}</span>
                    <Input
                      placeholder="ClickUp user ID"
                      value={overrides[m.user_id] ?? ""}
                      onChange={(e) => setOverrides({ ...overrides, [m.user_id]: e.target.value })}
                      className="max-w-40 h-8 text-xs"
                    />
                  </div>
                ))}
                <Button variant="outline" size="sm" onClick={handleSyncMembers}>
                  {Object.values(overrides).some((v) => v.trim()) ? "Save & re-sync" : "Re-sync members"}
                </Button>
              </div>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
