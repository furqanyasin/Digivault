"use client";

import { useState, useMemo } from "react";
import Link from "next/link";
import {
  Lock, ExternalLink, Pencil, Trash2, Plus,
  Eye, EyeOff, Copy, Search, X, KeyRound,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { useToast } from "@/hooks/use-toast";
import type { Credential, Website } from "@/lib/api";

// ─── Constants ────────────────────────────────────────────────────────────────

const CREDENTIAL_TYPES = [
  { value: "wordpress",  label: "WordPress Admin" },
  { value: "cpanel",     label: "cPanel / Hosting" },
  { value: "godaddy",    label: "GoDaddy" },
  { value: "namecheap",  label: "Namecheap" },
  { value: "hostinger",  label: "Hostinger" },
  { value: "cloudflare", label: "Cloudflare" },
  { value: "ftp",        label: "FTP / SFTP" },
  { value: "wix",        label: "Wix" },
  { value: "webflow",    label: "Webflow" },
  { value: "shopify",    label: "Shopify" },
  { value: "custom",     label: "Custom" },
];

const TYPE_GRADIENTS: Record<string, string> = {
  wordpress:  "from-blue-500 to-indigo-600",
  cpanel:     "from-orange-500 to-red-500",
  godaddy:    "from-green-500 to-emerald-600",
  cloudflare: "from-amber-400 to-orange-500",
  ftp:        "from-purple-500 to-violet-600",
  shopify:    "from-emerald-500 to-teal-600",
  namecheap:  "from-red-500 to-rose-600",
  hostinger:  "from-violet-500 to-purple-600",
  wix:        "from-slate-600 to-slate-800",
  webflow:    "from-indigo-500 to-blue-600",
  custom:     "from-slate-400 to-slate-600",
};

const TYPE_BADGE: Record<string, string> = {
  wordpress:  "bg-blue-50 text-blue-700 border-blue-200",
  cpanel:     "bg-orange-50 text-orange-700 border-orange-200",
  godaddy:    "bg-green-50 text-green-700 border-green-200",
  cloudflare: "bg-amber-50 text-amber-700 border-amber-200",
  ftp:        "bg-purple-50 text-purple-700 border-purple-200",
  shopify:    "bg-emerald-50 text-emerald-700 border-emerald-200",
  namecheap:  "bg-red-50 text-red-700 border-red-200",
  hostinger:  "bg-violet-50 text-violet-700 border-violet-200",
  wix:        "bg-slate-50 text-slate-700 border-slate-200",
  webflow:    "bg-indigo-50 text-indigo-700 border-indigo-200",
  custom:     "bg-slate-50 text-slate-600 border-slate-200",
};

// ─── Types ────────────────────────────────────────────────────────────────────

interface FlatCred { cred: Credential; site: Website }
interface RevealData { username: string; password: string; notes: string }

function typeLabel(t: string) {
  return CREDENTIAL_TYPES.find((x) => x.value === t)?.label ?? t;
}

function gradient(t: string) {
  return TYPE_GRADIENTS[t] ?? "from-slate-400 to-slate-600";
}

function badge(t: string) {
  return TYPE_BADGE[t] ?? "bg-slate-50 text-slate-600 border-slate-200";
}

// ─── Credential card ──────────────────────────────────────────────────────────

function CredCard({ flat, onView, onDelete }: {
  flat: FlatCred;
  onView: () => void;
  onDelete: () => void;
}) {
  const { cred, site } = flat;
  return (
    <div
      className="group border rounded-xl overflow-hidden bg-card hover:shadow-lg transition-all cursor-pointer select-none"
      onClick={onView}
    >
      {/* Coloured header */}
      <div className={`relative h-[72px] bg-gradient-to-br ${gradient(cred.credential_type)} flex items-center justify-center`}>
        <Lock className="h-8 w-8 text-white/75" />
        {cred.login_url && (
          <div className="absolute inset-0 bg-black/30 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center">
            <a
              href={cred.login_url}
              target="_blank"
              rel="noopener noreferrer"
              onClick={(e) => e.stopPropagation()}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-white/90 hover:bg-white text-slate-800 text-xs font-semibold rounded-full shadow transition-colors"
            >
              <ExternalLink className="h-3 w-3" />
              Launch
            </a>
          </div>
        )}
      </div>

      {/* Body */}
      <div className="px-3 pt-2.5 pb-1">
        <p className="font-semibold text-sm truncate">{cred.label}</p>
        <p className="text-xs text-muted-foreground truncate mt-0.5">{site.name || site.domain}</p>
      </div>

      {/* Footer */}
      <div className="px-3 pb-2.5 flex items-center gap-1.5 mt-1">
        <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded-full border ${badge(cred.credential_type)}`}>
          {typeLabel(cred.credential_type)}
        </span>
        <div className="ml-auto flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); onView(); }}
            className="p-1 rounded hover:bg-muted transition-colors text-muted-foreground hover:text-foreground"
            title="Edit"
          >
            <Pencil className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); onDelete(); }}
            className="p-1 rounded hover:bg-destructive/10 transition-colors text-muted-foreground hover:text-destructive"
            title="Delete"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Detail / edit modal ──────────────────────────────────────────────────────

function CredentialModal({ flat, onClose, onDeleted, onUpdated }: {
  flat: FlatCred;
  onClose: () => void;
  onDeleted: () => void;
  onUpdated: (updated: Credential) => void;
}) {
  const { toast } = useToast();
  const { cred, site } = flat;

  const [revealed, setRevealed] = useState<RevealData | null>(null);
  const [showPw, setShowPw] = useState(false);
  const [revealLoading, setRevealLoading] = useState(false);

  const [editMode, setEditMode] = useState(false);
  const [saveLoading, setSaveLoading] = useState(false);
  const [form, setForm] = useState({
    label: cred.label,
    credential_type: cred.credential_type,
    login_url: cred.login_url ?? "",
    username: "",
    password: "",
    notes: "",
  });

  const [deleteConfirm, setDeleteConfirm] = useState(false);
  const [deleting, setDeleting] = useState(false);

  function upd(k: string, v: string) {
    setForm((f) => ({ ...f, [k]: v }));
  }

  async function handleReveal() {
    if (revealed) { setShowPw((v) => !v); return; }
    setRevealLoading(true);
    try {
      const res = await fetch(`/api/credentials/${cred.id}/reveal`, { method: "POST" });
      if (!res.ok) { toast({ variant: "destructive", title: "Cannot reveal credential" }); return; }
      const data: RevealData = await res.json();
      setRevealed(data);
      setShowPw(true);
      setForm((f) => ({ ...f, username: data.username, password: data.password, notes: data.notes }));
    } catch {
      toast({ variant: "destructive", title: "Network error" });
    } finally {
      setRevealLoading(false);
    }
  }

  async function handleSave() {
    setSaveLoading(true);
    try {
      const body: Record<string, string> = { label: form.label, credential_type: form.credential_type, login_url: form.login_url };
      if (form.username) body.username = form.username;
      if (form.password) body.password = form.password;
      if (form.notes !== undefined) body.notes = form.notes;

      const res = await fetch(`/api/credentials/${cred.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) { toast({ variant: "destructive", title: "Failed to save" }); return; }
      const updated: Credential = await res.json();
      toast({ title: "Credential updated" });
      setEditMode(false);
      onUpdated(updated);
    } catch {
      toast({ variant: "destructive", title: "Network error" });
    } finally {
      setSaveLoading(false);
    }
  }

  async function handleDelete() {
    setDeleting(true);
    try {
      const res = await fetch(`/api/credentials/${cred.id}`, { method: "DELETE" });
      if (!res.ok && res.status !== 204) { toast({ variant: "destructive", title: "Failed to delete" }); return; }
      toast({ title: "Credential deleted" });
      onDeleted();
    } catch {
      toast({ variant: "destructive", title: "Network error" });
    } finally {
      setDeleting(false);
    }
  }

  function copy(text: string, label: string) {
    navigator.clipboard.writeText(text);
    toast({ title: `${label} copied` });
  }

  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent className="sm:max-w-md p-0 overflow-hidden gap-0">
        {/* Coloured header */}
        <div className={`h-24 bg-gradient-to-br ${gradient(cred.credential_type)} flex items-center justify-center relative`}>
          <Lock className="h-10 w-10 text-white/75" />
          {!editMode && (
            <button
              onClick={() => setEditMode(true)}
              className="absolute top-3 right-3 p-1.5 rounded-full bg-white/20 hover:bg-white/30 text-white transition-colors"
              title="Edit"
            >
              <Pencil className="h-3.5 w-3.5" />
            </button>
          )}
        </div>

        <div className="p-5 space-y-4">
          {/* Title + meta */}
          <div>
            {editMode ? (
              <Input
                value={form.label}
                onChange={(e) => upd("label", e.target.value)}
                className="font-semibold text-base mb-2"
              />
            ) : (
              <h2 className="font-bold text-xl leading-tight">{cred.label}</h2>
            )}
            <div className="flex items-center gap-2 mt-1.5">
              {editMode ? (
                <Select value={form.credential_type} onValueChange={(v) => upd("credential_type", v)}>
                  <SelectTrigger className="h-7 text-xs w-44"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {CREDENTIAL_TYPES.map((t) => <SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>)}
                  </SelectContent>
                </Select>
              ) : (
                <span className={`text-xs font-medium px-2 py-0.5 rounded-full border ${badge(cred.credential_type)}`}>
                  {typeLabel(cred.credential_type)}
                </span>
              )}
              <span className="text-xs text-muted-foreground">{site.name || site.domain}</span>
            </div>
          </div>

          {/* Login URL */}
          <div>
            <Label className="text-xs text-muted-foreground uppercase tracking-wide">Login URL</Label>
            {editMode ? (
              <Input
                value={form.login_url}
                onChange={(e) => upd("login_url", e.target.value)}
                placeholder="https://example.com/wp-admin"
                className="mt-1"
              />
            ) : (
              <div className="flex items-center gap-2 mt-1">
                <span className="text-sm font-mono flex-1 truncate text-muted-foreground">
                  {cred.login_url ? cred.login_url.replace(/^https?:\/\//, "") : "—"}
                </span>
                {cred.login_url && (
                  <a href={cred.login_url} target="_blank" rel="noopener noreferrer">
                    <Button size="sm" variant="ghost" className="h-7 w-7 p-0" title="Open">
                      <ExternalLink className="h-3.5 w-3.5" />
                    </Button>
                  </a>
                )}
              </div>
            )}
          </div>

          {/* Credentials section */}
          {!revealed && !editMode ? (
            <div className="border rounded-lg p-3 flex items-center gap-3 bg-muted/30">
              <div className="flex-1">
                <p className="text-xs text-muted-foreground mb-0.5">Username &amp; Password</p>
                <p className="text-sm tracking-widest text-muted-foreground">••••••••</p>
              </div>
              <Button size="sm" variant="outline" onClick={handleReveal} disabled={revealLoading}>
                <Eye className="h-3.5 w-3.5 mr-1.5" />
                {revealLoading ? "…" : "Reveal"}
              </Button>
            </div>
          ) : (
            <div className="space-y-3">
              {/* Username */}
              <div>
                <Label className="text-xs text-muted-foreground uppercase tracking-wide">Username</Label>
                {editMode ? (
                  <Input value={form.username} onChange={(e) => upd("username", e.target.value)} className="mt-1" />
                ) : (
                  <div className="flex items-center gap-2 mt-1">
                    <span className="text-sm font-mono flex-1 truncate">{revealed?.username || "—"}</span>
                    {revealed?.username && (
                      <Button size="sm" variant="ghost" className="h-7 w-7 p-0 shrink-0" onClick={() => copy(revealed!.username, "Username")}>
                        <Copy className="h-3.5 w-3.5" />
                      </Button>
                    )}
                  </div>
                )}
              </div>

              {/* Password */}
              <div>
                <Label className="text-xs text-muted-foreground uppercase tracking-wide">Password</Label>
                {editMode ? (
                  <Input type="password" value={form.password} onChange={(e) => upd("password", e.target.value)} className="mt-1" />
                ) : (
                  <div className="flex items-center gap-2 mt-1">
                    <span className="text-sm font-mono flex-1 truncate">
                      {showPw ? (revealed?.password || "—") : "••••••••"}
                    </span>
                    <Button size="sm" variant="ghost" className="h-7 w-7 p-0 shrink-0" onClick={() => setShowPw((v) => !v)}>
                      {showPw ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
                    </Button>
                    {revealed?.password && (
                      <Button size="sm" variant="ghost" className="h-7 w-7 p-0 shrink-0" onClick={() => copy(revealed!.password, "Password")}>
                        <Copy className="h-3.5 w-3.5" />
                      </Button>
                    )}
                  </div>
                )}
              </div>

              {/* Notes */}
              {(revealed?.notes || editMode) && (
                <div>
                  <Label className="text-xs text-muted-foreground uppercase tracking-wide">Notes</Label>
                  {editMode ? (
                    <Textarea value={form.notes} onChange={(e) => upd("notes", e.target.value)} rows={2} className="mt-1" />
                  ) : revealed?.notes ? (
                    <p className="text-sm text-muted-foreground mt-1">{revealed.notes}</p>
                  ) : null}
                </div>
              )}
            </div>
          )}

          {/* Action row */}
          <div className="flex items-center gap-2 pt-1 border-t">
            {editMode ? (
              <>
                <Button variant="outline" size="sm" onClick={() => setEditMode(false)} disabled={saveLoading}>Cancel</Button>
                <Button size="sm" onClick={handleSave} disabled={saveLoading}>{saveLoading ? "Saving…" : "Save changes"}</Button>
              </>
            ) : !deleteConfirm ? (
              <Button
                variant="ghost"
                size="sm"
                className="text-destructive hover:text-destructive hover:bg-destructive/10 ml-auto"
                onClick={() => setDeleteConfirm(true)}
              >
                <Trash2 className="h-3.5 w-3.5 mr-1.5" />Delete
              </Button>
            ) : (
              <div className="flex items-center gap-2 ml-auto">
                <span className="text-xs text-muted-foreground">Delete permanently?</span>
                <Button variant="outline" size="sm" onClick={() => setDeleteConfirm(false)} disabled={deleting}>Cancel</Button>
                <Button variant="destructive" size="sm" onClick={handleDelete} disabled={deleting}>
                  {deleting ? "…" : "Delete"}
                </Button>
              </div>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

// ─── Quick-delete confirm ─────────────────────────────────────────────────────

function DeleteConfirmModal({ flat, onClose, onDeleted }: {
  flat: FlatCred;
  onClose: () => void;
  onDeleted: () => void;
}) {
  const { toast } = useToast();
  const [deleting, setDeleting] = useState(false);

  async function handleDelete() {
    setDeleting(true);
    try {
      const res = await fetch(`/api/credentials/${flat.cred.id}`, { method: "DELETE" });
      if (!res.ok && res.status !== 204) { toast({ variant: "destructive", title: "Failed to delete" }); return; }
      toast({ title: "Credential deleted" });
      onDeleted();
    } catch {
      toast({ variant: "destructive", title: "Network error" });
    } finally {
      setDeleting(false);
    }
  }

  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent>
        <DialogHeader><DialogTitle>Delete credential?</DialogTitle></DialogHeader>
        <p className="text-sm text-muted-foreground">
          This will permanently delete <strong>{flat.cred.label}</strong> from {flat.site.name || flat.site.domain}.
        </p>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={deleting}>Cancel</Button>
          <Button variant="destructive" onClick={handleDelete} disabled={deleting}>
            {deleting ? "Deleting…" : "Delete"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ─── Add new credential modal ─────────────────────────────────────────────────

function AddItemModal({ websites, onClose, onAdded }: {
  websites: Website[];
  onClose: () => void;
  onAdded: (websiteId: string, cred: Credential) => void;
}) {
  const { toast } = useToast();
  const [loading, setLoading] = useState(false);
  const [form, setForm] = useState({
    website_id: "",
    label: "",
    credential_type: "",
    login_url: "",
    username: "",
    password: "",
    notes: "",
  });

  function upd(k: string, v: string) { setForm((f) => ({ ...f, [k]: v })); }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.website_id) { toast({ variant: "destructive", title: "Select a website" }); return; }
    setLoading(true);
    try {
      const res = await fetch(`/api/websites/${form.website_id}/credentials`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
      if (!res.ok) { toast({ variant: "destructive", title: "Failed to save credential" }); return; }
      const created: Credential = await res.json();
      toast({ title: "Credential saved" });
      onAdded(form.website_id, created);
      onClose();
    } catch {
      toast({ variant: "destructive", title: "Network error" });
    } finally {
      setLoading(false);
    }
  }

  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader><DialogTitle>New credential</DialogTitle></DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-3">
          <div className="space-y-1.5">
            <Label>Website</Label>
            <Select value={form.website_id} onValueChange={(v) => upd("website_id", v)}>
              <SelectTrigger><SelectValue placeholder="Select website" /></SelectTrigger>
              <SelectContent>
                {websites.map((w) => (
                  <SelectItem key={w.id} value={w.id}>{w.name || w.domain}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label>Label</Label>
            <Input placeholder="e.g. WordPress Admin" value={form.label} onChange={(e) => upd("label", e.target.value)} required />
          </div>
          <div className="space-y-1.5">
            <Label>Type</Label>
            <Select value={form.credential_type} onValueChange={(v) => upd("credential_type", v)}>
              <SelectTrigger><SelectValue placeholder="Select type" /></SelectTrigger>
              <SelectContent>
                {CREDENTIAL_TYPES.map((t) => <SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label>Login URL</Label>
            <Input placeholder="https://example.com/wp-admin" value={form.login_url} onChange={(e) => upd("login_url", e.target.value)} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label>Username</Label>
              <Input value={form.username} onChange={(e) => upd("username", e.target.value)} required />
            </div>
            <div className="space-y-1.5">
              <Label>Password</Label>
              <Input type="password" value={form.password} onChange={(e) => upd("password", e.target.value)} required />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label>Notes <span className="text-muted-foreground">(optional)</span></Label>
            <Textarea placeholder="2FA codes, account email…" value={form.notes} onChange={(e) => upd("notes", e.target.value)} rows={2} />
          </div>
          <DialogFooter className="pt-2">
            <Button type="button" variant="outline" onClick={onClose} disabled={loading}>Cancel</Button>
            <Button type="submit" disabled={loading}>{loading ? "Saving…" : "Save"}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

// ─── Empty states ──────────────────────────────────────────────────────────────

function EmptyState({ type, onAdd, onClear }: {
  type: "no-websites" | "no-creds" | "no-results";
  onAdd?: () => void;
  onClear?: () => void;
}) {
  if (type === "no-websites") {
    return (
      <div className="border rounded-xl py-16 flex flex-col items-center gap-3 text-center">
        <KeyRound className="h-10 w-10 text-muted-foreground opacity-40" />
        <p className="font-medium">No websites yet</p>
        <p className="text-sm text-muted-foreground">Add a website first, then store credentials here.</p>
        <Link href="/websites/new">
          <Button variant="outline" size="sm" className="mt-1">Add website</Button>
        </Link>
      </div>
    );
  }
  if (type === "no-creds") {
    return (
      <div className="border rounded-xl py-20 flex flex-col items-center gap-3 text-center">
        <KeyRound className="h-12 w-12 text-muted-foreground opacity-30" />
        <p className="font-semibold text-lg">Your vault is empty</p>
        <p className="text-sm text-muted-foreground max-w-xs">
          Store logins for WordPress, cPanel, GoDaddy, Cloudflare, and more — all in one place.
        </p>
        <Button variant="outline" size="sm" className="mt-1" onClick={onAdd}>
          <Plus className="h-3.5 w-3.5 mr-1" />Add first credential
        </Button>
      </div>
    );
  }
  return (
    <div className="border rounded-xl py-16 flex flex-col items-center gap-3 text-center">
      <Search className="h-10 w-10 text-muted-foreground opacity-40" />
      <p className="font-medium">No results</p>
      <p className="text-sm text-muted-foreground">Try a different search or filter.</p>
      <Button variant="outline" size="sm" className="mt-1" onClick={onClear}>Clear filters</Button>
    </div>
  );
}

// ─── Main vault client ─────────────────────────────────────────────────────────

export function CredentialsVaultClient({
  websites,
  credsByWebsite: initialCredsByWebsite,
}: {
  websites: Website[];
  credsByWebsite: Record<string, Credential[]>;
}) {
  const [credsByWebsite, setCredsByWebsite] = useState(initialCredsByWebsite);
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState("all");
  const [selected, setSelected] = useState<FlatCred | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<FlatCred | null>(null);
  const [addOpen, setAddOpen] = useState(false);

  const allCreds = useMemo<FlatCred[]>(
    () =>
      websites.flatMap((site) =>
        (credsByWebsite[site.id] ?? []).map((cred) => ({ cred, site }))
      ),
    [websites, credsByWebsite]
  );

  const filtered = useMemo(() => {
    let result = allCreds;
    if (search) {
      const q = search.toLowerCase();
      result = result.filter(
        ({ cred, site }) =>
          cred.label.toLowerCase().includes(q) ||
          (site.name ?? "").toLowerCase().includes(q) ||
          site.domain.toLowerCase().includes(q)
      );
    }
    if (typeFilter !== "all") {
      result = result.filter(({ cred }) => cred.credential_type === typeFilter);
    }
    return result;
  }, [allCreds, search, typeFilter]);

  function handleDeleted(flat: FlatCred) {
    setCredsByWebsite((prev) => ({
      ...prev,
      [flat.site.id]: (prev[flat.site.id] ?? []).filter((c) => c.id !== flat.cred.id),
    }));
    setSelected(null);
    setDeleteTarget(null);
  }

  function handleUpdated(flat: FlatCred, updated: Credential) {
    setCredsByWebsite((prev) => ({
      ...prev,
      [flat.site.id]: (prev[flat.site.id] ?? []).map((c) => (c.id === updated.id ? updated : c)),
    }));
    setSelected((prev) => (prev ? { ...prev, cred: updated } : null));
  }

  function handleAdded(websiteId: string, cred: Credential) {
    setCredsByWebsite((prev) => ({
      ...prev,
      [websiteId]: [...(prev[websiteId] ?? []), cred],
    }));
  }

  const totalCreds = allCreds.length;
  const sitesWithCreds = websites.filter((s) => (credsByWebsite[s.id]?.length ?? 0) > 0).length;

  return (
    <div className="p-8 space-y-6">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Vault</h1>
          <p className="text-muted-foreground mt-1">
            {totalCreds > 0
              ? `${totalCreds} credential${totalCreds !== 1 ? "s" : ""} across ${sitesWithCreds} site${sitesWithCreds !== 1 ? "s" : ""}`
              : "Securely stored logins — managed per website"}
          </p>
        </div>
        {websites.length > 0 && (
          <Button onClick={() => setAddOpen(true)}>
            <Plus className="h-4 w-4 mr-1.5" />New item
          </Button>
        )}
      </div>

      {/* Search + filter */}
      {totalCreds > 0 && (
        <div className="flex items-center gap-3">
          <div className="relative flex-1 max-w-sm">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none" />
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search credentials…"
              className="pl-9 pr-8"
            />
            {search && (
              <button
                onClick={() => setSearch("")}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
          <Select value={typeFilter} onValueChange={setTypeFilter}>
            <SelectTrigger className="w-44"><SelectValue placeholder="All types" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All types</SelectItem>
              {CREDENTIAL_TYPES.map((t) => (
                <SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}

      {/* Content */}
      {websites.length === 0 ? (
        <EmptyState type="no-websites" />
      ) : totalCreds === 0 ? (
        <EmptyState type="no-creds" onAdd={() => setAddOpen(true)} />
      ) : filtered.length === 0 ? (
        <EmptyState type="no-results" onClear={() => { setSearch(""); setTypeFilter("all"); }} />
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
          {filtered.map((flat) => (
            <CredCard
              key={flat.cred.id}
              flat={flat}
              onView={() => setSelected(flat)}
              onDelete={() => setDeleteTarget(flat)}
            />
          ))}
        </div>
      )}

      {/* Modals */}
      {selected && (
        <CredentialModal
          flat={selected}
          onClose={() => setSelected(null)}
          onDeleted={() => handleDeleted(selected)}
          onUpdated={(updated) => handleUpdated(selected, updated)}
        />
      )}
      {deleteTarget && !selected && (
        <DeleteConfirmModal
          flat={deleteTarget}
          onClose={() => setDeleteTarget(null)}
          onDeleted={() => handleDeleted(deleteTarget)}
        />
      )}
      {addOpen && (
        <AddItemModal
          websites={websites}
          onClose={() => setAddOpen(false)}
          onAdded={handleAdded}
        />
      )}
    </div>
  );
}
