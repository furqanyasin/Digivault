"use client";

import { useState, useMemo, useEffect } from "react";
import {
  Lock, ExternalLink, Pencil, Trash2, Plus,
  Eye, EyeOff, Copy, Search, X, KeyRound, Globe, Server, Share2, Upload, FileDown, Download,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PasswordInput } from "@/components/ui/password-input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { useToast } from "@/hooks/use-toast";
import type { Credential, CredentialShare, Website } from "@/lib/api";

// ─── Constants ────────────────────────────────────────────────────────────────

// A template for the CSV importer, offered next to the Import button so nobody
// has to reverse-engineer the column names from an error message. The header row
// is exactly what CredentialImportView reads (a LastPass export's own columns);
// the rows demonstrate a site login, a hosting panel, and a TOTP secret.
// `grouping` and the URL are what the importer's type guesser reads, so these
// examples land as wordpress / siteground / cloudflare rather than "custom".
const SAMPLE_CSV = [
  "url,username,password,totp,extra,name,grouping,fav",
  'https://example.com/wp-admin,admin@example.com,"Repl4ce-Me!",,"Main WordPress admin — replace before importing.",Example Co — WordPress Admin,Website Credentials,0',
  'https://my.siteground.com,agency@youragency.com,"H0sting-Pass!",JBSWY3DPEHPK3PXP,"Hosting control panel. The totp column becomes a note.",SiteGround — Hosting,Hosting,0',
  'https://dash.cloudflare.com,dns@youragency.com,"DNS-Pass-123!",,,Cloudflare — DNS,Hosting,0',
  "",
].join("\n");

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

