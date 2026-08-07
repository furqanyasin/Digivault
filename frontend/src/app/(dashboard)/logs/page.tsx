"use client";

import { useEffect, useState, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ClipboardList, RefreshCw, ShieldAlert } from "lucide-react";

interface LogEntry {
  id: string;
  actor_email: string | null;
  actor_name: string;
  action: string;
  action_label: string;
  resource_type: string;
  website_name: string;
  client_name: string;
  description: string;
  ip_address: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
}

interface NamedRef { id: string; name: string; }

interface Member {
  id: string;
  role: string;
  user: { id: string; email: string; first_name: string; last_name: string };
}

/** Named views over the log. Each maps to a set of action types, sent to the
 *  API as ?actions=a,b,c — approvals in particular span two action types, so a
 *  single ?action= cannot express them. */
const VIEWS = [
  { key: "all", label: "All activity", actions: [] as string[] },
  {
    key: "websites",
    label: "Website changes",
    actions: [
      "website.created", "website.updated", "website.deleted",
      "website.scan_triggered", "website.snippet_verified",
      "website.snippet_regenerated", "website.change_acknowledged",
      "website.wp_login", "website.wp_sso_secret_rotated",
      "script.reviewed", "domain.refreshed",
    ],
  },
  {
    key: "approvals",
    label: "Approvals",
    actions: ["script.reviewed", "website.change_acknowledged"],
  },
  {
    key: "clients",
    label: "Client changes",
    actions: [
      "client.created", "client.updated", "client.status_changed",
      "client.synced", "client.imported", "client.exported",
    ],
  },
  {
    key: "credentials",
    label: "Credentials",
    actions: [
      "credential.created", "credential.revealed", "credential.updated",
      "credential.deleted", "credential.shared", "credential.unshared",
    ],
  },
  {
    key: "security",
    label: "Team & security",
    actions: [
      "auth.login", "auth.login_failed", "auth.logout",
      "auth.2fa_enabled", "auth.2fa_disabled", "auth.2fa_setup_started",
      "auth.backup_codes_regenerated",
      "team.member_invited", "team.member_joined",
      "team.member_role_changed", "team.member_removed", "team.created",
      "settings.team_name_changed", "settings.integration_updated",
    ],
  },
] as const;

/** Time windows for the When column. Sent as ?start=<iso>, which the API
 *  already supports. */
const SINCE_OPTIONS = [
  { key: "", label: "Any time", days: 0 },
  { key: "1", label: "Last 24 hours", days: 1 },
  { key: "7", label: "Last 7 days", days: 7 },
  { key: "30", label: "Last 30 days", days: 30 },
  { key: "90", label: "Last 90 days", days: 90 },
] as const;

type ViewKey = (typeof VIEWS)[number]["key"];

// Matches the Clients table. All within the API's max_page_size of 100.
const PAGE_SIZES = [5, 10, 15, 20, 25, 30, 50, 100] as const;

// align-top so labels line up across headers of differing height, since the
// filterable ones carry a control underneath.
const TH = "text-left px-4 py-3 align-top font-medium text-muted-foreground";
const COL_FILTER =
  "mt-1.5 w-full min-w-[110px] border rounded px-1.5 py-1 text-xs font-normal bg-background text-foreground";
