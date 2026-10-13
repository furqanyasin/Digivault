"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Users, Plus, Pencil, Trash2, Check, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useToast } from "@/hooks/use-toast";
import type { SubTeam } from "@/lib/api";


interface Props {
  teamId: string;
  canManageGroups: boolean;
  initialGroups: SubTeam[];
}

/**
 * Credential-access groups ("Web Team", "SEO Team").
 *
 * A group decides which credentials its members can see. It does not touch
 * role or feature access, so a viewer in a fully granted group is still a
 * viewer. Only the team owner can create, rename or delete one, and only the
 * owner can grant a group access to credentials — one at a time on the
 * Credentials page, or a whole folder from the vault's "Manage folders": a
 * group a folder is shared with sees everything filed in it, now or later.
 */
export function TeamGroupsPanel({ teamId, canManageGroups, initialGroups }: Props) {
  const router = useRouter();
  const { toast } = useToast();
  const [, startTransition] = useTransition();

  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDescription, setNewDescription] = useState("");
  const [busy, setBusy] = useState(false);

  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");

  const [pendingDelete, setPendingDelete] = useState<SubTeam | null>(null);

  function refresh() {
    startTransition(() => router.refresh());
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    const name = newName.trim();
    if (!name) return;
    setBusy(true);
    try {
      const res = await fetch(`/api/teams/${teamId}/sub-teams`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, description: newDescription.trim() }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        toast({
          title: "Could not create the group",
          description: data?.detail ?? `Error ${res.status}`,
          variant: "destructive",
        });
        return;
      }
      setNewName("");
      setNewDescription("");
      setCreating(false);
      toast({ title: `Group "${name}" created` });
      refresh();
    } finally {
      setBusy(false);
    }
  }

  async function handleRename(group: SubTeam) {
    const name = renameValue.trim();
    if (!name || name === group.name) {
      setRenamingId(null);
      return;
    }
    setBusy(true);
    try {
      const res = await fetch(`/api/teams/${teamId}/sub-teams/${group.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        toast({
          title: "Could not rename the group",
          description: data?.detail ?? `Error ${res.status}`,
          variant: "destructive",
        });
        return;
      }
      setRenamingId(null);
      refresh();
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete(group: SubTeam) {
    setBusy(true);
    try {
      const res = await fetch(`/api/teams/${teamId}/sub-teams/${group.id}`, {
        method: "DELETE",
      });
      if (!res.ok && res.status !== 204) {
        const data = await res.json().catch(() => ({}));
        toast({
          title: "Could not delete the group",
          description: data?.detail ?? `Error ${res.status}`,
          variant: "destructive",
        });
        return;
      }
      setPendingDelete(null);
      toast({ title: `Group "${group.name}" deleted` });
      refresh();
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="mb-6">
      <CardHeader className="flex flex-row items-center justify-between gap-4">
        <div className="space-y-1">
          <CardTitle className="flex items-center gap-2 text-base">
            <Users className="h-4 w-4 text-muted-foreground" />
            Groups
          </CardTitle>
          <p className="text-sm text-muted-foreground">
            Groups decide which credentials a person can see. Share a vault
            folder with a group (Credentials → Manage folders), or grant single
            credentials. Roles are unaffected.
          </p>
        </div>
        {canManageGroups && !creating && (
          <Button
            size="sm"
            variant="outline"
            className="rounded-full shrink-0"
            onClick={() => setCreating(true)}
          >
            <Plus className="h-4 w-4 mr-1" />
            New group
          </Button>
        )}
      </CardHeader>

      <CardContent className="space-y-4">
        {canManageGroups && creating && (
          <form
            onSubmit={handleCreate}
            className="rounded-lg border bg-muted/30 p-4 space-y-3"
          >
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="group-name">Name</Label>
                <Input
                  id="group-name"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder="Web Team"
                  maxLength={80}
                  required
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="group-description">Description (optional)</Label>
                <Input
                  id="group-description"
                  value={newDescription}
                  onChange={(e) => setNewDescription(e.target.value)}
                  placeholder="Builds and maintains client sites"
                  maxLength={200}
                />
              </div>
            </div>
            <div className="flex gap-2">
              <Button type="submit" size="sm" disabled={busy}>
                {busy ? "Creating..." : "Create group"}
              </Button>
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => {
                  setCreating(false);
                  setNewName("");
                  setNewDescription("");
                }}
              >
                Cancel
              </Button>
            </div>
          </form>
        )}

        {initialGroups.length === 0 ? (
          <p className="text-sm text-muted-foreground py-2">
            {canManageGroups
              ? "No groups yet. Create one, put people in it, then grant it credential access from the Credentials page."
              : "No groups have been set up yet."}
          </p>
        ) : (
          <ul className="divide-y rounded-lg border">
            {initialGroups.map((group) => (
              <li
                key={group.id}
                className="flex items-center justify-between gap-3 px-4 py-3"
              >
                {renamingId === group.id ? (
                  <div className="flex items-center gap-2 flex-1">
                    <Input
                      value={renameValue}
                      onChange={(e) => setRenameValue(e.target.value)}
                      maxLength={80}
                      autoFocus
                      className="h-8 max-w-xs"
                    />
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={busy}
                      onClick={() => handleRename(group)}
                      aria-label="Save name"
                    >
                      <Check className="h-4 w-4" />
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => setRenamingId(null)}
                      aria-label="Cancel rename"
                    >
                      <X className="h-4 w-4" />
                    </Button>
                  </div>
                ) : (
                  <div className="min-w-0">
                    <p className="font-medium truncate">{group.name}</p>
                    <p className="text-sm text-muted-foreground truncate">
                      {group.member_count ?? 0}{" "}
                      {(group.member_count ?? 0) === 1 ? "member" : "members"}
                      {group.description ? ` · ${group.description}` : ""}
                    </p>
                  </div>
                )}

                {canManageGroups && renamingId !== group.id && (
                  <div className="flex items-center gap-1 shrink-0">
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => {
                        setRenamingId(group.id);
                        setRenameValue(group.name);
                      }}
                      aria-label={`Rename ${group.name}`}
                    >
                      <Pencil className="h-4 w-4" />
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="text-destructive hover:text-destructive"
                      onClick={() => setPendingDelete(group)}
                      aria-label={`Delete ${group.name}`}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </CardContent>

      <Dialog
        open={pendingDelete !== null}
        onOpenChange={(open) => !open && setPendingDelete(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete “{pendingDelete?.name}”?</DialogTitle>
            <DialogDescription>
              {pendingDelete?.member_count ?? 0}{" "}
              {(pendingDelete?.member_count ?? 0) === 1 ? "member" : "members"}{" "}
              will be left with no group and will lose any credential access
              this group granted. They keep their own credentials and anything
              shared with them individually. This cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setPendingDelete(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={busy}
              onClick={() => pendingDelete && handleDelete(pendingDelete)}
            >
              {busy ? "Deleting..." : "Delete group"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
