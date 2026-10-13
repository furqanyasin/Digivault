"use client";

import { useMemo, useState, useTransition } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  UserPlus, Trash2, Check, ShieldAlert, ShieldCheck, ShieldOff, X, ScrollText,
  MoreHorizontal, Search, SlidersHorizontal, KeyRound, Users, ArrowRightLeft,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PasswordInput } from "@/components/ui/password-input";
import { Label } from "@/components/ui/label";
import { fmtDate, cn } from "@/lib/utils";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel,
  DropdownMenuRadioGroup, DropdownMenuRadioItem, DropdownMenuSeparator,
  DropdownMenuSub, DropdownMenuSubContent, DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { TeamMember, SubTeam } from "@/lib/api";
import { TeamGroupsPanel } from "@/components/team-groups-panel";
import { CredentialHandoverDialog } from "@/components/credential-handover-dialog";
import { roleLabel } from "@/lib/roles";

// Editor and the legacy "seo" role are retired — only these are offered now.
// (Legacy roles stay valid in the backend so existing members still work; they
// just aren't listed.)
const ROLES = ["viewer", "developer", "seo_executive", "manager", "custom", "owner"] as const;
type Role = typeof ROLES[number];

const ROLE_LEVELS: Record<string, number> = {
  viewer: 1, developer: 2, custom: 2, editor: 2, seo: 2, seo_executive: 2,
  manager: 3, owner: 4,
};


// Role pills carry a light and a dark treatment — the dashboard ships both
// themes, and a single fixed palette washes out in one of them.
const ROLE_BADGE: Record<string, string> = {
  owner:     "bg-amber-100 text-amber-800 border-amber-200 dark:bg-amber-500/15 dark:text-amber-300 dark:border-amber-500/25",
  manager:   "bg-blue-100 text-blue-800 border-blue-200 dark:bg-blue-500/15 dark:text-blue-300 dark:border-blue-500/25",
  developer: "bg-emerald-100 text-emerald-800 border-emerald-200 dark:bg-emerald-500/15 dark:text-emerald-300 dark:border-emerald-500/25",
  custom:    "bg-indigo-100 text-indigo-800 border-indigo-200 dark:bg-indigo-500/15 dark:text-indigo-300 dark:border-indigo-500/25",
  editor:    "bg-purple-100 text-purple-800 border-purple-200 dark:bg-purple-500/15 dark:text-purple-300 dark:border-purple-500/25",
  seo:       "bg-teal-100 text-teal-800 border-teal-200 dark:bg-teal-500/15 dark:text-teal-300 dark:border-teal-500/25",
  seo_executive: "bg-teal-100 text-teal-800 border-teal-200 dark:bg-teal-500/15 dark:text-teal-300 dark:border-teal-500/25",
  viewer:    "bg-slate-100 text-slate-700 border-slate-200 dark:bg-slate-400/15 dark:text-slate-300 dark:border-slate-400/25",
};

// Avatar wash, tinted by role so seniority reads down the column at a glance.
const ROLE_AVATAR: Record<string, string> = {
  owner:     "bg-gradient-to-br from-amber-400/30 to-amber-600/10 text-amber-700 dark:text-amber-300",
  manager:   "bg-gradient-to-br from-blue-400/30 to-blue-600/10 text-blue-700 dark:text-blue-300",
  developer: "bg-gradient-to-br from-emerald-400/30 to-emerald-600/10 text-emerald-700 dark:text-emerald-300",
  custom:    "bg-gradient-to-br from-indigo-400/30 to-indigo-600/10 text-indigo-700 dark:text-indigo-300",
  editor:    "bg-gradient-to-br from-purple-400/30 to-purple-600/10 text-purple-700 dark:text-purple-300",
  seo:       "bg-gradient-to-br from-teal-400/30 to-teal-600/10 text-teal-700 dark:text-teal-300",
  seo_executive: "bg-gradient-to-br from-teal-400/30 to-teal-600/10 text-teal-700 dark:text-teal-300",
  viewer:    "bg-gradient-to-br from-slate-400/30 to-slate-600/10 text-slate-700 dark:text-slate-300",
};

