"use client";

import { useState, useMemo, useEffect } from "react";
import {
  Lock, ExternalLink, Pencil, Trash2, Plus,
  Eye, EyeOff, Copy, Search, X, KeyRound, Globe, Server, Share2,
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

const WEBSITE_TYPES = [
  { value: "wordpress",  label: "WordPress Admin" },
  { value: "wix",        label: "Wix" },
  { value: "webflow",    label: "Webflow" },
  { value: "framer",     label: "Framer" },
  { value: "shopify",    label: "Shopify" },
  { value: "custom",     label: "Custom / Other" },
];

const HOSTING_TYPES = [
  { value: "siteground", label: "SiteGround" },
  { value: "cpanel",     label: "cPanel" },
  { value: "godaddy",    label: "GoDaddy" },
  { value: "namecheap",  label: "Namecheap" },
  { value: "hostinger",  label: "Hostinger" },
  { value: "bluehost",   label: "Bluehost" },
  { value: "wpengine",   label: "WP Engine" },
  { value: "kinsta",     label: "Kinsta" },
  { value: "cloudflare", label: "Cloudflare" },
  { value: "ftp",        label: "FTP / SFTP" },
  { value: "custom",     label: "Custom / Other" },
];

const ALL_TYPES = [...WEBSITE_TYPES, ...HOSTING_TYPES].filter(
  (t, i, arr) => arr.findIndex((x) => x.value === t.value) === i
);

const HOSTING_TYPE_VALUES = new Set(HOSTING_TYPES.map((t) => t.value));

const TYPE_GRADIENTS: Record<string, string> = {
  wordpress:  "from-blue-500 to-indigo-600",
  cpanel:     "from-orange-500 to-red-500",
  godaddy:    "from-green-500 to-emerald-600",
  namecheap:  "from-red-500 to-rose-600",
  hostinger:  "from-violet-500 to-purple-600",
  cloudflare: "from-amber-400 to-orange-500",
  ftp:        "from-purple-500 to-violet-600",
  wix:        "from-slate-600 to-slate-800",
  webflow:    "from-indigo-500 to-blue-600",
  framer:     "from-pink-500 to-rose-600",
  shopify:    "from-emerald-500 to-teal-600",
  siteground: "from-sky-500 to-blue-600",
  bluehost:   "from-blue-600 to-indigo-700",
  wpengine:   "from-teal-500 to-cyan-600",
  kinsta:     "from-fuchsia-500 to-purple-600",
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
  framer:     "bg-pink-50 text-pink-700 border-pink-200",
  siteground: "bg-sky-50 text-sky-700 border-sky-200",
  bluehost:   "bg-blue-50 text-blue-700 border-blue-200",
  wpengine:   "bg-teal-50 text-teal-700 border-teal-200",
  kinsta:     "bg-fuchsia-50 text-fuchsia-700 border-fuchsia-200",
  custom:     "bg-slate-50 text-slate-600 border-slate-200",
};

// ─── Types ────────────────────────────────────────────────────────────────────

interface RevealData { username: string; password: string; notes: string }

function typeLabel(t: string) {
  return ALL_TYPES.find((x) => x.value === t)?.label ?? t;
}
function gradient(t: string) { return TYPE_GRADIENTS[t] ?? "from-slate-400 to-slate-600"; }
function badge(t: string) { return TYPE_BADGE[t] ?? "bg-slate-50 text-slate-600 border-slate-200"; }

// ─── Credential card ──────────────────────────────────────────────────────────

function CredCard({ cred, subtitle, canWrite, onView, onDelete, onShare }: {
  cred: Credential;
  subtitle: string;
  canWrite: boolean;
  onView: () => void;
  onDelete: () => void;
  onShare: () => void;
}) {
  return (
    <div
      className="group border rounded-xl overflow-hidden bg-card hover:shadow-lg transition-all cursor-pointer select-none"
      onClick={onView}
    >
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
      <div className="px-3 pt-2.5 pb-1">
        <p className="font-semibold text-sm truncate">{cred.label}</p>
        <p className="text-xs text-muted-foreground truncate mt-0.5">{subtitle}</p>
      </div>
      <div className="px-3 pb-2.5 flex items-center gap-1.5 mt-1">
        <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded-full border ${badge(cred.credential_type)}`}>
          {typeLabel(cred.credential_type)}
        </span>
        <div className="ml-auto flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
          {canWrite ? (
            <>
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
                onClick={(e) => { e.stopPropagation(); onShare(); }}
                className="p-1 rounded hover:bg-muted transition-colors text-muted-foreground hover:text-foreground"
                title="Share credentials"
              >
                <Share2 className="h-3.5 w-3.5" />
              </button>
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); onDelete(); }}
                className="p-1 rounded hover:bg-destructive/10 transition-colors text-muted-foreground hover:text-destructive"
                title="Delete"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </>
          ) : (
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); onView(); }}
              className="p-1 rounded hover:bg-muted transition-colors text-muted-foreground hover:text-foreground"
              title="View"
            >
              <Eye className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── Detail / edit modal ──────────────────────────────────────────────────────

function CredentialModal({ cred, subtitle, canWrite, onClose, onDeleted, onUpdated }: {
  cred: Credential;
  subtitle: string;
  canWrite: boolean;
  onClose: () => void;
  onDeleted: () => void;
  onUpdated: (updated: Credential) => void;
}) {
  const { toast } = useToast();
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

  function upd(k: string, v: string) { setForm((f) => ({ ...f, [k]: v })); }

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

  const typeList = cred.website_id ? WEBSITE_TYPES : HOSTING_TYPES;

  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent className="sm:max-w-md p-0 overflow-hidden gap-0">
        <div className={`h-24 bg-gradient-to-br ${gradient(cred.credential_type)} flex items-center justify-center relative`}>
          <Lock className="h-10 w-10 text-white/75" />
          {!editMode && canWrite && (
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
          <div>
            {editMode ? (
              <Input value={form.label} onChange={(e) => upd("label", e.target.value)} className="font-semibold text-base mb-2" />
            ) : (
              <h2 className="font-bold text-xl leading-tight">{cred.label}</h2>
            )}
            <div className="flex items-center gap-2 mt-1.5">
              {editMode ? (
                <Select value={form.credential_type} onValueChange={(v) => upd("credential_type", v)}>
                  <SelectTrigger className="h-7 text-xs w-44"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {typeList.map((t) => <SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>)}
                  </SelectContent>
                </Select>
              ) : (
                <span className={`text-xs font-medium px-2 py-0.5 rounded-full border ${badge(cred.credential_type)}`}>
                  {typeLabel(cred.credential_type)}
                </span>
              )}
              <span className="text-xs text-muted-foreground">{subtitle}</span>
            </div>
          </div>

          <div>
            <Label className="text-xs text-muted-foreground uppercase tracking-wide">Login URL</Label>
            {editMode ? (
              <Input value={form.login_url} onChange={(e) => upd("login_url", e.target.value)} placeholder="https://…" className="mt-1" />
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

          {canWrite && (
            <div className="flex items-center gap-2 pt-1 border-t">
              {editMode ? (
                <>
                  <Button variant="outline" size="sm" onClick={() => setEditMode(false)} disabled={saveLoading}>Cancel</Button>
                  <Button size="sm" onClick={handleSave} disabled={saveLoading}>{saveLoading ? "Saving…" : "Save changes"}</Button>
                </>
              ) : !deleteConfirm ? (
                <Button
                  variant="ghost" size="sm"
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
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

// ─── Add new credential modal ─────────────────────────────────────────────────

type Section = "website" | "hosting";

function AddItemModal({ websites, defaultSection, onClose, onAdded }: {
  websites: Website[];
  defaultSection: Section;
  onClose: () => void;
  onAdded: (cred: Credential) => void;
}) {
  const { toast } = useToast();
  const [loading, setLoading] = useState(false);
  const [section, setSection] = useState<Section>(defaultSection);
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

  const typeOptions = section === "website" ? WEBSITE_TYPES : HOSTING_TYPES;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (section === "website" && !form.website_id) {
      toast({ variant: "destructive", title: "Select a website" });
      return;
    }
    setLoading(true);
    try {
      const body: Record<string, string | null> = {
        label: form.label,
        credential_type: form.credential_type || (section === "website" ? "wordpress" : "siteground"),
        login_url: form.login_url,
        username: form.username,
        password: form.password,
        notes: form.notes,
        website_id: section === "website" ? form.website_id : null,
      };

      const res = await fetch("/api/credentials", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) { toast({ variant: "destructive", title: "Failed to save credential" }); return; }
      const created: Credential = await res.json();
      toast({ title: "Credential saved" });
      onAdded(created);
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

        {/* Section toggle */}
        <div className="flex rounded-lg border p-1 gap-1">
          <button
            type="button"
            onClick={() => setSection("website")}
            className={`flex-1 flex items-center justify-center gap-2 rounded-md py-2 text-sm font-medium transition-colors ${
              section === "website" ? "bg-primary text-primary-foreground" : "hover:bg-muted text-muted-foreground"
            }`}
          >
            <Globe className="h-4 w-4" />Website Login
          </button>
          <button
            type="button"
            onClick={() => setSection("hosting")}
            className={`flex-1 flex items-center justify-center gap-2 rounded-md py-2 text-sm font-medium transition-colors ${
              section === "hosting" ? "bg-primary text-primary-foreground" : "hover:bg-muted text-muted-foreground"
            }`}
          >
            <Server className="h-4 w-4" />Hosting / General
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-3">
          {section === "website" && (
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
          )}

          <div className="space-y-1.5">
            <Label>Label</Label>
            <Input
              placeholder={section === "website" ? "e.g. WordPress Admin" : "e.g. SiteGround Account"}
              value={form.label}
              onChange={(e) => upd("label", e.target.value)}
              required
            />
          </div>

          <div className="space-y-1.5">
            <Label>Type</Label>
            <Select
              value={form.credential_type}
              onValueChange={(v) => upd("credential_type", v)}
            >
              <SelectTrigger><SelectValue placeholder="Select type" /></SelectTrigger>
              <SelectContent>
                {typeOptions.map((t) => <SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1.5">
            <Label>Login URL</Label>
            <Input
              placeholder={section === "hosting" ? "https://my.siteground.com" : "https://example.com/wp-admin"}
              value={form.login_url}
              onChange={(e) => upd("login_url", e.target.value)}
            />
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

// ─── Share credential modal ───────────────────────────────────────────────────

function ShareCredentialModal({ cred, onClose }: {
  cred: Credential;
  onClose: () => void;
}) {
  const { toast } = useToast();
  const [revealed, setRevealed] = useState<RevealData | null>(null);
  const [showPw, setShowPw] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    fetch(`/api/credentials/${cred.id}/reveal`, { method: "POST" })
      .then((r) => r.ok ? r.json() : null)
      .then((data) => { if (active && data) setRevealed(data as RevealData); })
      .catch(() => {})
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [cred.id]);

  function copy(text: string, label: string) {
    navigator.clipboard.writeText(text);
    toast({ title: `${label} copied` });
  }

  function copyAll() {
    if (!revealed) return;
    const lines = [
      `Label: ${cred.label}`,
      cred.login_url ? `URL: ${cred.login_url}` : null,
      revealed.username ? `Username: ${revealed.username}` : null,
      revealed.password ? `Password: ${revealed.password}` : null,
      revealed.notes ? `Notes: ${revealed.notes}` : null,
    ].filter(Boolean).join("\n");
    navigator.clipboard.writeText(lines);
    toast({ title: "All credentials copied to clipboard" });
  }

  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent className="sm:max-w-md p-0 overflow-hidden gap-0">
        <div className={`h-20 bg-gradient-to-br ${gradient(cred.credential_type)} flex items-center justify-center`}>
          <Share2 className="h-8 w-8 text-white/80" />
        </div>

        <div className="p-5 space-y-4">
          <div>
            <h2 className="font-bold text-lg leading-tight">{cred.label}</h2>
            <p className="text-xs text-muted-foreground mt-0.5">Share these credentials securely</p>
          </div>

          {loading ? (
            <div className="py-6 text-center text-sm text-muted-foreground">Revealing credentials…</div>
          ) : !revealed ? (
            <div className="py-6 text-center text-sm text-destructive">Could not reveal credentials</div>
          ) : (
            <div className="space-y-3">
              {cred.login_url && (
                <div className="flex items-center gap-2">
                  <div className="flex-1 min-w-0">
                    <p className="text-xs text-muted-foreground uppercase tracking-wide mb-0.5">Login URL</p>
                    <p className="text-sm font-mono truncate">{cred.login_url}</p>
                  </div>
                  <Button size="sm" variant="ghost" className="h-7 w-7 p-0 shrink-0" onClick={() => copy(cred.login_url!, "URL")}>
                    <Copy className="h-3.5 w-3.5" />
                  </Button>
                </div>
              )}

              {revealed.username && (
                <div className="flex items-center gap-2">
                  <div className="flex-1 min-w-0">
                    <p className="text-xs text-muted-foreground uppercase tracking-wide mb-0.5">Username</p>
                    <p className="text-sm font-mono truncate">{revealed.username}</p>
                  </div>
                  <Button size="sm" variant="ghost" className="h-7 w-7 p-0 shrink-0" onClick={() => copy(revealed.username, "Username")}>
                    <Copy className="h-3.5 w-3.5" />
                  </Button>
                </div>
              )}

              {revealed.password && (
                <div className="flex items-center gap-2">
                  <div className="flex-1 min-w-0">
                    <p className="text-xs text-muted-foreground uppercase tracking-wide mb-0.5">Password</p>
                    <p className="text-sm font-mono truncate">{showPw ? revealed.password : "••••••••••••"}</p>
                  </div>
                  <Button size="sm" variant="ghost" className="h-7 w-7 p-0 shrink-0" onClick={() => setShowPw((v) => !v)}>
                    {showPw ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
                  </Button>
                  <Button size="sm" variant="ghost" className="h-7 w-7 p-0 shrink-0" onClick={() => copy(revealed.password, "Password")}>
                    <Copy className="h-3.5 w-3.5" />
                  </Button>
                </div>
              )}

              {revealed.notes && (
                <div>
                  <p className="text-xs text-muted-foreground uppercase tracking-wide mb-0.5">Notes</p>
                  <p className="text-sm text-muted-foreground whitespace-pre-line">{revealed.notes}</p>
                </div>
              )}
            </div>
          )}

          {revealed && (
            <div className="pt-1 border-t flex gap-2">
              <Button size="sm" variant="outline" className="flex-1" onClick={copyAll}>
                <Copy className="h-3.5 w-3.5 mr-1.5" />Copy all
              </Button>
              <Button size="sm" variant="ghost" className="flex-1" onClick={onClose}>Done</Button>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

// ─── Section header ───────────────────────────────────────────────────────────

function SectionHeader({ icon: Icon, title, count, canWrite, onAdd }: {
  icon: React.ElementType;
  title: string;
  count: number;
  canWrite: boolean;
  onAdd: () => void;
}) {
  return (
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-2.5">
        <div className="p-1.5 rounded-lg bg-muted">
          <Icon className="h-4 w-4 text-muted-foreground" />
        </div>
        <div>
          <h2 className="font-semibold text-base">{title}</h2>
          <p className="text-xs text-muted-foreground">{count} saved</p>
        </div>
      </div>
      {canWrite && (
        <Button size="sm" variant="outline" onClick={onAdd}>
          <Plus className="h-3.5 w-3.5 mr-1" />Add
        </Button>
      )}
    </div>
  );
}

// ─── Empty section state ──────────────────────────────────────────────────────

function SectionEmpty({ label, canWrite, onAdd }: { label: string; canWrite: boolean; onAdd: () => void }) {
  return (
    <div className="border rounded-xl py-10 flex flex-col items-center gap-2 text-center">
      <KeyRound className="h-8 w-8 text-muted-foreground opacity-30" />
      <p className="text-sm text-muted-foreground">{label}</p>
      {canWrite && (
        <Button size="sm" variant="ghost" onClick={onAdd}>
          <Plus className="h-3.5 w-3.5 mr-1" />Add one
        </Button>
      )}
    </div>
  );
}

// ─── Main vault client ─────────────────────────────────────────────────────────

export function CredentialsVaultClient({
  initialCredentials,
  websites,
  myRole,
}: {
  initialCredentials: Credential[];
  websites: Website[];
  myRole: string;
}) {
  const canWrite = myRole === "manager" || myRole === "owner";

  const [credentials, setCredentials] = useState(initialCredentials);
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<Credential | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Credential | null>(null);
  const [addSection, setAddSection] = useState<Section | null>(null);
  const [shareTarget, setShareTarget] = useState<Credential | null>(null);

  const websiteCreds = useMemo(() => credentials.filter((c) => c.website_id !== null), [credentials]);
  const hostingCreds = useMemo(() => credentials.filter((c) => c.website_id === null), [credentials]);

  const filtered = useMemo(() => {
    if (!search) return { website: websiteCreds, hosting: hostingCreds };
    const q = search.toLowerCase();
    const match = (c: Credential) =>
      c.label.toLowerCase().includes(q) ||
      (c.website_name ?? "").toLowerCase().includes(q) ||
      c.credential_type.toLowerCase().includes(q);
    return { website: websiteCreds.filter(match), hosting: hostingCreds.filter(match) };
  }, [search, websiteCreds, hostingCreds]);

  function credSubtitle(c: Credential) {
    return c.website_name ?? typeLabel(c.credential_type);
  }

  function handleAdded(cred: Credential) {
    setCredentials((prev) => [cred, ...prev]);
  }

  function handleDeleted(id: string) {
    setCredentials((prev) => prev.filter((c) => c.id !== id));
    setSelected(null);
    setDeleteTarget(null);
  }

  function handleUpdated(updated: Credential) {
    setCredentials((prev) => prev.map((c) => (c.id === updated.id ? updated : c)));
    setSelected((prev) => (prev?.id === updated.id ? updated : prev));
  }

  async function confirmDelete(cred: Credential) {
    try {
      const res = await fetch(`/api/credentials/${cred.id}`, { method: "DELETE" });
      if (res.ok || res.status === 204) handleDeleted(cred.id);
    } catch { /* ignore */ }
    setDeleteTarget(null);
  }

  const totalCreds = credentials.length;

  return (
    <div className="p-8 space-y-8">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Vault</h1>
          <p className="text-muted-foreground mt-1">
            {totalCreds > 0
              ? `${totalCreds} credential${totalCreds !== 1 ? "s" : ""} — encrypted and secured`
              : "Securely store all your logins in one place"}
          </p>
        </div>
        {canWrite && (
          <Button onClick={() => setAddSection("hosting")}>
            <Plus className="h-4 w-4 mr-1.5" />New item
          </Button>
        )}
      </div>

      {/* Search */}
      {totalCreds > 0 && (
        <div className="relative max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search vault…"
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
      )}

      {/* ── Website Credentials ── */}
      <section className="space-y-4">
        <SectionHeader
          icon={Globe}
          title="Website Credentials"
          count={websiteCreds.length}
          canWrite={canWrite}
          onAdd={() => setAddSection("website")}
        />
        {filtered.website.length === 0 ? (
          <SectionEmpty
            label={search ? "No website credentials match your search." : "No website logins saved yet — add a WordPress admin, Wix, Shopify, or other site login."}
            canWrite={canWrite}
            onAdd={() => setAddSection("website")}
          />
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
            {filtered.website.map((cred) => (
              <CredCard
                key={cred.id}
                cred={cred}
                subtitle={credSubtitle(cred)}
                canWrite={canWrite}
                onView={() => setSelected(cred)}
                onDelete={() => setDeleteTarget(cred)}
                onShare={() => setShareTarget(cred)}
              />
            ))}
          </div>
        )}
      </section>

      {/* ── Hosting & General ── */}
      <section className="space-y-4">
        <SectionHeader
          icon={Server}
          title="Hosting &amp; General"
          count={hostingCreds.length}
          canWrite={canWrite}
          onAdd={() => setAddSection("hosting")}
        />
        {filtered.hosting.length === 0 ? (
          <SectionEmpty
            label={search ? "No hosting credentials match your search." : "No hosting or general logins saved yet — add SiteGround, cPanel, GoDaddy, Cloudflare, and more."}
            canWrite={canWrite}
            onAdd={() => setAddSection("hosting")}
          />
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
            {filtered.hosting.map((cred) => (
              <CredCard
                key={cred.id}
                cred={cred}
                subtitle={typeLabel(cred.credential_type)}
                canWrite={canWrite}
                onView={() => setSelected(cred)}
                onDelete={() => setDeleteTarget(cred)}
                onShare={() => setShareTarget(cred)}
              />
            ))}
          </div>
        )}
      </section>

      {/* Modals */}
      {selected && (
        <CredentialModal
          cred={selected}
          subtitle={credSubtitle(selected)}
          canWrite={canWrite}
          onClose={() => setSelected(null)}
          onDeleted={() => handleDeleted(selected.id)}
          onUpdated={handleUpdated}
        />
      )}

      {shareTarget && !selected && (
        <ShareCredentialModal
          cred={shareTarget}
          onClose={() => setShareTarget(null)}
        />
      )}

      {deleteTarget && !selected && (
        <Dialog open onOpenChange={() => setDeleteTarget(null)}>
          <DialogContent>
            <DialogHeader><DialogTitle>Delete credential?</DialogTitle></DialogHeader>
            <p className="text-sm text-muted-foreground">
              This will permanently delete <strong>{deleteTarget.label}</strong>.
            </p>
            <DialogFooter>
              <Button variant="outline" onClick={() => setDeleteTarget(null)}>Cancel</Button>
              <Button variant="destructive" onClick={() => confirmDelete(deleteTarget)}>Delete</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}

      {canWrite && addSection && (
        <AddItemModal
          websites={websites}
          defaultSection={addSection}
          onClose={() => setAddSection(null)}
          onAdded={handleAdded}
        />
      )}
    </div>
  );
}
