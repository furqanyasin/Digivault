"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { UserPlus, Trash2, Check, ShieldAlert, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { fmtDate } from "@/lib/utils";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { TeamMember } from "@/lib/api";

const ROLES = ["viewer", "developer", "manager", "owner"] as const;
type Role = typeof ROLES[number];

const ROLE_LEVELS: Record<Role, number> = {
  viewer: 1, developer: 2, manager: 3, owner: 4,
};

const ROLE_BADGE: Record<string, string> = {
  owner: "bg-amber-100 text-amber-800 border border-amber-200",
  manager: "bg-blue-100 text-blue-800 border border-blue-200",
  developer: "bg-emerald-100 text-emerald-800 border border-emerald-200",
  viewer: "bg-gray-100 text-gray-700 border border-gray-200",
};

interface PasswordResetReq {
  id: string;
  user_email: string;
  user_name: string;
  status: string;
  created_at: string;
}

interface Props {
  teamId: string;
  myRole: string;
  myMembershipId: string;
  initialMembers: TeamMember[];
  initialResetRequests: PasswordResetReq[];
}

export function TeamManagementClient({
  teamId,
  myRole,
  myMembershipId,
  initialMembers,
  initialResetRequests,
}: Props) {
  const router = useRouter();
  const [, startTransition] = useTransition();

  // Add member form state
  const [showAddForm, setShowAddForm] = useState(false);
  const [addForm, setAddForm] = useState({ name: "", email: "", password: "", role: "developer" as Role });
  const [addLoading, setAddLoading] = useState(false);
  const [addError, setAddError] = useState("");
  const [addSuccess, setAddSuccess] = useState("");

  // Password reset state
  const [resetRequests, setResetRequests] = useState<PasswordResetReq[]>(initialResetRequests);
  const [processingReset, setProcessingReset] = useState<string | null>(null);

  const myLevel = ROLE_LEVELS[myRole as Role] ?? 0;
  const canManage = myLevel >= ROLE_LEVELS["manager"];

  function refresh() {
    startTransition(() => router.refresh());
  }

  async function handleAddMember(e: React.FormEvent) {
    e.preventDefault();
    setAddLoading(true);
    setAddError("");
    setAddSuccess("");
    try {
      const res = await fetch(`/api/teams/${teamId}/users`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(addForm),
      });
      const data = await res.json();
      if (!res.ok) {
        setAddError(data?.detail ?? `Error ${res.status}`);
        return;
      }
      setAddSuccess(`${addForm.name || addForm.email} has been added to the team.`);
      setAddForm({ name: "", email: "", password: "", role: "developer" });
      setShowAddForm(false);
      refresh();
    } finally {
      setAddLoading(false);
    }
  }

  async function handleRoleChange(memberId: string, newRole: Role) {
    await fetch(`/api/teams/${teamId}/members/${memberId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role: newRole }),
    });
    refresh();
  }

  async function handleRemoveMember(memberId: string) {
    if (!confirm("Remove this member from the team?")) return;
    await fetch(`/api/teams/${teamId}/members/${memberId}`, { method: "DELETE" });
    refresh();
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

  const assignableRoles = ROLES.filter((r) => ROLE_LEVELS[r] <= myLevel && r !== "owner");

  return (
    <div className="space-y-6">
      {/* Add Member */}
      {canManage && (
        <Card>
          <CardHeader className="pb-3 flex flex-row items-center justify-between">
            <CardTitle className="text-base flex items-center gap-2">
              <UserPlus className="h-4 w-4" />
              Team members
            </CardTitle>
            {!showAddForm && (
              <Button size="sm" onClick={() => setShowAddForm(true)}>
                <UserPlus className="h-4 w-4 mr-1" /> Add member
              </Button>
            )}
          </CardHeader>
          {showAddForm && (
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
                    <Label htmlFor="add-password">Password</Label>
                    <Input
                      id="add-password"
                      type="password"
                      placeholder="Min. 8 characters"
                      required
                      minLength={8}
                      value={addForm.password}
                      onChange={(e) => setAddForm((f) => ({ ...f, password: e.target.value }))}
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="add-role">Role</Label>
                    <Select value={addForm.role} onValueChange={(v) => setAddForm((f) => ({ ...f, role: v as Role }))}>
                      <SelectTrigger id="add-role">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {assignableRoles.map((r) => (
                          <SelectItem key={r} value={r} className="capitalize">{r}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
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
          )}
          {addSuccess && !showAddForm && (
            <CardContent>
              <p className="text-sm text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-md px-3 py-2">
                {addSuccess}
              </p>
            </CardContent>
          )}
        </Card>
      )}

      {/* Members table */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Members ({initialMembers.length})</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Member</TableHead>
                <TableHead>Role</TableHead>
                <TableHead>Joined</TableHead>
                {canManage && <TableHead className="w-12" />}
              </TableRow>
            </TableHeader>
            <TableBody>
              {initialMembers.map((member) => {
                const isSelf = member.id === myMembershipId;
                const memberLevel = ROLE_LEVELS[member.role as Role] ?? 0;
                const canModify = canManage && memberLevel <= myLevel && member.role !== "owner" && !isSelf;
                return (
                  <TableRow key={member.id}>
                    <TableCell>
                      <div className="font-medium text-sm">
                        {(member.user.first_name || member.user.last_name)
                          ? `${member.user.first_name} ${member.user.last_name}`.trim()
                          : member.user.email}
                        {isSelf && <span className="ml-1 text-muted-foreground text-xs">(you)</span>}
                      </div>
                      <div className="text-xs text-muted-foreground">{member.user.email}</div>
                    </TableCell>
                    <TableCell>
                      {canModify ? (
                        <Select
                          value={member.role}
                          onValueChange={(v) => handleRoleChange(member.id, v as Role)}
                        >
                          <SelectTrigger className="h-7 w-[110px] text-xs px-2">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {assignableRoles.map((r) => (
                              <SelectItem key={r} value={r} className="capitalize text-xs">{r}</SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      ) : (
                        <span className={`inline-block rounded px-2 py-0.5 text-xs font-medium capitalize ${ROLE_BADGE[member.role] ?? ""}`}>
                          {member.role}
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {fmtDate(member.created_at)}
                    </TableCell>
                    {canManage && (
                      <TableCell>
                        {canModify && (
                          <Button
                            size="icon"
                            variant="ghost"
                            className="h-7 w-7 text-red-500 hover:text-red-600"
                            title="Remove member"
                            onClick={() => handleRemoveMember(member.id)}
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        )}
                      </TableCell>
                    )}
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* Password reset requests */}
      {canManage && resetRequests.length > 0 && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <ShieldAlert className="h-4 w-4 text-amber-500" />
              Password reset requests ({resetRequests.length})
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>User</TableHead>
                  <TableHead>Requested</TableHead>
                  <TableHead className="w-28" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {resetRequests.map((req) => (
                  <TableRow key={req.id}>
                    <TableCell>
                      <div className="font-medium text-sm">{req.user_name}</div>
                      <div className="text-xs text-muted-foreground">{req.user_email}</div>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {fmtDate(req.created_at)}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1">
                        <Button
                          size="icon"
                          variant="ghost"
                          className="h-7 w-7 text-emerald-600 hover:text-emerald-700"
                          title="Approve — send reset email"
                          disabled={processingReset === req.id}
                          onClick={() => handleResetAction(req.id, "approve")}
                        >
                          <Check className="h-3.5 w-3.5" />
                        </Button>
                        <Button
                          size="icon"
                          variant="ghost"
                          className="h-7 w-7 text-red-500 hover:text-red-600"
                          title="Reject"
                          disabled={processingReset === req.id}
                          onClick={() => handleResetAction(req.id, "reject")}
                        >
                          <X className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