// Feature keys a custom member's access can be limited to — mirrors the backend
// CUSTOM_FEATURE_KEYS and the sidebar nav.
const FEATURES: { key: string; label: string }[] = [
  { key: "clients", label: "Clients" },
  { key: "websites", label: "Websites" },
  { key: "renewals", label: "Renewal Center" },
  { key: "alerts", label: "Alerts" },
  { key: "credentials", label: "Credentials" },
  { key: "activity_log", label: "Activity Log" },
  { key: "heatmap", label: "Heatmap" },
];

// Filter-tab wording. Not every role name pluralises by adding an "s" —
// "Customs" and "SEOs" both read as nonsense.
const ROLE_TAB_LABEL: Record<string, string> = {
  owner: "Owners",
  manager: "Managers",
  developer: "Developers",
  viewer: "Viewers",
  custom: "Custom access",
  editor: "Editors",
  seo: "SEO",
  seo_executive: "SEO Executives",
};

const MONTH_YEAR = new Intl.DateTimeFormat("en-GB", { month: "short", year: "numeric" });

function joinedLabel(d: string): string {
  if (!d) return "—";
  try { return `Joined ${MONTH_YEAR.format(new Date(d))}`; } catch { return "—"; }
}

function displayName(m: TeamMember): string {
  return `${m.user.first_name} ${m.user.last_name}`.trim() || m.user.email;
}

function initials(m: TeamMember): string {
  const f = (m.user.first_name ?? "").trim();
  const l = (m.user.last_name ?? "").trim();
  const pair = `${f.charAt(0)}${l.charAt(0)}`.trim();
  return (pair || m.user.email.charAt(0)).toUpperCase();
}

interface PasswordResetReq {
  id: string;
  user_email: string;
  user_name: string;
  status: string;
  created_at: string;
}

interface Props {
  teamId: string;
  teamName: string;
  plan: string;
  myRole: string;
  myMembershipId: string;
  initialMembers: TeamMember[];
  initialResetRequests: PasswordResetReq[];
  initialGroups: SubTeam[];
}

