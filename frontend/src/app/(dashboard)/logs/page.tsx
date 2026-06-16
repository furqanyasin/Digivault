"use client";

import { useEffect, useState, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ClipboardList, RefreshCw } from "lucide-react";

interface LogEntry {
  id: string;
  actor_email: string | null;
  actor_name: string;
  action: string;
  action_label: string;
  resource_type: string;
  description: string;
  ip_address: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
}

interface Member {
  id: string;
  role: string;
  user: { id: string; email: string; first_name: string; last_name: string };
}

const ACTION_VARIANTS: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  "auth.login": "default",
  "auth.login_failed": "destructive",
  "auth.logout": "secondary",
  "auth.2fa_enabled": "default",
  "auth.2fa_disabled": "destructive",
  "credential.revealed": "secondary",
  "credential.deleted": "destructive",
  "website.scan_triggered": "default",
  "team.member_removed": "destructive",
  "team.member_role_changed": "secondary",
};

function actionVariant(action: string) {
  return ACTION_VARIANTS[action] ?? "outline";
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

function renderMetadata(action: string, metadata: Record<string, unknown>): string | null {
  if (!metadata || Object.keys(metadata).length === 0) return null;
  if (action === "team.member_role_changed" && metadata.previous_role && metadata.new_role) {
    return `${metadata.previous_role} → ${metadata.new_role}`;
  }
  if (action === "team.member_removed" && metadata.role) {
    return `role: ${metadata.role}`;
  }
  if (action === "settings.team_name_changed" && metadata.previous_name && metadata.new_name) {
    return `"${metadata.previous_name}" → "${metadata.new_name}"`;
  }
  if (action === "credential.updated" && Array.isArray(metadata.fields_changed)) {
    return `fields changed: ${(metadata.fields_changed as string[]).join(", ")}`;
  }
  return null;
}

function initials(name: string, email: string | null) {
  if (name.trim()) return name.trim().slice(0, 2).toUpperCase();
  return (email ?? "?").slice(0, 2).toUpperCase();
}

export default function LogsPage() {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [members, setMembers] = useState<Member[]>([]);
  const [myRole, setMyRole] = useState<string>("viewer");
  // Preselect a member when arriving via /logs?user_id=… (e.g. the
  // "View activity" link on the Members page).
  const [selectedUser, setSelectedUser] = useState<string>(() => {
    if (typeof window === "undefined") return "";
    return new URLSearchParams(window.location.search).get("user_id") ?? "";
  });
  const [page, setPage] = useState(1);
  const [hasNext, setHasNext] = useState(false);

  const isManager = myRole === "manager" || myRole === "owner";

  const fetchLogs = useCallback(async (userId: string, pg: number) => {
    setLoading(true);
    const qs = new URLSearchParams({ page: String(pg) });
    if (userId) qs.set("user_id", userId);
    const res = await fetch(`/api/logs?${qs}`);
    if (res.ok) {
      const envelope = await res.json();
      // List responses are enveloped as { data: [...rows], meta: {count, next, previous} }.
      // (StandardPagination puts the array in `data` and counts in `meta`.)
      const payload = envelope?.data ?? envelope;
      const rows: LogEntry[] = Array.isArray(payload) ? payload : (payload?.results ?? []);
      const meta = envelope?.meta ?? {};
      setLogs(rows);
      setTotal(meta.count ?? payload?.count ?? rows.length);
      setHasNext(!!(meta.next ?? payload?.next));
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    (async () => {
      const [meRes, teamsRes] = await Promise.all([
        fetch("/api/auth/me"),
        fetch("/api/auth/teams"),
      ]);
      if (!meRes.ok || !teamsRes.ok) return;
      const meEnv = await meRes.json();
      const teamsEnv = await teamsRes.json();
      const me = meEnv?.data ?? meEnv;
      const teams: Array<{ id: string; my_role?: string }> = teamsEnv?.data ?? teamsEnv;
      const activeTeamId = me?.active_team;
      if (!activeTeamId) return;

      // Authoritative role comes from the team's own `my_role` field.
      const activeTeam = Array.isArray(teams)
        ? teams.find((t) => t.id === activeTeamId)
        : null;
      setMyRole(activeTeam?.my_role ?? "viewer");

      // Members list powers the "Filter by member" dropdown for managers.
      const membersRes = await fetch(`/api/teams/${activeTeamId}/members`);
      if (membersRes.ok) {
        const membersEnv = await membersRes.json();
        const membersList: Member[] = membersEnv?.data ?? membersEnv;
        if (Array.isArray(membersList)) setMembers(membersList);
      }
    })();
  }, []);

  useEffect(() => {
    fetchLogs(selectedUser, page);
  }, [fetchLogs, selectedUser, page]);

  function handleUserChange(uid: string) {
    setSelectedUser(uid);
    setPage(1);
  }

  return (
    <div className="p-8 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight flex items-center gap-2">
            <ClipboardList className="h-7 w-7" />
            Activity Log
          </h1>
          <p className="text-muted-foreground mt-1">
            {isManager ? "All team activity" : "Your activity"} — {total} events
          </p>
        </div>
        <button
          onClick={() => fetchLogs(selectedUser, page)}
          className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground"
        >
          <RefreshCw className="h-4 w-4" />
          Refresh
        </button>
      </div>

      {isManager && members.length > 0 && (
        <div className="flex items-center gap-3">
          <label className="text-sm font-medium">Filter by member:</label>
          <select
            value={selectedUser}
            onChange={(e) => handleUserChange(e.target.value)}
            className="border rounded-md px-3 py-1.5 text-sm bg-background"
          >
            <option value="">All members</option>
            {members.map((m) => (
              <option key={m.user.id} value={m.user.id}>
                {m.user.first_name} {m.user.last_name} — {m.user.email} ({m.role})
              </option>
            ))}
          </select>
        </div>
      )}

      <Card>
        <CardHeader className="pb-0">
          <CardTitle className="text-base">Events</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {loading ? (
            <div className="text-center py-12 text-muted-foreground text-sm">Loading…</div>
          ) : logs.length === 0 ? (
            <div className="text-center py-12 text-muted-foreground text-sm">No activity found.</div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b">
                  <th className="text-left px-4 py-3 font-medium text-muted-foreground">When</th>
                  <th className="text-left px-4 py-3 font-medium text-muted-foreground">Who</th>
                  <th className="text-left px-4 py-3 font-medium text-muted-foreground">Action</th>
                  <th className="text-left px-4 py-3 font-medium text-muted-foreground">Description</th>
                  <th className="text-left px-4 py-3 font-medium text-muted-foreground">IP</th>
                </tr>
              </thead>
              <tbody>
                {logs.map((log) => (
                  <tr key={log.id} className="border-b last:border-0 hover:bg-muted/30">
                    <td className="px-4 py-3 whitespace-nowrap text-muted-foreground text-xs">
                      {formatDate(log.created_at)}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <span className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-primary/10 text-primary text-xs font-semibold shrink-0">
                          {initials(log.actor_name, log.actor_email)}
                        </span>
                        <span className="text-xs">
                          <div className="font-medium">{log.actor_name || log.actor_email || "System"}</div>
                          {log.actor_name && log.actor_email && (
                            <div className="text-muted-foreground">{log.actor_email}</div>
                          )}
                        </span>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <Badge variant={actionVariant(log.action)} className="text-xs">
                        {log.action_label}
                      </Badge>
                    </td>
                    <td className="px-4 py-3 text-muted-foreground">
                      <div>{log.description}</div>
                      {renderMetadata(log.action, log.metadata) && (
                        <div className="text-xs text-muted-foreground/60 mt-0.5 font-mono">
                          {renderMetadata(log.action, log.metadata)}
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-3 text-xs font-mono text-muted-foreground">
                      {log.ip_address ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>

      {(page > 1 || hasNext) && (
        <div className="flex items-center justify-between text-sm">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page === 1}
            className="px-3 py-1 border rounded disabled:opacity-40"
          >
            Previous
          </button>
          <span className="text-muted-foreground">Page {page}</span>
          <button
            onClick={() => setPage((p) => p + 1)}
            disabled={!hasNext}
            className="px-3 py-1 border rounded disabled:opacity-40"
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}