// Card header colours. One muted family — desaturated teals, slate blues,
// navies and soft purples — rather than a saturated hue per brand: the vault is
// a wall of cards, and full-strength oranges/pinks beside each other made it
// read as noise. Hex rather than Tailwind classes because the value is chosen at
// runtime, and Tailwind cannot generate a class it never sees in the source.
const TYPE_COLOR: Record<string, string> = {
  wordpress:  "#4a6b96",
  cpanel:     "#2f7b88",
  godaddy:    "#1e4e5c",
  namecheap:  "#5a7fa6",
  hostinger:  "#7d78b4",
  cloudflare: "#3d8f9b",
  ftp:        "#8a86bd",
  wix:        "#28324f",
  webflow:    "#4a54a8",
  framer:     "#272d6b",
  shopify:    "#2f7b88",
  siteground: "#5a7fa6",
  bluehost:   "#1e2a5e",
  wpengine:   "#1e4e5c",
  kinsta:     "#7d78b4",
  custom:     "#5a7fa6",
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

// Solid brand dot shown beside each option in the type dropdown, so platforms
// are recognisable at a glance. Hues match TYPE_BADGE / TYPE_COLOR.
function dot(t: string) { return TYPE_COLOR[t] ?? "#5a7fa6"; }

// ─── Types ────────────────────────────────────────────────────────────────────

interface RevealData { username: string; password: string; notes: string; password_hidden?: boolean }

// Most vault items are "custom", so each gets a stable colour derived from its
// name — enough variety to tell cards apart at a glance, all within the same
// muted band so the grid still reads as one set.
const CARD_COLORS = [
  "#4a6b96", "#2f7b88", "#1e4e5c", "#5a7fa6", "#7d78b4",
  "#3d8f9b", "#1e2a5e", "#4a54a8", "#8a86bd", "#272d6b",
  "#4aa3ad", "#28324f",
];

function hashString(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
  return Math.abs(h);
}

function typeLabel(t: string) {
  return ALL_TYPES.find((x) => x.value === t)?.label ?? t;
}
function badge(t: string) { return TYPE_BADGE[t] ?? "bg-slate-50 text-slate-600 border-slate-200"; }

/** Header colour for a card: the provider's colour when known, otherwise a
 *  stable pick from the palette so the same credential always looks the same. */
function cardColor(cred: { credential_type: string; label?: string }): string {
  const known = TYPE_COLOR[cred.credential_type];
  if (known && cred.credential_type !== "custom") return known;
  const seed = cred.label || cred.credential_type || "";
  return CARD_COLORS[hashString(seed) % CARD_COLORS.length];
}

// ─── Credential card ──────────────────────────────────────────────────────────

function hostFromUrl(url: string): string | null {
  if (!url) return null;
  try {
    return new URL(url).hostname;
  } catch {
    return null;
  }
}

/** Up to two initials for the card monogram: one per word, label first. Matches
 *  the avatar initials on the Activity Log so the two read as the same idiom. */
function monogram(cred: { label?: string; credential_type: string }): string {
  const source = (cred.label || "").trim() || typeLabel(cred.credential_type);
  const letters = source
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((word) => word[0]);
  return letters.join("").toUpperCase() || "?";
}

/** Site favicon on the card header, over a monogram of the credential's name.
 *
 *  The monogram is the base layer rather than a `failed ? …` branch, so the
 *  fallback is already painted when the image drops out — no flash. It has to
 *  cover three separate failures that used to collapse onto one padlock: no
 *  login_url to derive a host from, a host whose favicon Google 404s (it does
 *  404 for icon-less domains — it does not serve a placeholder), and a request
 *  that simply fails. A padlock meant all three, and on a vault every card is
 *  a secret, so it distinguished nothing. */
function CardArt({ cred }: { cred: Credential }) {
  const host = hostFromUrl(cred.login_url);
  const [failed, setFailed] = useState(false);
  return (
    <span className="relative flex h-10 w-10 items-center justify-center">
      {/* aria-hidden: the card body already names the credential, so reading
          the initials out would just repeat it. */}
      <span aria-hidden className="text-base font-semibold tracking-wide text-white/85">
        {monogram(cred)}
      </span>
      {host && !failed && (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={`https://www.google.com/s2/favicons?domain=${host}&sz=128`}
          alt=""
          width={40}
          height={40}
          className="absolute inset-0 h-10 w-10 rounded-md bg-white/95 p-1.5 shadow-sm object-contain"
          onError={() => setFailed(true)}
        />
      )}
    </span>
  );
}

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
      <div
        className="relative flex h-[72px] items-center justify-center"
        style={{ backgroundColor: cardColor(cred) }}
      >
        <CardArt cred={cred} />
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

  // Entering edit reveals the stored values first (when possible) so every
  // field is populated and editable, not just the metadata.
  async function enterEdit() {
    if (!revealed) {
      try {
        const res = await fetch(`/api/credentials/${cred.id}/reveal`, { method: "POST" });
        if (res.ok) {
          const data: RevealData = await res.json();
          setRevealed(data);
          setForm((f) => ({ ...f, username: data.username, password: data.password, notes: data.notes }));
        }
      } catch {
        // fall through to edit with metadata only; blank secret fields are
        // left unchanged on save
      }
    }
    setEditMode(true);
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
        <div
          className="relative flex h-24 items-center justify-center"
          style={{ backgroundColor: cardColor(cred) }}
        >
          {/* Same art as the grid card, so opening one doesn't swap a
              recognisable favicon for a generic padlock. */}
          <CardArt cred={cred} />
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
                    {typeList.map((t) => (
                      <SelectItem key={t.value} value={t.value}>
                        <span className="flex items-center gap-2">
                          <span className={`h-2 w-2 shrink-0 rounded-full ${dot(t.value)}`} aria-hidden />
                          {t.label}
                        </span>
                      </SelectItem>
                    ))}
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
                  <PasswordInput value={form.password} onChange={(e) => upd("password", e.target.value)} className="mt-1" />
                ) : revealed?.password_hidden ? (
                  <div className="flex items-center gap-2 mt-1">
                    <Lock className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                    <span className="text-xs text-muted-foreground">
                      Hidden by share settings — you can autofill but not view this password.
                    </span>
                  </div>
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
                <>
                  <Button variant="outline" size="sm" onClick={enterEdit}>
                    <Pencil className="h-3.5 w-3.5 mr-1.5" />Edit
                  </Button>
                  <Button
                    variant="ghost" size="sm"
                    className="text-destructive hover:text-destructive hover:bg-destructive/10 ml-auto"
                    onClick={() => setDeleteConfirm(true)}
                  >
                    <Trash2 className="h-3.5 w-3.5 mr-1.5" />Delete
                  </Button>
                </>
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
    credential_type: "",
    custom_type: "",
    login_url: "",
    username: "",
    password: "",
    notes: "",
  });

  function upd(k: string, v: string) { setForm((f) => ({ ...f, [k]: v })); }

  const typeOptions = section === "website" ? WEBSITE_TYPES : HOSTING_TYPES;
  const isCustom = form.credential_type === "custom";

  // Selecting a website autofills as much as possible: the login URL derived
  // from its domain, and a sensible default type from its platform.
  function selectWebsite(id: string) {
    const site = websites.find((w) => w.id === id);
    const domain = (site?.domain || "").replace(/^https?:\/\//, "").replace(/\/$/, "");
    setForm((f) => {
      const platform = (site?.platform || "").toLowerCase();
      const type = f.credential_type || (platform === "wordpress" || !platform ? "wordpress" : "custom");
      const loginUrl = domain
        ? type === "wordpress" ? `https://${domain}/wp-admin` : `https://${domain}`
        : f.login_url;
      return { ...f, website_id: id, credential_type: type, login_url: loginUrl };
    });
  }

  // Label is auto-generated (the field was removed from the form). For custom
  // types the free-text CMS/hosting name stands in for the type.
  function derivedLabel(): string {
    const site = websites.find((w) => w.id === form.website_id);
    const typeName = isCustom
      ? (form.custom_type.trim() || "Custom")
      : typeLabel(form.credential_type || (section === "website" ? "wordpress" : "siteground"));
    if (section === "website") {
      const siteName = site?.name || site?.domain || "Website";
      return `${siteName} — ${typeName}`;
    }
    return form.custom_type.trim() ? `${form.custom_type.trim()} Account` : `${typeName} Account`;
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (section === "website" && !form.website_id) {
      toast({ variant: "destructive", title: "Select a website" });
      return;
    }
    if (isCustom && !form.custom_type.trim()) {
      toast({ variant: "destructive", title: section === "website" ? "Enter the CMS type" : "Enter the hosting type" });
      return;
    }
    setLoading(true);
    try {
      const body: Record<string, string | null> = {
        label: derivedLabel(),
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
              <Select value={form.website_id} onValueChange={selectWebsite}>
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
            <Label>{section === "website" ? "CMS type" : "Hosting type"}</Label>
            <Select
              value={form.credential_type}
              onValueChange={(v) => upd("credential_type", v)}
            >
              <SelectTrigger>
                <SelectValue placeholder={section === "website" ? "Select CMS type" : "Select hosting type"} />
              </SelectTrigger>
              <SelectContent>
                {typeOptions.map((t) => (
                  <SelectItem key={t.value} value={t.value}>
                    <span className="flex items-center gap-2">
                      <span className={`h-2 w-2 shrink-0 rounded-full ${dot(t.value)}`} aria-hidden />
                      {t.label}
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {isCustom && (
            <div className="space-y-1.5">
              <Label>{section === "website" ? "Which CMS?" : "Which host?"}</Label>
              <Input
                placeholder={section === "website" ? "e.g. Joomla, Drupal, Ghost" : "e.g. AWS, DigitalOcean, Vercel"}
                value={form.custom_type}
                onChange={(e) => upd("custom_type", e.target.value)}
                autoFocus
              />
            </div>
          )}

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
              <PasswordInput value={form.password} onChange={(e) => upd("password", e.target.value)} autoComplete="new-password" required />
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

// ─── Share credential modal (LastPass-style) ──────────────────────────────────

interface DevOption { id: string; email: string; name: string }

function ShareCredentialModal({ cred, teamId, onClose }: {
  cred: Credential;
  teamId: string | null;
  onClose: () => void;
}) {
  const { toast } = useToast();
  const [developers, setDevelopers] = useState<DevOption[]>([]);
  const [shares, setShares] = useState<CredentialShare[]>([]);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [canViewPw, setCanViewPw] = useState(true);
  const [loading, setLoading] = useState(true);
  const [sharing, setSharing] = useState(false);

  useEffect(() => {
    let active = true;
    async function load() {
      const [membersRes, sharesRes] = await Promise.all([
        teamId ? fetch(`/api/teams/${teamId}/members`) : Promise.resolve(null),
        fetch(`/api/credentials/${cred.id}/shares`),
      ]);
      if (!active) return;
      if (membersRes?.ok) {
        const members = await membersRes.json();
        const list = Array.isArray(members) ? members : members?.data ?? [];
        setDevelopers(
          list
            .filter((m: { role: string }) => m.role === "developer")
            .map((m: { user: { id: string; email: string; first_name: string; last_name: string } }) => ({
              id: m.user.id,
              email: m.user.email,
              name: `${m.user.first_name ?? ""} ${m.user.last_name ?? ""}`.trim(),
            }))
        );
      }
      if (sharesRes.ok) {
        const data = await sharesRes.json();
        setShares(Array.isArray(data) ? data : data?.data ?? []);
      }
      setLoading(false);
    }
    load().catch(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [cred.id, teamId]);

  const sharedUserIds = useMemo(() => new Set(shares.map((s) => s.user_id)), [shares]);
  const candidates = developers.filter((d) => !sharedUserIds.has(d.id));

  function toggle(id: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  async function handleShare() {
    if (selectedIds.size === 0) return;
    setSharing(true);
    try {
      const res = await fetch(`/api/credentials/${cred.id}/shares`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_ids: Array.from(selectedIds),
          can_view_password: canViewPw,
        }),
      });
      if (!res.ok) {
        toast({ variant: "destructive", title: "Failed to share credential" });
        return;
      }
      const data = await res.json();
      setShares(Array.isArray(data) ? data : data?.data ?? []);
      setSelectedIds(new Set());
      toast({ title: "Credential shared" });
    } catch {
      toast({ variant: "destructive", title: "Network error" });
    } finally {
      setSharing(false);
    }
  }

  async function revoke(userId: string) {
    const res = await fetch(`/api/credentials/${cred.id}/shares/${userId}`, { method: "DELETE" });
    if (res.ok || res.status === 204) {
      setShares((prev) => prev.filter((s) => s.user_id !== userId));
      toast({ title: "Share revoked" });
    } else {
      toast({ variant: "destructive", title: "Failed to revoke share" });
    }
  }

  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent className="sm:max-w-2xl p-0 overflow-hidden gap-0">
        <div
          className="flex h-16 items-center gap-3 px-5"
          style={{ backgroundColor: cardColor(cred) }}
        >
          <Share2 className="h-6 w-6 text-white/80 shrink-0" />
          <h2 className="font-bold text-lg text-white truncate">Share: {cred.label}</h2>
        </div>

        {loading ? (
          <div className="py-12 text-center text-sm text-muted-foreground">Loading…</div>
        ) : (
          <div className="grid md:grid-cols-2 divide-y md:divide-y-0 md:divide-x">
            {/* Left — grant access */}
            <div className="p-5 space-y-4">
              <div>
                <p className="text-sm font-semibold mb-2">Share with developers</p>
                {candidates.length === 0 ? (
                  <p className="text-xs text-muted-foreground">
                    {developers.length === 0
                      ? "No developers on this team yet. Owners and managers already see every credential."
                      : "All developers already have access."}
                  </p>
                ) : (
                  <div className="space-y-1.5 max-h-44 overflow-y-auto pr-1">
                    {candidates.map((d) => (
                      <label key={d.id} className="flex items-center gap-2.5 rounded-md border px-3 py-2 cursor-pointer hover:bg-muted/50 transition-colors">
                        <input
                          type="checkbox"
                          checked={selectedIds.has(d.id)}
                          onChange={() => toggle(d.id)}
                          className="h-4 w-4 accent-primary"
                        />
                        <span className="min-w-0">
                          <span className="block text-sm truncate">{d.name || d.email}</span>
                          {d.name && <span className="block text-xs text-muted-foreground truncate">{d.email}</span>}
                        </span>
                      </label>
                    ))}
                  </div>
                )}
              </div>

              <label className="flex items-center gap-2.5 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={canViewPw}
                  onChange={(e) => setCanViewPw(e.target.checked)}
                  className="h-4 w-4 accent-primary"
                />
                <span className="text-sm">Allow Recipient to View Password</span>
              </label>
              {!canViewPw && (
                <p className="text-xs text-muted-foreground -mt-2">
                  Recipient can use the credential (autofill) but the password stays hidden in the dashboard.
                </p>
              )}

              <Button
                size="sm"
                className="w-full"
                disabled={sharing || selectedIds.size === 0}
                onClick={handleShare}
              >
                {sharing ? "Sharing…" : `Share${selectedIds.size > 0 ? ` (${selectedIds.size})` : ""}`}
              </Button>
            </div>

            {/* Right — existing shares */}
            <div className="p-5">
              <p className="text-sm font-semibold mb-2">Existing shares</p>
              {shares.length === 0 ? (
                <p className="text-xs text-muted-foreground">Not shared with anyone yet.</p>
              ) : (
                <div className="space-y-1.5 max-h-60 overflow-y-auto pr-1">
                  {shares.map((s) => (
                    <div key={s.user_id} className="flex items-center gap-2 rounded-md border px-3 py-2">
                      <div className="min-w-0 flex-1">
                        <p className="text-sm truncate">{s.name || s.email}</p>
                        <p className="text-xs text-muted-foreground truncate">{s.email}</p>
                      </div>
                      {!s.can_view_password && (
                        <Badge variant="secondary" className="text-[10px] shrink-0">password hidden</Badge>
                      )}
                      <button
                        type="button"
                        onClick={() => revoke(s.user_id)}
                        className="p-1 rounded hover:bg-destructive/10 text-muted-foreground hover:text-destructive transition-colors shrink-0"
                        title="Revoke access"
                      >
                        <X className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  ))}
                </div>
              )}
              <p className="text-[11px] text-muted-foreground mt-3">
                Owners and managers always have access and are not listed here.
              </p>
            </div>
          </div>
        )}
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
  teamId = null,
}: {
  initialCredentials: Credential[];
  websites: Website[];
  myRole: string;
  teamId?: string | null;
}) {
  const { toast } = useToast();
  const canWrite = myRole === "manager" || myRole === "owner";

  const [credentials, setCredentials] = useState(initialCredentials);
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<Credential | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Credential | null>(null);
  const [addSection, setAddSection] = useState<Section | null>(null);
  const [shareTarget, setShareTarget] = useState<Credential | null>(null);
  const [importing, setImporting] = useState(false);
  const [exporting, setExporting] = useState(false);

  // Built and downloaded in the browser — a static template needs no round trip.
  // The leading BOM is for Excel, which reads a BOM-less UTF-8 CSV as ANSI and
  // mangles the em dashes. The importer decodes utf-8-sig, so it strips cleanly.
  function handleDownloadSample() {
    const url = URL.createObjectURL(
      new Blob(["﻿" + SAMPLE_CSV], { type: "text/csv;charset=utf-8" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = "digivault-vault-sample.csv";
    link.click();
    URL.revokeObjectURL(url);
  }

  async function handleImportCsv(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setImporting(true);
    const form = new FormData();
    form.append("file", file);
    try {
      const res = await fetch("/api/credentials/import", { method: "POST", body: form });
      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        // Report against the row count so a short import is obvious straight
        // away rather than being discovered later as missing logins.
        const parts = [
          `${data.created ?? 0} added`,
          `${data.updated ?? 0} updated`,
          `${data.skipped ?? 0} skipped`,
        ];
        if (data.failed) parts.push(`${data.failed} failed`);
        toast({
          title: `Import complete — ${data.rows ?? 0} rows read`,
          description: parts.join(", ") + ".",
        });
        setTimeout(() => window.location.reload(), 1400);
      } else {
        toast({ variant: "destructive", title: "Import failed", description: data?.detail ?? "Check the CSV and try again." });
      }
    } catch {
      toast({ variant: "destructive", title: "Network error" });
    } finally {
      setImporting(false);
      e.target.value = "";
    }
  }

  // Downloads every password in plaintext, so it goes through fetch rather than
  // a plain <a download>: that way a 403 surfaces as a toast instead of the
  // browser silently saving an error page as "vault-export.csv".
  async function handleExportCsv() {
    setExporting(true);
    try {
      const res = await fetch("/api/credentials/export");
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        toast({
          variant: "destructive",
          title: "Export failed",
          description: data?.detail ?? "You may not have permission to export the vault.",
        });
        return;
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "digivault-vault-export.csv";
      link.click();
      URL.revokeObjectURL(url);
      toast({
        title: "Vault exported",
        description: "The file holds every password in plaintext — store it somewhere safe or delete it once used.",
      });
    } catch {
      toast({ variant: "destructive", title: "Network error" });
    } finally {
      setExporting(false);
    }
  }

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
          <div className="flex items-center gap-2">
            <Button variant="ghost" onClick={handleDownloadSample} title="Download a CSV template with the columns the importer expects">
              <FileDown className="h-4 w-4 mr-1.5" />Sample CSV
            </Button>
            <label className="cursor-pointer">
              <input type="file" accept=".csv" className="hidden" onChange={handleImportCsv} disabled={importing} />
              <Button variant="outline" asChild>
                <span><Upload className="h-4 w-4 mr-1.5" />{importing ? "Importing…" : "Import CSV"}</span>
              </Button>
            </label>
            <Button
              variant="outline"
              onClick={handleExportCsv}
              disabled={exporting || totalCreds === 0}
              title="Download the whole vault as a CSV — includes plaintext passwords"
            >
              <Download className="h-4 w-4 mr-1.5" />{exporting ? "Exporting…" : "Export CSV"}
            </Button>
            <Button onClick={() => setAddSection("hosting")}>
              <Plus className="h-4 w-4 mr-1.5" />New item
            </Button>
          </div>
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
          teamId={teamId}
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