type PageSize = (typeof PAGE_SIZES)[number];

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
  const [search, setSearch] = useState("");
  // Debounced copy — the log is paginated server-side, so searching has to be a
  // request; firing one per keystroke would hammer the API.
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [view, setView] = useState<ViewKey>("all");
  // null until the role check resolves, so the page renders neither the log nor
  // the access notice while it is still unknown.
  const [roleResolved, setRoleResolved] = useState(false);
  const [roleError, setRoleError] = useState("");
  const [myFeatures, setMyFeatures] = useState<string[]>([]);
  const [clients, setClients] = useState<NamedRef[]>([]);
  const [websites, setWebsites] = useState<(NamedRef & { client: string | null })[]>([]);
  const [selectedClient, setSelectedClient] = useState("");
  const [selectedWebsite, setSelectedWebsite] = useState("");
  const [pageSize, setPageSize] = useState<PageSize>(25);
  const [since, setSince] = useState("");

  const isManager = myRole === "manager" || myRole === "owner";
  // Owner has every feature implicitly; everyone else carries an explicit list.
  // Drives which filter columns render — a member with no Clients section has
  // no use for a client filter, and the dropdown would only list accounts they
  // cannot open.
  const can = (feature: string) => myRole === "owner" || myFeatures.includes(feature);

  useEffect(() => {
    const t = setTimeout(() => { setDebouncedSearch(search); setPage(1); }, 300);
    return () => clearTimeout(t);
  }, [search]);

  const fetchLogs = useCallback(async (
    userId: string, pg: number, q: string, v: ViewKey,
    clientId: string, websiteId: string, ps: PageSize, sinceDays: string,
  ) => {
    setLoading(true);
    const qs = new URLSearchParams({ page: String(pg), page_size: String(ps) });
    if (sinceDays) {
      const from = new Date(Date.now() - Number(sinceDays) * 86400000);
      qs.set("start", from.toISOString());
    }
    if (userId) qs.set("user_id", userId);
    if (clientId) qs.set("client_id", clientId);
    if (websiteId) qs.set("website_id", websiteId);
    if (q.trim()) qs.set("q", q.trim());
    const actions = VIEWS.find((x) => x.key === v)?.actions ?? [];
    if (actions.length) qs.set("actions", actions.join(","));
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
      // Fail loudly rather than silently reading as "viewer" — that is what
      // turned a missing BFF route into a bogus "Managers only" for an owner.
      if (!meRes.ok || !teamsRes.ok) {
        setRoleError(`Could not read your role (me: ${meRes.status}, teams: ${teamsRes.status}).`);
        setRoleResolved(true);
        return;
      }
      const meEnv = await meRes.json();
      const teamsEnv = await teamsRes.json();
      const me = meEnv?.data ?? meEnv;
      const teams: Array<{ id: string; my_role?: string; my_features?: string[] }> =
        teamsEnv?.data ?? teamsEnv;
      const activeTeamId = me?.active_team;
      if (!activeTeamId) { setRoleResolved(true); return; }

      // Authoritative role comes from the team's own `my_role` field.
      const activeTeam = Array.isArray(teams)
        ? teams.find((t) => t.id === activeTeamId)
        : null;
      const role = activeTeam?.my_role ?? "viewer";
      const features = activeTeam?.my_features ?? [];
      setMyRole(role);
      setMyFeatures(features);
      // ?user_id= is a manager-only filter and the API ignores it for everyone
      // else. Dropping it here stops a non-manager who followed such a link
      // from seeing a "Filtered" chip they have no control to clear.
      if (role !== "manager" && role !== "owner") setSelectedUser("");

      const allowed = (feature: string) => role === "owner" || features.includes(feature);

      // Client and website lists power their filter dropdowns. Both are small
      // and unpaginated, so one call each is enough — and each is skipped
      // outright when its filter column won't render, rather than fetching a
      // list to populate a control nobody sees.
      const [clientsRes, sitesRes] = await Promise.all([
        allowed("clients") ? fetch("/api/clients?page_size=200") : null,
        allowed("websites") ? fetch("/api/websites?page_size=200") : null,
      ]);
      if (clientsRes?.ok) {
        const j = await clientsRes.json();
        const list = Array.isArray(j?.clients) ? j.clients : (j?.data ?? j);
        if (Array.isArray(list)) setClients(list.map((c) => ({ id: c.id, name: c.name })));
      }
      if (sitesRes?.ok) {
        const j = await sitesRes.json();
        const list = Array.isArray(j?.websites) ? j.websites : (j?.data ?? j);
        if (Array.isArray(list)) {
          setWebsites(list.map((w) => ({ id: w.id, name: w.name || w.domain, client: w.client ?? null })));
        }
      }

      // Members list powers the "Filter by member" dropdown, which only
      // managers get — a non-manager's rows are all their own, so there is
      // nobody to filter by and no reason to ask for the roster.
      if (role === "manager" || role === "owner") {
        const membersRes = await fetch(`/api/teams/${activeTeamId}/members`);
        if (membersRes.ok) {
          const membersEnv = await membersRes.json();
          const membersList: Member[] = membersEnv?.data ?? membersEnv;
          if (Array.isArray(membersList)) setMembers(membersList);
        }
      }
      setRoleResolved(true);
    })();
  }, []);

  useEffect(() => {
    if (!roleResolved) return;
    fetchLogs(selectedUser, page, debouncedSearch, view, selectedClient, selectedWebsite, pageSize, since);
  }, [fetchLogs, selectedUser, page, debouncedSearch, view, roleResolved,
      selectedClient, selectedWebsite, pageSize, since]);

  function handleUserChange(uid: string) {
    setSelectedUser(uid);
    setPage(1);
  }

  // A failure to read the role is a bug, not a permission decision, so it still
  // stops the page — rendering the log against an unknown role would be
  // guessing. The "Managers only" refusal that used to live here is gone: the
  // API scopes a non-manager to their own rows, so there is nothing to refuse.
  if (roleResolved && roleError) {
    return (
      <div className="p-8">
        <div className="mx-auto max-w-md rounded-xl border p-8 text-center">
          <ShieldAlert className="mx-auto h-10 w-10 text-muted-foreground" aria-hidden />
          <h1 className="mt-4 text-xl font-semibold">Couldn&apos;t check your access</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            {roleError} Reload the page — if it keeps happening, this is a bug
            rather than a permission problem.
          </p>
        </div>
      </div>
    );
  }

  const activeFilters = Boolean(
    debouncedSearch || selectedUser || selectedClient || selectedWebsite
    || since || view !== "all"
  );
  // Narrow the website list to the chosen client, so the two filters can't be
  // combined into something that matches nothing.
  const websiteOptions = selectedClient
    ? websites.filter((w) => w.client === selectedClient)
    : websites;

  return (
    <div className="p-8 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight flex items-center gap-2">
            <ClipboardList className="h-7 w-7" />
            {isManager ? "Activity Log" : "My activity"}
          </h1>
          {/* The title has to say whose actions these are. The API returns the
              whole team for a manager and only your own for everyone else, and
              a shared heading would misdescribe one of them. */}
          <p className="text-muted-foreground mt-1">
            {isManager ? "All team activity" : "Your actions"} — {total} event
            {total !== 1 ? "s" : ""}
          </p>
        </div>
        <button
          onClick={() => fetchLogs(selectedUser, page, debouncedSearch, view, selectedClient, selectedWebsite, pageSize, since)}
          className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground"
        >
          <RefreshCw className="h-4 w-4" />
          Refresh
        </button>
      </div>

      {/* Filters live in the column headers instead of a separate bar above the
          table, so each control sits under the data it narrows. A "Clear" link
          appears here only once something is filtered. */}
      {activeFilters && (
        <div className="flex items-center gap-2 text-sm">
          <span className="text-muted-foreground">Filtered</span>
          <button
            type="button"
            onClick={() => {
              setSearch(""); setDebouncedSearch("");
              setSelectedUser(""); setSelectedClient(""); setSelectedWebsite("");
              setView("all"); setSince(""); setPage(1);
            }}
            className="text-muted-foreground underline hover:text-foreground"
          >
            Clear all filters
          </button>
        </div>
      )}

      <Card>
        <CardHeader>
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
                  <th className={TH}>
                    When
                    <select
                      aria-label="Filter by time"
                      value={since}
                      onChange={(e) => { setSince(e.target.value); setPage(1); }}
                      className={COL_FILTER}
                    >
                      {SINCE_OPTIONS.map((o) => (
                        <option key={o.key} value={o.key}>{o.label}</option>
                      ))}
                    </select>
                  </th>
                  {/* Every row is the viewer's own for a non-manager, so a Who
                      column would repeat one name down the whole table. */}
                  {isManager && (
                    <th className={TH}>
                      Who
                      <select
                        aria-label="Filter by member"
                        value={selectedUser}
                        onChange={(e) => handleUserChange(e.target.value)}
                        className={COL_FILTER}
                      >
                        <option value="">All members</option>
                        {members.map((m) => (
                          <option key={m.user.id} value={m.user.id}>
                            {`${m.user.first_name} ${m.user.last_name}`.trim() || m.user.email}
                          </option>
                        ))}
                      </select>
                    </th>
                  )}
                  <th className={TH}>
                    Action
                    <select
                      aria-label="Filter by action"
                      value={view}
                      onChange={(e) => { setView(e.target.value as ViewKey); setPage(1); }}
                      className={COL_FILTER}
                    >
                      {VIEWS.map((v) => (
                        <option key={v.key} value={v.key}>{v.label}</option>
                      ))}
                    </select>
                  </th>
                  {can("clients") && (
                    <th className={TH}>
                      Client
                      <select
                        aria-label="Filter by client"
                        value={selectedClient}
                        onChange={(e) => {
                          setSelectedClient(e.target.value);
                          setSelectedWebsite("");  // may not belong to this client
                          setPage(1);
                        }}
                        className={COL_FILTER}
                      >
                        <option value="">All clients</option>
                        {clients.map((c) => (
                          <option key={c.id} value={c.id}>{c.name}</option>
                        ))}
                      </select>
                    </th>
                  )}
                  {can("websites") && (
                    <th className={TH}>
                      Website
                      <select
                        aria-label="Filter by website"
                        value={selectedWebsite}
                        onChange={(e) => { setSelectedWebsite(e.target.value); setPage(1); }}
                        className={COL_FILTER}
                      >
                        <option value="">All websites</option>
                        {websiteOptions.map((w) => (
                          <option key={w.id} value={w.id}>{w.name}</option>
                        ))}
                      </select>
                    </th>
                  )}
                  <th className={TH}>
                    Description
                    <input
                      type="search"
                      aria-label="Search activity"
                      placeholder="Search…"
                      value={search}
                      onChange={(e) => setSearch(e.target.value)}
                      className={COL_FILTER}
                    />
                  </th>
                  <th className={TH}>IP</th>
                </tr>
              </thead>
              <tbody>
                {logs.map((log) => (
                  <tr key={log.id} className="border-b last:border-0 hover:bg-muted/30">
                    <td className="px-4 py-3 whitespace-nowrap text-muted-foreground text-xs">
                      {formatDate(log.created_at)}
                    </td>
                    {isManager && (
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
                    )}
                    <td className="px-4 py-3">
                      <Badge variant={actionVariant(log.action)} className="text-xs">
                        {log.action_label}
                      </Badge>
                    </td>
                    {can("clients") && (
                      <td className="px-4 py-3 text-sm max-w-[150px] truncate" title={log.client_name || undefined}>
                        {log.client_name || <span className="text-muted-foreground">—</span>}
                      </td>
                    )}
                    {can("websites") && (
                      <td className="px-4 py-3 text-sm max-w-[150px] truncate" title={log.website_name || undefined}>
                        {log.website_name || <span className="text-muted-foreground">—</span>}
                      </td>
                    )}
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

      {/* Per-page sits with the pager so both paging controls are together. It
          shows even on a single page — it is how you change the page size. */}
      <div className="flex items-center justify-between gap-3 text-sm flex-wrap">
        <div className="flex items-center gap-2">
          <label htmlFor="log-page-size" className="text-muted-foreground">Per page:</label>
          <select
            id="log-page-size"
            value={pageSize}
            onChange={(e) => { setPageSize(Number(e.target.value) as PageSize); setPage(1); }}
            className="border rounded-md px-2 py-1 text-xs bg-background"
          >
            {PAGE_SIZES.map((ps) => <option key={ps} value={ps}>{ps}</option>)}
          </select>
          <span className="text-muted-foreground">
            {total} event{total !== 1 ? "s" : ""}
          </span>
        </div>

        {(page > 1 || hasNext) && (
          <div className="flex items-center gap-2">
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
    </div>
  );
}