export function TeamManagementClient({
  teamId,
  teamName,
  plan,
  myRole,
  myMembershipId,
  initialMembers,
  initialResetRequests,
  initialGroups,
}: Props) {
  const router = useRouter();
  const [, startTransition] = useTransition();

  // Add member form state
  const [showAddForm, setShowAddForm] = useState(false);
  const [addForm, setAddForm] = useState({ name: "", email: "", password: "", role: "developer" as Role });
  // Held apart from addForm because the POST body is built explicitly: sending
  // sub_team at all is owner-only, so a manager must not send an empty one.
  const [addGroup, setAddGroup] = useState("");
  const [addLoading, setAddLoading] = useState(false);
  const [addError, setAddError] = useState("");
  const [addResult, setAddResult] = useState<{ msg: string; link?: string; emailSent: boolean } | null>(null);
  const [copied, setCopied] = useState(false);

  // List controls
  const [query, setQuery] = useState("");
  const [roleFilter, setRoleFilter] = useState("all");
  const [accessOpen, setAccessOpen] = useState<string | null>(null);
  const [handoverFor, setHandoverFor] = useState<TeamMember | null>(null);

  // Password reset state
  const [resetRequests, setResetRequests] = useState<PasswordResetReq[]>(initialResetRequests);
  const [processingReset, setProcessingReset] = useState<string | null>(null);

  const myLevel = ROLE_LEVELS[myRole as Role] ?? 0;
  const canManage = myLevel >= ROLE_LEVELS["manager"];
  // Groups and credential grants stay owner-only: a manager already reads every
  // credential in the team, so what this gate withholds is the power to hand
  // that reach to other people. Cover for an absent owner is a *second owner* —
  // the role is assignable below — rather than every manager holding it.
  const canManageGroups = myLevel >= ROLE_LEVELS["owner"];

  function refresh() {
    startTransition(() => router.refresh());
  }

  async function handleAddMember(e: React.FormEvent) {
    e.preventDefault();
    setAddLoading(true);
    setAddError("");
    setAddResult(null);
    setCopied(false);
    try {
      // sub_team is included only when the owner actually chose a group. The
      // backend refuses the key outright from a non-owner, so sending an empty
      // string would break a manager's own create-user call.
      const body: Record<string, unknown> = { ...addForm };
      if (canManageGroups && addGroup) body.sub_team = addGroup;
      const res = await fetch(`/api/teams/${teamId}/users`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) {
        setAddError(data?.detail ?? `Error ${res.status}`);
        return;
      }
      setAddResult({
        msg: data?.already_active
          ? `${addForm.name || addForm.email} was added — they already have an account and can log in with their existing password. ${
              data?.email_sent
                ? "We've emailed them a notification that includes a password-reset link in case they've forgotten it."
                : "The notification email could not be sent (check SMTP) — if they've forgotten their password, ask them to use “Forgot password” on the login page."
            }`
          : `${addForm.name || addForm.email} has been added to the team.`,
        link: data?.set_password_url,
        emailSent: Boolean(data?.email_sent),
      });
      setAddForm({ name: "", email: "", password: "", role: "developer" });
      setAddGroup("");
      setShowAddForm(false);
      refresh();
    } finally {
      setAddLoading(false);
    }
  }

  async function copyLink(link: string) {
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard unavailable — the link is visible for manual copy */
    }
  }

  async function handleRoleChange(memberId: string, newRole: Role, featureAccess?: string[]) {
    // Promotion to owner is confirmed, the way removal and disabling 2FA are.
    // It is the one role change that hands over the whole vault — group access,
    // credential grants, and the ability to name further owners — and it is a
    // click away in a radio list of otherwise ordinary roles. Skipped when
    // featureAccess is passed, since that path is a chip toggle re-sending the
    // role the member already holds.
    if (newRole === "owner" && featureAccess === undefined) {
      const member = initialMembers.find((m) => m.id === memberId);
      const who = member ? displayName(member) : "this member";
      if (
        !confirm(
          `Make ${who} an owner?

Owners see and manage everything in the team, including credential groups and who may access which credentials. They can also make further owners.

You can demote them again later.`
        )
      )
        return;
    }
    const body: Record<string, unknown> = { role: newRole };
    // Omit feature_access on a plain role change so the backend applies that
    // role's default preset; send it only when toggling a specific chip.
    if (featureAccess !== undefined) body.feature_access = featureAccess;
    await fetch(`/api/teams/${teamId}/members/${memberId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    refresh();
  }

  async function handleGroupChange(member: TeamMember, groupId: string) {
    // `role` is required on every PATCH to this endpoint, so it is resent
    // unchanged. An empty groupId clears the member's group.
    await fetch(`/api/teams/${teamId}/members/${member.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role: member.role, sub_team: groupId || null }),
    });
    refresh();
  }

  async function handleToggleFeature(member: TeamMember, key: string) {
    // Toggle against the member's effective set, keeping their current role.
    const current = new Set(member.effective_features ?? member.feature_access ?? []);
    if (current.has(key)) current.delete(key);
    else current.add(key);
    await handleRoleChange(member.id, member.role as Role, Array.from(current));
  }

  async function handleRemoveMember(memberId: string) {
    if (!confirm("Remove this member from the team?\n\nIf this is their only team, their account is deactivated (they can no longer log in). Re-adding them later reactivates it.")) return;
    const permanent = confirm(
      "Also permanently DELETE their account?\n\nOK = delete the account forever (cannot be undone).\nCancel = just remove from the team (account kept, deactivated)."
    );
    await fetch(`/api/teams/${teamId}/members/${memberId}${permanent ? "?permanent=true" : ""}`, { method: "DELETE" });
    refresh();
  }

  async function handleDisable2fa(userId: string, memberName: string) {
    if (!confirm(`Disable 2FA for ${memberName}? They will need to re-enrol on next login.`)) return;
    const res = await fetch("/api/auth/2fa/disable", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId }),
    });
    if (res.ok) refresh();
  }

  async function handleResetAction(id: string, action: "approve" | "reject") {
    setProcessingReset(id);
    try {
      await fetch(`/api/password-reset/${id}/${action}`, { method: "POST" });
      setResetRequests((prev) => prev.filter((r) => r.id !== id));
    } finally {
      setProcessingReset(null);
    }
  }

  // "Owner" is offered like any other role, which the level check alone already
  // restricts to owners (owner is the top level, so nobody else can reach it).
  // It used to be excluded outright, which made ownership a thing only Django
  // admin could hand over — the whole reason group administration kept being
  // asked to widen instead.
  const assignableRoles = ROLES.filter((r) => ROLE_LEVELS[r] <= myLevel);

  // Only offer filters for roles somebody actually holds — a tab that always
  // returns nothing is noise.
  const roleTabs = useMemo(() => {
    const counts = new Map<string, number>();
    for (const m of initialMembers) counts.set(m.role, (counts.get(m.role) ?? 0) + 1);
    return [
      { key: "all", label: "All", count: initialMembers.length },
      ...ROLES.filter((r) => counts.has(r)).map((r) => ({
        key: r as string,
        label: ROLE_TAB_LABEL[r] ?? r,
        count: counts.get(r) ?? 0,
      })),
    ];
  }, [initialMembers]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return initialMembers.filter((m) => {
      if (roleFilter !== "all" && m.role !== roleFilter) return false;
      if (!q) return true;
      return displayName(m).toLowerCase().includes(q) || m.user.email.toLowerCase().includes(q);
    });
  }, [initialMembers, query, roleFilter]);

  return (
    <div className="space-y-5">
      {/* Page header + primary action */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">{teamName}</h1>
          <p className="text-muted-foreground mt-1">
            Manage who has access to this workspace · {plan} plan
          </p>
        </div>
        {canManage && !showAddForm && (
          <Button onClick={() => setShowAddForm(true)} className="rounded-full">
            <UserPlus className="h-4 w-4 mr-1.5" />
            Invite members
          </Button>
        )}
      </div>

      {/* Invite form */}
      {canManage && showAddForm && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <UserPlus className="h-4 w-4" />
              Invite a member
            </CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleAddMember} className="space-y-4">
              <div className="grid sm:grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <Label htmlFor="add-name">Full name</Label>
                  <Input
                    id="add-name"
                    placeholder="Jane Smith"
                    required
                    value={addForm.name}
                    onChange={(e) => setAddForm((f) => ({ ...f, name: e.target.value }))}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="add-email">Email</Label>
                  <Input
                    id="add-email"
                    type="email"
                    placeholder="jane@example.com"
                    required
                    value={addForm.email}
                    onChange={(e) => setAddForm((f) => ({ ...f, email: e.target.value }))}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="add-password">Password (optional)</Label>
                  <PasswordInput
                    id="add-password"
                    placeholder="Leave blank to email a set-password link"
                    minLength={8}
                    value={addForm.password}
                    onChange={(e) => setAddForm((f) => ({ ...f, password: e.target.value }))}
                  />
                  <p className="text-xs text-muted-foreground">
                    Leave blank and the new member gets an email to set their own password.
                    If you set one, they&apos;ll be required to change it on first login.
                  </p>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="add-role">Role</Label>
                  <Select value={addForm.role} onValueChange={(v) => setAddForm((f) => ({ ...f, role: v as Role }))}>
                    <SelectTrigger id="add-role">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {assignableRoles.map((r) => (
                        <SelectItem key={r} value={r}>{roleLabel(r)}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                {canManageGroups && initialGroups.length > 0 && (
                  <div className="space-y-1.5">
                    <Label htmlFor="add-group">Group</Label>
                    <Select value={addGroup || "none"} onValueChange={(v) => setAddGroup(v === "none" ? "" : v)}>
                      <SelectTrigger id="add-group">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="none">No group</SelectItem>
                        {initialGroups.map((g) => (
                          <SelectItem key={g.id} value={g.id}>{g.name}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <p className="text-xs text-muted-foreground">
                      Controls which credentials this person can see.
                    </p>
                  </div>
                )}
              </div>
              {addError && <p className="text-sm text-red-600">{addError}</p>}
              <div className="flex gap-2">
                <Button type="submit" disabled={addLoading}>
                  {addLoading ? "Creating…" : "Create account"}
                </Button>
                <Button type="button" variant="outline" onClick={() => { setShowAddForm(false); setAddError(""); }}>
                  Cancel
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>
      )}

      {addResult && !showAddForm && (
        <Card>
          <CardContent className="space-y-3 pt-6">
            <p className="text-sm rounded-md px-3 py-2 border text-emerald-700 bg-emerald-50 border-emerald-200 dark:text-emerald-300 dark:bg-emerald-500/10 dark:border-emerald-500/25">
              {addResult.msg}
            </p>
            {addResult.link && (
              <div className="rounded-md border px-3 py-2 space-y-1.5 border-amber-200 bg-amber-50 dark:border-amber-500/25 dark:bg-amber-500/10">
                <p className="text-sm text-amber-800 dark:text-amber-300">
                  {addResult.emailSent
                    ? "A set-password email was sent. You can also share this link with them directly:"
                    : "The set-password email could not be sent (check SMTP). Share this link with the new member so they can log in:"}
                </p>
                <div className="flex items-center gap-2">
                  <code className="flex-1 min-w-0 truncate text-xs bg-background border rounded px-2 py-1">
                    {addResult.link}
                  </code>
                  <Button type="button" size="sm" variant="outline" onClick={() => copyLink(addResult.link!)}>
                    {copied ? "Copied" : "Copy"}
                  </Button>
                </div>
                <p className="text-xs text-amber-700 dark:text-amber-400">Link valid for 7 days.</p>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Credential-access groups. Read-only for non-owners; the panel itself
          hides every write control. */}
      <TeamGroupsPanel teamId={teamId} canManageGroups={canManageGroups} initialGroups={initialGroups} />

      {/* Filter tabs + search */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-1 rounded-full border bg-muted/50 p-1 w-fit max-w-full overflow-x-auto">
          {roleTabs.map((t) => (
            <button
              key={t.key}
              type="button"
              onClick={() => setRoleFilter(t.key)}
              aria-pressed={roleFilter === t.key}
              className={cn(
                "flex shrink-0 items-center gap-1.5 rounded-full px-3.5 py-1.5 text-sm font-medium transition-colors",
                roleFilter === t.key
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              {t.label}
              <span className="text-xs tabular-nums opacity-60">{t.count}</span>
            </button>
          ))}
        </div>

        <div className="relative w-full sm:max-w-xs">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search members..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="pl-9 rounded-full"
          />
        </div>
      </div>

      {/* Member rows */}
      <div className="rounded-xl border bg-card overflow-hidden">
        {filtered.length === 0 ? (
          <div className="py-14 text-center">
            <p className="text-sm font-medium">No members match that filter</p>
            <p className="text-sm text-muted-foreground mt-1">
              Try a different search term or role.
            </p>
          </div>
        ) : (
          filtered.map((member, i) => {
            const isSelf = member.id === myMembershipId;
            const memberLevel = ROLE_LEVELS[member.role as Role] ?? 0;
            // The primary owner — not every owner — is the row nothing may be
            // done to: `Team.owner` is what holds the team together, while a
            // co-owner is a membership an owner named and an owner can unname.
            const canModify =
              canManage && memberLevel <= myLevel && !member.is_primary_owner && !isSelf;
            const name = displayName(member);
            const features = member.effective_features ?? member.feature_access ?? [];
            const showAccess = accessOpen === member.id;

            return (
              <div key={member.id} className={cn(i > 0 && "border-t")}>
                <div className="flex items-center gap-4 p-4 transition-colors hover:bg-muted/40">
                  <div
                    className={cn(
                      "flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-sm font-semibold",
                      ROLE_AVATAR[member.role] ?? ROLE_AVATAR.viewer
                    )}
                  >
                    {initials(member)}
                  </div>

                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5">
                      <span className="truncate font-medium text-sm">{name}</span>
                      {isSelf && <span className="text-xs text-muted-foreground shrink-0">(you)</span>}
                    </div>
                    <div className="truncate text-xs text-muted-foreground">{member.user.email}</div>
                  </div>

                  <span className="hidden md:block shrink-0 text-xs text-muted-foreground">
                    {joinedLabel(member.created_at)}
                  </span>

                  {/* Deliberately not a pill: the role badge beside it already is
                      one, and ROLE_BADGE uses these same two colours, so a second
                      pill would read as a second role. Amber rather than grey for
                      the off state — an account without 2FA is a gap worth seeing. */}
                  <span
                    className={cn(
                      "hidden sm:flex shrink-0 items-center gap-1 text-xs font-medium",
                      member.totp_enabled
                        ? "text-emerald-600 dark:text-emerald-400"
                        : "text-amber-600 dark:text-amber-400"
                    )}
                  >
                    {member.totp_enabled ? (
                      <ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />
                    ) : (
                      <ShieldAlert className="h-3.5 w-3.5" aria-hidden="true" />
                    )}
                    {member.totp_enabled ? "2FA on" : "No 2FA"}
                  </span>

                  {/* Group, only once groups exist. Muted and uncoloured so it
                      never competes with the role badge beside it: a group is
                      not a rank. */}
                  {initialGroups.length > 0 && (
                    <span className="hidden lg:block shrink-0 text-xs text-muted-foreground truncate max-w-[9rem]">
                      {member.sub_team_name ?? "No group"}
                    </span>
                  )}

                  <span
                    className={cn(
                      "shrink-0 rounded-full border px-2.5 py-0.5 text-xs font-medium",
                      ROLE_BADGE[member.role] ?? ROLE_BADGE.viewer
                    )}
                  >
                    {member.is_primary_owner ? "Primary owner" : roleLabel(member.role)}
                  </span>

                  {canManage ? (
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8 shrink-0 text-muted-foreground hover:text-foreground"
                          aria-label={`Actions for ${name}`}
                        >
                          <MoreHorizontal className="h-4 w-4" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end" className="w-52">
                        <DropdownMenuLabel className="truncate">{name}</DropdownMenuLabel>
                        <DropdownMenuSeparator />

                        <DropdownMenuItem asChild>
                          <Link href={`/logs?user_id=${member.user.id}`}>
                            <ScrollText className="h-4 w-4 mr-2" />
                            View activity
                          </Link>
                        </DropdownMenuItem>

                        {canModify && (
                          <DropdownMenuSub>
                            <DropdownMenuSubTrigger>
                              <KeyRound className="h-4 w-4 mr-2" />
                              Change role
                            </DropdownMenuSubTrigger>
                            <DropdownMenuSubContent>
                              <DropdownMenuRadioGroup
                                value={member.role}
                                onValueChange={(v) => handleRoleChange(member.id, v as Role)}
                              >
                                {assignableRoles.map((r) => (
                                  <DropdownMenuRadioItem key={r} value={r}>
                                    {roleLabel(r)}
                                  </DropdownMenuRadioItem>
                                ))}
                              </DropdownMenuRadioGroup>
                            </DropdownMenuSubContent>
                          </DropdownMenuSub>
                        )}

                        {canManageGroups && member.role !== "owner" && initialGroups.length > 0 && (
                          <DropdownMenuSub>
                            <DropdownMenuSubTrigger>
                              <Users className="h-4 w-4 mr-2" />
                              Change group
                            </DropdownMenuSubTrigger>
                            <DropdownMenuSubContent>
                              <DropdownMenuRadioGroup
                                value={member.sub_team ?? "none"}
                                onValueChange={(v) => handleGroupChange(member, v === "none" ? "" : v)}
                              >
                                <DropdownMenuRadioItem value="none">No group</DropdownMenuRadioItem>
                                {initialGroups.map((g) => (
                                  <DropdownMenuRadioItem key={g.id} value={g.id}>
                                    {g.name}
                                  </DropdownMenuRadioItem>
                                ))}
                              </DropdownMenuRadioGroup>
                            </DropdownMenuSubContent>
                          </DropdownMenuSub>
                        )}

                        {canModify && (
                          <DropdownMenuItem onSelect={() => setAccessOpen(showAccess ? null : member.id)}>
                            <SlidersHorizontal className="h-4 w-4 mr-2" />
                            {showAccess ? "Hide access" : "Manage access"}
                          </DropdownMenuItem>
                        )}

                        {canModify && member.totp_enabled && (
                          <DropdownMenuItem
                            className="text-amber-600 focus:text-amber-600"
                            onSelect={() => handleDisable2fa(member.user.id, name)}
                          >
                            <ShieldOff className="h-4 w-4 mr-2" />
                            Disable 2FA
                          </DropdownMenuItem>
                        )}

                        {canModify && (
                          <DropdownMenuItem onSelect={() => setHandoverFor(member)}>
                            <ArrowRightLeft className="h-4 w-4 mr-2" />
                            Hand over credentials
                          </DropdownMenuItem>
                        )}

                        {canModify && (
                          <>
                            <DropdownMenuSeparator />
                            <DropdownMenuItem
                              className="text-red-600 focus:text-red-600"
                              onSelect={() => handleRemoveMember(member.id)}
                            >
                              <Trash2 className="h-4 w-4 mr-2" />
                              Remove from team
                            </DropdownMenuItem>
                          </>
                        )}
                      </DropdownMenuContent>
                    </DropdownMenu>
                  ) : (
                    <span className="w-8 shrink-0" aria-hidden />
                  )}
                </div>

                {/* Per-member section access — opened from the row menu so the
                    list stays scannable until you need to change something. */}
                {showAccess && canModify && (
                  <div className="border-t bg-muted/30 p-4 md:pl-[4.5rem]">
                    <p className="text-xs text-muted-foreground mb-2">
                      Sections this member can open. Changes save immediately.
                    </p>
                    <div className="flex flex-wrap gap-1.5">
                      {FEATURES.map((f) => {
                        const on = features.includes(f.key);
                        return (
                          <button
                            key={f.key}
                            type="button"
                            onClick={() => handleToggleFeature(member, f.key)}
                            aria-pressed={on}
                            className={cn(
                              "rounded-full border px-2.5 py-1 text-xs transition-colors",
                              on
                                ? "bg-indigo-100 text-indigo-800 border-indigo-200 dark:bg-indigo-500/15 dark:text-indigo-300 dark:border-indigo-500/25"
                                : "bg-background text-muted-foreground border-border hover:text-foreground"
                            )}
                            title={on ? `Remove ${f.label} access` : `Grant ${f.label} access`}
                          >
                            {on ? "✓ " : ""}{f.label}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>

      {/* Password reset requests — a work queue, so it keeps the amber edge and
          spells its actions out rather than hiding them behind bare icons. */}
      {canManage && resetRequests.length > 0 && (
        <section className="space-y-3">
          <div className="flex items-baseline gap-2">
            <h2 className="text-base font-semibold flex items-center gap-2">
              <ShieldAlert className="h-4 w-4 text-amber-500" />
              Password reset requests
            </h2>
            <span className="text-sm text-muted-foreground">
              {resetRequests.length} waiting on you
            </span>
          </div>

          <div className="rounded-xl border border-amber-300/60 dark:border-amber-500/25 bg-amber-50/40 dark:bg-amber-500/[0.04] overflow-hidden">
            {resetRequests.map((req, i) => (
              <div
                key={req.id}
                className={cn(
                  "flex flex-wrap items-center gap-x-4 gap-y-2 p-4",
                  i > 0 && "border-t border-amber-300/50 dark:border-amber-500/20"
                )}
              >
                <div className="min-w-0 flex-1">
                  <div className="truncate font-medium text-sm">{req.user_name}</div>
                  <div className="truncate text-xs text-muted-foreground">{req.user_email}</div>
                </div>
                <span className="shrink-0 text-xs text-muted-foreground">
                  Asked {fmtDate(req.created_at)}
                </span>
                <div className="flex shrink-0 items-center gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-8 bg-background"
                    disabled={processingReset === req.id}
                    onClick={() => handleResetAction(req.id, "reject")}
                  >
                    <X className="h-3.5 w-3.5 mr-1.5" />
                    Reject
                  </Button>
                  <Button
                    size="sm"
                    className="h-8"
                    disabled={processingReset === req.id}
                    title="Sends this member a password reset email"
                    onClick={() => handleResetAction(req.id, "approve")}
                  >
                    <Check className="h-3.5 w-3.5 mr-1.5" />
                    {processingReset === req.id ? "Sending…" : "Send reset link"}
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {handoverFor && (
        <CredentialHandoverDialog
          member={handoverFor}
          members={initialMembers}
          onClose={() => setHandoverFor(null)}
        />
      )}
    </div>
  );
}
