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
        </CardContent>
      </Card>
    </div>
  );
}
