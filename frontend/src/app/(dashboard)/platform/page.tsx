"use client";

import { useCallback, useEffect, useState } from "react";
import { Building2, Globe, RefreshCw, Search, ShieldCheck, UserPlus, Users } from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useToast } from "@/hooks/use-toast";

interface Overview {
  users: number;
  active_users: number;
  teams: number;
  websites: number;
  signups_last_7_days: number;
  teams_by_plan: Record<string, number>;
  plans: { value: string; label: string }[];
}

interface TeamRow {
  id: string;
  name: string;
  plan: string;
  plan_label: string;
  require_2fa: boolean;
  owner_email: string;
  member_count: number;
  website_count: number;
  created_at: string;
}

interface UserRow {
  id: string;
  email: string;
  name: string;
  is_active: boolean;
  is_platform_admin: boolean;
  totp_enabled: boolean;
  last_login: string | null;
  created_at: string;
  teams: { id: string; name: string; role: string; plan: string }[];
}

const fmt = (v: string | null) => (v ? new Date(v).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" }) : "Never");

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url, { cache: "no-store" });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body?.detail ?? body?.errors?.[0]?.message ?? `HTTP ${res.status}`);
  return body as T;
}

export default function PlatformPage() {
  const { toast } = useToast();
  const [tab, setTab] = useState<"teams" | "users">("teams");
  const [q, setQ] = useState("");
  const [overview, setOverview] = useState<Overview | null>(null);
  const [teams, setTeams] = useState<TeamRow[]>([]);
  const [users, setUsers] = useState<UserRow[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async (query: string) => {
    setLoading(true);
    setError("");
    try {
      const qs = query ? `?q=${encodeURIComponent(query)}` : "";
      const [o, t, u] = await Promise.all([
        getJson<Overview>("/api/platform/overview"),
        getJson<TeamRow[]>(`/api/platform/teams${qs}`),
        getJson<UserRow[]>(`/api/platform/users${qs}`),
      ]);
      setOverview(o);
      setTeams(t);
      setUsers(u);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load platform data.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    (async () => {
      await Promise.resolve();
      load("");
    })();
  }, [load]);

  async function patch(url: string, body: Record<string, unknown>) {
    const res = await fetch(url, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data?.detail ?? data?.errors?.[0]?.message ?? "Update failed");
    return data;
  }

  async function changePlan(team: TeamRow, plan: string) {
    try {
      const updated = (await patch(`/api/platform/teams/${team.id}`, { plan })) as TeamRow;
      setTeams((rows) => rows.map((r) => (r.id === team.id ? updated : r)));
      toast({ title: "Plan updated", description: `${team.name} is now on ${updated.plan_label}.` });
    } catch (e) {
      toast({ variant: "destructive", title: "Could not change plan", description: String((e as Error).message) });
    }
  }

  async function toggle2fa(team: TeamRow) {
    try {
      const updated = (await patch(`/api/platform/teams/${team.id}`, { require_2fa: !team.require_2fa })) as TeamRow;
      setTeams((rows) => rows.map((r) => (r.id === team.id ? updated : r)));
    } catch (e) {
      toast({ variant: "destructive", title: "Could not update", description: String((e as Error).message) });
    }
  }

  async function toggleActive(user: UserRow) {
    try {
      const updated = (await patch(`/api/platform/users/${user.id}`, { is_active: !user.is_active })) as UserRow;
      setUsers((rows) => rows.map((r) => (r.id === user.id ? updated : r)));
      toast({ title: updated.is_active ? "User activated" : "User deactivated", description: user.email });
    } catch (e) {
      toast({ variant: "destructive", title: "Could not update user", description: String((e as Error).message) });
    }
  }

  if (error) {
    return (
      <div className="p-6">
        <Card>
          <CardContent className="py-10 text-center text-muted-foreground">
            {error.includes("permission") || error.includes("403") ? "Only the platform owner can open this page." : error}
          </CardContent>
        </Card>
      </div>
    );
  }

  const stats = overview
    ? [
        { icon: Users, label: "Users", value: overview.users, sub: `${overview.active_users} active` },
        { icon: Building2, label: "Workspaces", value: overview.teams, sub: Object.entries(overview.teams_by_plan).map(([k, v]) => `${v} ${k}`).join(", ") },
        { icon: Globe, label: "Websites", value: overview.websites, sub: "across all workspaces" },
        { icon: UserPlus, label: "New users", value: overview.signups_last_7_days, sub: "last 7 days" },
      ]
    : [];

  return (
    <div className="space-y-6 p-4 md:p-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold"><ShieldCheck className="h-6 w-6 text-primary" /> Platform</h1>
          <p className="text-sm text-muted-foreground">Every workspace and user on Stacks Monitor. Change plans after a customer pays.</p>
        </div>
        <Button variant="outline" size="sm" onClick={() => load(q)} disabled={loading}>
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} /> Refresh
        </Button>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {stats.map(({ icon: Icon, label, value, sub }) => (
          <Card key={label}>
            <CardContent className="flex items-start gap-3 p-5">
              <Icon className="mt-1 h-5 w-5 text-primary" />
              <div className="min-w-0">
                <p className="text-sm text-muted-foreground">{label}</p>
                <p className="dv-num text-2xl font-bold">{value}</p>
                <p className="truncate text-xs text-muted-foreground">{sub}</p>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      <Card>
        <CardHeader className="flex flex-col gap-3 space-y-0 md:flex-row md:items-center md:justify-between">
          <div className="flex gap-1 rounded-lg bg-muted p-1">
            {(["teams", "users"] as const).map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setTab(t)}
                className={`rounded-md px-3 py-1.5 text-sm font-medium ${tab === t ? "bg-card shadow-sm" : "text-muted-foreground"}`}
              >
                {t === "teams" ? `Workspaces (${teams.length})` : `Users (${users.length})`}
              </button>
            ))}
          </div>
          <form
            className="flex w-full gap-2 md:w-80"
            onSubmit={(e) => {
              e.preventDefault();
              load(q);
            }}
          >
            <Input placeholder="Search name or email" value={q} onChange={(e) => setQ(e.target.value)} />
            <Button type="submit" size="icon" variant="outline" aria-label="Search"><Search className="h-4 w-4" /></Button>
          </form>
        </CardHeader>
        <CardContent className="overflow-x-auto p-0">
          {tab === "teams" ? (
            <table className="w-full min-w-[820px] text-sm">
              <thead className="border-y bg-muted/50 text-left text-xs uppercase text-muted-foreground">
                <tr>
                  <th className="px-4 py-3">Workspace</th>
                  <th className="px-4 py-3">Owner</th>
                  <th className="px-4 py-3">Sites</th>
                  <th className="px-4 py-3">Members</th>
                  <th className="px-4 py-3">Plan</th>
                  <th className="px-4 py-3">2FA required</th>
                  <th className="px-4 py-3">Created</th>
                </tr>
              </thead>
              <tbody>
                {teams.map((t) => (
                  <tr key={t.id} className="border-b last:border-0">
                    <td className="px-4 py-3 font-medium">{t.name}</td>
                    <td className="px-4 py-3 text-muted-foreground">{t.owner_email}</td>
                    <td className="dv-num px-4 py-3">{t.website_count}</td>
                    <td className="dv-num px-4 py-3">{t.member_count}</td>
                    <td className="px-4 py-3">
                      <select
                        aria-label={`Plan for ${t.name}`}
                        value={t.plan}
                        onChange={(e) => changePlan(t, e.target.value)}
                        className="h-9 rounded-md border bg-background px-2 text-sm"
                      >
                        {(overview?.plans ?? []).map((p) => (
                          <option key={p.value} value={p.value}>{p.label}</option>
                        ))}
                      </select>
                    </td>
                    <td className="px-4 py-3">
                      <button type="button" onClick={() => toggle2fa(t)} title="Click to toggle">
                        <Badge variant={t.require_2fa ? "default" : "secondary"}>{t.require_2fa ? "Required" : "Optional"}</Badge>
                      </button>
                    </td>
                    <td className="px-4 py-3 text-muted-foreground">{fmt(t.created_at)}</td>
                  </tr>
                ))}
                {!teams.length && !loading && (
                  <tr><td colSpan={7} className="px-4 py-10 text-center text-muted-foreground">No workspaces found.</td></tr>
                )}
              </tbody>
            </table>
          ) : (
            <table className="w-full min-w-[820px] text-sm">
              <thead className="border-y bg-muted/50 text-left text-xs uppercase text-muted-foreground">
                <tr>
                  <th className="px-4 py-3">User</th>
                  <th className="px-4 py-3">Workspaces</th>
                  <th className="px-4 py-3">2FA</th>
                  <th className="px-4 py-3">Last login</th>
                  <th className="px-4 py-3">Joined</th>
                  <th className="px-4 py-3">Status</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.id} className="border-b last:border-0">
                    <td className="px-4 py-3">
                      <p className="font-medium">{u.name || u.email}</p>
                      <p className="text-xs text-muted-foreground">
                        {u.email} {u.is_platform_admin && <Badge className="ml-1">Platform owner</Badge>}
                      </p>
                    </td>
                    <td className="px-4 py-3 text-muted-foreground">
                      {u.teams.length ? u.teams.map((t) => `${t.name} (${t.role})`).join(", ") : "None"}
                    </td>
                    <td className="px-4 py-3">{u.totp_enabled ? <Badge>On</Badge> : <Badge variant="secondary">Off</Badge>}</td>
                    <td className="px-4 py-3 text-muted-foreground">{fmt(u.last_login)}</td>
                    <td className="px-4 py-3 text-muted-foreground">{fmt(u.created_at)}</td>
                    <td className="px-4 py-3">
                      <Button
                        size="sm"
                        variant={u.is_active ? "outline" : "default"}
                        disabled={u.is_platform_admin}
                        onClick={() => toggleActive(u)}
                      >
                        {u.is_active ? "Deactivate" : "Activate"}
                      </Button>
                    </td>
                  </tr>
                ))}
                {!users.length && !loading && (
                  <tr><td colSpan={6} className="px-4 py-10 text-center text-muted-foreground">No users found.</td></tr>
                )}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
