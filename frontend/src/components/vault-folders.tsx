"use client";

import { useEffect, useState } from "react";
import { Folder, FolderPlus, Pencil, Trash2, Check, X, Share2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { useToast } from "@/hooks/use-toast";
import type { SubTeam, VaultFolder } from "@/lib/api";
import { SHAREABLE_ROLES, roleLabel } from "@/lib/roles";

const NO_FOLDER = "__none__";
const NEW_FOLDER = "__new__";

function errorMessage(data: unknown, fallback: string): string {
  const d = data as { errors?: { message?: string }[]; detail?: string } | null;
  return d?.errors?.[0]?.message ?? d?.detail ?? fallback;
}

/** Create a folder; returns it, or null after telling the user why not. */
export async function createFolder(
  name: string,
  toast: ReturnType<typeof useToast>["toast"],
): Promise<VaultFolder | null> {
  const res = await fetch("/api/credentials/folders", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    toast({ variant: "destructive", title: "Could not create the folder", description: errorMessage(data, `Error ${res.status}`) });
    return null;
  }
  return data as VaultFolder;
}

/**
 * The folder a credential is filed in. Managers can make a new folder from the
 * same dropdown — filing is when you notice the folder you want is missing.
 */
export function FolderPicker({
  value, folders, canCreate, onChange, onCreated,
}: {
  value: string;
  folders: VaultFolder[];
  canCreate: boolean;
  onChange: (folderId: string) => void;
  onCreated: (folder: VaultFolder) => void;
}) {
  const { toast } = useToast();

  async function pick(v: string) {
    if (v !== NEW_FOLDER) { onChange(v === NO_FOLDER ? "" : v); return; }
    const name = window.prompt("New folder name (e.g. SEO, Web, Agency tools)")?.trim();
    if (!name) return;
    const folder = await createFolder(name, toast);
    if (folder) { onCreated(folder); onChange(folder.id); }
  }

  return (
    <Select value={value || NO_FOLDER} onValueChange={pick}>
      <SelectTrigger aria-label="Folder"><SelectValue /></SelectTrigger>
      <SelectContent>
        <SelectItem value={NO_FOLDER}>No folder</SelectItem>
        {folders.map((f) => (
          <SelectItem key={f.id} value={f.id}>{f.name}</SelectItem>
        ))}
        {canCreate && <SelectItem value={NEW_FOLDER}>+ New folder…</SelectItem>}
      </SelectContent>
    </Select>
  );
}

/**
 * Make, rename and delete folders — and, for the owner, share a folder with a
 * group: everything filed in it, now or later, autofill-only unless "view
 * passwords" is on. LastPass's shared folder.
 */
export function FolderManagerDialog({
  folders, groups, canShare, onChanged, onClose,
}: {
  folders: VaultFolder[];
  groups: SubTeam[];
  /** Owner only — group access is the owner's to hand out. */
  canShare: boolean;
  onChanged: () => Promise<void> | void;
  onClose: () => void;
}) {
  const { toast } = useToast();
  const [newName, setNewName] = useState("");
  const [renaming, setRenaming] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [busy, setBusy] = useState(false);

  async function run(work: () => Promise<Response>, ok: string) {
    setBusy(true);
    try {
      const res = await work();
      if (!res.ok && res.status !== 204) {
        const data = await res.json().catch(() => ({}));
        toast({ variant: "destructive", title: "Could not save", description: errorMessage(data, `Error ${res.status}`) });
        return false;
      }
      if (ok) toast({ title: ok });
      await onChanged();
      return true;
    } finally {
      setBusy(false);
    }
  }

  async function add(e: React.FormEvent) {
    e.preventDefault();
    const name = newName.trim();
    if (!name) return;
    setBusy(true);
    const folder = await createFolder(name, toast);
    setBusy(false);
    if (folder) { setNewName(""); await onChanged(); }
  }

  const rename = (f: VaultFolder) => run(
    () => fetch(`/api/credentials/folders/${f.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: renameValue.trim() }),
    }),
    "",
  ).then((done) => { if (done) setRenaming(null); });

  const remove = (f: VaultFolder) => {
    if (!confirm(`Delete the folder "${f.name}"? Its logins are kept and become unfiled; groups it was shared with lose access through it.`)) return;
    void run(() => fetch(`/api/credentials/folders/${f.id}`, { method: "DELETE" }), `Folder "${f.name}" deleted`);
  };

  /** Share or unshare a folder with a group, or flip its reveal flag (a grant
   *  has no PATCH, so a change is a delete plus a create). */
  async function setAccess(f: VaultFolder, group: SubTeam, on: boolean, canView: boolean) {
    const existing = f.groups?.find((g) => g.sub_team === group.id);
    await run(async () => {
      if (existing) {
        const del = await fetch(`/api/sub-teams/${group.id}/credential-grants/${existing.grant_id}`, { method: "DELETE" });
        if (!del.ok && del.status !== 204) return del;
      }
      if (!on) return new Response(null, { status: 204 });
      return fetch(`/api/sub-teams/${group.id}/credential-grants`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scope: "folder", folder: f.id, can_view_password: canView }),
      });
    }, "");
  }

  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent className="sm:max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Folders</DialogTitle>
          <DialogDescription>
            Arrange the vault your way — SEO, Web, Agency tools. A login lives in
            one folder; move it from its edit dialog.
            {canShare && " Share a folder with a group to give its members everything in it."}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={add} className="flex gap-2">
          <Input
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="New folder name"
            maxLength={80}
          />
          <Button type="submit" disabled={busy || !newName.trim()}>
            <FolderPlus className="h-4 w-4" />Add
          </Button>
        </form>

        {folders.length === 0 ? (
          <p className="text-sm text-muted-foreground py-2">No folders yet.</p>
        ) : (
          <ul className="divide-y rounded-lg border">
            {folders.map((f) => (
              <li key={f.id} className="px-3 py-2.5 space-y-2">
                <div className="flex items-center gap-2">
                  <Folder className="h-4 w-4 text-muted-foreground shrink-0" />
                  {renaming === f.id ? (
                    <>
                      <Input
                        autoFocus
                        value={renameValue}
                        onChange={(e) => setRenameValue(e.target.value)}
                        maxLength={80}
                        className="h-8 max-w-xs"
                      />
                      <Button size="sm" variant="ghost" disabled={busy} onClick={() => rename(f)} aria-label="Save name">
                        <Check className="h-4 w-4" />
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => setRenaming(null)} aria-label="Cancel rename">
                        <X className="h-4 w-4" />
                      </Button>
                    </>
                  ) : (
                    <>
                      <span className="font-medium flex-1 truncate">{f.name}</span>
                      <span className="text-xs text-muted-foreground shrink-0">
                        {f.credential_count} login{f.credential_count !== 1 ? "s" : ""}
                      </span>
                      <Button
                        size="sm" variant="ghost" aria-label={`Rename ${f.name}`}
                        onClick={() => { setRenaming(f.id); setRenameValue(f.name); }}
                      >
                        <Pencil className="h-4 w-4" />
                      </Button>
                      <Button
                        size="sm" variant="ghost" className="text-destructive hover:text-destructive"
                        aria-label={`Delete ${f.name}`} disabled={busy} onClick={() => remove(f)}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </>
                  )}
                </div>

                {canShare && groups.length > 0 && (
                  <div className="pl-6 flex flex-wrap gap-x-4 gap-y-1.5">
                    {groups.map((g) => {
                      const grant = f.groups?.find((x) => x.sub_team === g.id);
                      return (
                        <div key={g.id} className="flex items-center gap-2 text-xs">
                          <label className="flex items-center gap-1.5 cursor-pointer">
                            <input
                              type="checkbox"
                              className="h-3.5 w-3.5 accent-primary"
                              checked={!!grant}
                              disabled={busy}
                              onChange={(e) => setAccess(f, g, e.target.checked, false)}
                            />
                            {g.name}
                          </label>
                          {grant && (
                            <label
                              className="flex items-center gap-1 text-muted-foreground cursor-pointer"
                              title="Off: they can autofill these logins but never see the passwords"
                            >
                              <input
                                type="checkbox"
                                className="h-3 w-3 accent-primary"
                                checked={grant.can_view_password}
                                disabled={busy}
                                onChange={(e) => setAccess(f, g, true, e.target.checked)}
                              />
                              view passwords
                            </label>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </DialogContent>
    </Dialog>
  );
}

interface Person { id: string; name: string; email: string; role: string }

/**
 * Share a whole folder with people — "give Amar all 51 SEO logins" in one
 * step. They get everything filed in it, including what is filed later, and
 * see the passwords only if "See passwords" is ticked (off by default). To
 * share just some of a folder's logins, use Select on the vault instead.
 */
export function ShareFolderDialog({
  folder, teamId, onChanged, onClose,
}: {
  folder: VaultFolder;
  teamId: string | null;
  onChanged: () => Promise<void> | void;
  onClose: () => void;
}) {
  const { toast } = useToast();
  const [people, setPeople] = useState<Person[] | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [canView, setCanView] = useState(false);
  const [busy, setBusy] = useState(false);
  const members = folder.members ?? [];
  const memberIds = new Set(members.map((m) => m.user_id));

  useEffect(() => {
    if (!teamId) return;
    let active = true;
    (async () => {
      const res = await fetch(`/api/teams/${teamId}/members`);
      if (!active) return;
      const data = res.ok ? await res.json().catch(() => []) : [];
      const list = Array.isArray(data) ? data : data?.data ?? [];
      setPeople(
        list
          .filter((m: { role: string }) => SHAREABLE_ROLES.has(m.role))
          .map((m: { role: string; user: { id: string; email: string; first_name?: string; last_name?: string } }) => ({
            id: m.user.id,
            email: m.user.email,
            name: `${m.user.first_name ?? ""} ${m.user.last_name ?? ""}`.trim() || m.user.email,
            role: m.role,
          })),
      );
    })();
    return () => { active = false; };
  }, [teamId]);

  function toggle(id: string) {
    setPicked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  async function share() {
    setBusy(true);
    try {
      const res = await fetch(`/api/credentials/folders/${folder.id}/members`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_ids: [...picked], can_view_password: canView }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        toast({ variant: "destructive", title: "Could not share the folder", description: errorMessage(data, `Error ${res.status}`) });
        return;
      }
      const n = picked.size;
      toast({ title: `"${folder.name}" shared with ${n} ${n === 1 ? "person" : "people"}` });
      setPicked(new Set());
      await onChanged();
    } finally {
      setBusy(false);
    }
  }

  async function remove(userId: string, name: string) {
    setBusy(true);
    try {
      const res = await fetch(`/api/credentials/folders/${folder.id}/members/${userId}`, { method: "DELETE" });
      if (!res.ok && res.status !== 204) {
        toast({ variant: "destructive", title: "Could not remove access" });
        return;
      }
      toast({ title: `${name} no longer has the "${folder.name}" folder` });
      await onChanged();
    } finally {
      setBusy(false);
    }
  }

  const available = (people ?? []).filter((p) => !memberIds.has(p.id));
  const count = folder.credential_count;

  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent className="sm:max-w-lg max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Share2 className="h-4 w-4" />Share &ldquo;{folder.name}&rdquo;
          </DialogTitle>
          <DialogDescription>
            Everyone you add gets all {count} login{count !== 1 ? "s" : ""} in
            this folder, and any added to it later. To share only some, close
            this and use Select.
          </DialogDescription>
        </DialogHeader>

        {members.length > 0 && (
          <div className="space-y-1.5">
            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Has access</p>
            <ul className="space-y-1">
              {members.map((m) => (
                <li key={m.user_id} className="flex items-center gap-2 rounded-md border px-3 py-1.5">
                  <span className="text-sm flex-1 truncate">{m.name}</span>
                  <span className="text-[11px] text-muted-foreground shrink-0">
                    {m.can_view_password ? "sees passwords" : "autofill only"}
                  </span>
                  <Button
                    size="sm" variant="ghost" className="h-7 w-7 p-0 text-muted-foreground hover:text-destructive"
                    disabled={busy} onClick={() => remove(m.user_id, m.name)} aria-label={`Remove ${m.name}`}
                  >
                    <X className="h-3.5 w-3.5" />
                  </Button>
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="space-y-1.5">
          <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Add people</p>
          {people === null ? (
            <p className="text-sm text-muted-foreground">Loading…</p>
          ) : available.length === 0 ? (
            <p className="text-sm text-muted-foreground">Everyone who can be added already has this folder.</p>
          ) : (
            <ul className="max-h-60 overflow-y-auto space-y-1 pr-1">
              {available.map((p) => (
                <li key={p.id}>
                  <label className="flex items-center gap-2.5 rounded-md border px-3 py-2 cursor-pointer hover:bg-muted/50">
                    <input
                      type="checkbox"
                      className="h-4 w-4 accent-primary"
                      checked={picked.has(p.id)}
                      onChange={() => toggle(p.id)}
                    />
                    <span className="text-sm flex-1 truncate">{p.name}</span>
                    <span className="text-[11px] text-muted-foreground">{roleLabel(p.role)}</span>
                  </label>
                </li>
              ))}
            </ul>
          )}
          <label className="flex items-start gap-2.5 pt-1 cursor-pointer">
            <input
              type="checkbox"
              className="mt-0.5 h-4 w-4 accent-primary"
              checked={canView}
              onChange={(e) => setCanView(e.target.checked)}
            />
            <span className="text-xs">
              See passwords
              <span className="block text-muted-foreground mt-0.5">
                Off: they autofill these logins with the extension but never see
                the passwords in the dashboard.
              </span>
            </span>
          </label>
          <Button className="w-full" disabled={busy || picked.size === 0} onClick={share}>
            {busy
              ? "Sharing…"
              : picked.size === 0
                ? "Pick people to share with"
                : `Share with ${picked.size} ${picked.size === 1 ? "person" : "people"}`}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
