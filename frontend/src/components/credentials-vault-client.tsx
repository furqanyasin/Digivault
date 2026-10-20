"use client";

import { useState, useMemo, useEffect } from "react";
import {
  Lock, ExternalLink, Pencil, Trash2, Plus,
  Eye, EyeOff, Copy, Search, X, KeyRound, Globe, Server, Share2, Upload, FileDown, Download,
  Check, CheckSquare, ChevronDown, CopyPlus, FolderInput, Link2, User,
  Folder, AlertTriangle, ScrollText,
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
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel,
  DropdownMenuSeparator, DropdownMenuSub, DropdownMenuSubContent,
  DropdownMenuSubTrigger, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Badge } from "@/components/ui/badge";
import { useToast } from "@/hooks/use-toast";
import type {
  Credential, CredentialGroupGrant, CredentialShare, SubTeam, VaultFolder, Website,
} from "@/lib/api";
import { SHAREABLE_ROLES, roleLabel } from "@/lib/roles";
import { CLIPBOARD_CLEAR_SECONDS, copySecret } from "@/lib/clipboard";
import { AccessRequestsPanel, RequestAccessDialog } from "@/components/vault-access-requests";
import { GenerateButton, PasswordHistorySection } from "@/components/vault-password-tools";
import { BrokenLoginControl, WhoHasAccessSection } from "@/components/vault-access-panel";
import { FolderManagerDialog, FolderPicker, ShareFolderDialog } from "@/components/vault-folders";

// ─── Constants ────────────────────────────────────────────────────────────────

// A template for the CSV importer, offered next to the Import button so nobody
// has to reverse-engineer the column names from an error message. The header is
// the one the export writes, which is every field the vault stores against a
// credential, so a sample filled in and imported produces exactly what a
// hand-added entry would.
//
// The `teams` cells are left empty on purpose: group names are per-agency, so a
// placeholder here would import as an "unknown group" warning on every row. The
// format is spelled out in the third row's notes instead.
const SAMPLE_CSV = [
  "name,credential_type,website,url,username,password,notes,teams,department,totp,folder",
  'Example Co Website Login,wordpress,example.com,https://example.com/wp-admin,admin@example.com,Repl4ce-Me!,"Replace every row before importing. The credential_type column takes the value shown in the app, such as wordpress, cpanel, ftp or custom.",,,,Web',
  'Example Co Hosting Panel,siteground,example.com,https://my.siteground.com,agency@youragency.com,H0sting-Pass!,"The website column links this login to example.com even though the panel lives on another domain.",,,,Web',
  'Example Co Search Console,google_search_console,example.com,https://search.google.com/search-console,seo@youragency.com,GSC-Pass-123!,"folder files it in a vault folder, created if it does not exist yet. LastPass\'s grouping column works too.",,,,SEO',
  'Cloudflare DNS,cloudflare,,https://dash.cloudflare.com,dns@youragency.com,DNS-Pass-123!,"Leave website empty for an agency-wide login. To give a group access, put its name in teams, semicolon separated, and add :view to let it reveal the password. Owners only.",,,,',
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
  // SEO / ads / agency tools. Filed under the SEO or Ads department by default.
  { value: "google_search_console",   label: "Google Search Console" },
  { value: "google_analytics",        label: "Google Analytics" },
  { value: "google_business_profile", label: "Google Business Profile" },
  { value: "google_tag_manager",      label: "Google Tag Manager" },
  { value: "google_ads",              label: "Google Ads" },
  { value: "meta_business",           label: "Meta Business Suite" },
  { value: "semrush",                 label: "Semrush" },
  { value: "ahrefs",                  label: "Ahrefs" },
  // Items that are not website logins: same encrypted fields, labelled for what
  // they hold (see fieldsFor).
  { value: "secure_note", label: "Secure Note" },
  { value: "server",      label: "Server / SSH" },
  { value: "database",    label: "Database" },
  { value: "api_key",     label: "API Key" },
  { value: "wifi",        label: "Wi-Fi" },
  { value: "custom",     label: "Custom / Other" },
];

/** What each stored field means for a type. `null` hides the field: a secure
 *  note has no login, a Wi-Fi network no URL. Logins get the defaults. */
type FieldLabels = { url: string | null; username: string | null; password: string | null; notes: string };
const DEFAULT_FIELDS: FieldLabels = { url: "Login URL", username: "Username", password: "Password", notes: "Notes" };
const KIND_FIELDS: Record<string, FieldLabels> = {
  secure_note: { url: null, username: null, password: null, notes: "Note" },
  server:      { url: "Host", username: "Username", password: "Password or private key", notes: "Notes" },
  database:    { url: "Host / connection string", username: "Username", password: "Password", notes: "Notes" },
  api_key:     { url: "Service URL", username: "Account or key ID", password: "API key", notes: "Notes" },
  wifi:        { url: null, username: "Network name (SSID)", password: "Password", notes: "Notes" },
};
function fieldsFor(type: string): FieldLabels {
  return KIND_FIELDS[type] ?? DEFAULT_FIELDS;
}
/** Item kinds where a username and password are not both expected. */
const LOGINLESS_KINDS = new Set(["secure_note", "api_key", "wifi"]);

const ALL_FILTER = "__all__";
const UNFILED = "__unfiled__";

export const ALL_TYPES = [...WEBSITE_TYPES, ...HOSTING_TYPES].filter(
  (t, i, arr) => arr.findIndex((x) => x.value === t.value) === i
);

// A CSV row that matches a login already in the vault, as the importer's
// `preview` pass reports it. `username` arrives partly masked.
type ImportConflict = {
  row: number;
  label: string;
  username: string;
  credential_type: string;
  login_url: string;
  website_name: string | null;
  existing_id: string;
  existing_label: string;
  existing_updated_at: string;
};

type ImportPreview = {
  rows: number;
  created: number;          // rows that are genuinely new
  duplicates: number;       // rows that match something already saved
  repeats_in_file: number;  // rows the file itself repeats
  skipped: number;
  failed: number;
  conflicts: ImportConflict[];
};

// What to do with the rows the vault already has.
type ImportMode = "update" | "skip" | "duplicate";

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

// ─── Sorting ──────────────────────────────────────────────────────────────────

// "Folder" is the heading a card already sits under — the linked website for a
// website login, the provider for a hosting one. The vault stores no folder of
// its own, and that subtitle is the only grouping visible on a card, so sorting
// by anything else would order the wall of cards by something the user cannot
// see.
const SORT_OPTIONS = [
  { value: "folder-asc",  label: "Folder (a-z)" },
  { value: "folder-desc", label: "Folder (z-a)" },
  { value: "name-asc",    label: "Name (a-z)" },
  { value: "name-desc",   label: "Name (z-a)" },
  { value: "recent",      label: "Most Recent" },
] as const;

type SortKey = (typeof SORT_OPTIONS)[number]["value"];

function folderKey(c: Credential) {
  // The client folder first, now that credentials can be filed under one.
  // The folder first — it is how the team arranges the vault.
  return c.folder_name ?? c.website_name ?? typeLabel(c.credential_type);
}

// localeCompare with numeric collation: "Client 2" sorts before "Client 10",
// and accented names file beside their unaccented spelling instead of after Z.
const collate = (a: string, b: string) =>
  a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" });

function sortCredentials(list: Credential[], sort: SortKey) {
  const byName = (a: Credential, b: Credential) => collate(a.label, b.label);
  const copy = [...list];
  switch (sort) {
    case "name-asc":
      return copy.sort(byName);
    case "name-desc":
      return copy.sort((a, b) => byName(b, a));
    // Name is the tiebreak in both folder directions: reversing it as well
    // would reshuffle the cards inside a folder, which is not what the control
    // says it does.
    case "folder-asc":
      return copy.sort((a, b) => collate(folderKey(a), folderKey(b)) || byName(a, b));
    case "folder-desc":
      return copy.sort((a, b) => collate(folderKey(b), folderKey(a)) || byName(a, b));
    default:
      return copy.sort(
        (a, b) =>
          new Date(b.updated_at ?? b.created_at).getTime() -
          new Date(a.updated_at ?? a.created_at).getTime(),
      );
  }
}

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

function CredCard({
  cred, subtitle, canWrite, selectable, selecting, isSelected, onToggleSelect,
  onView, onDelete, onShare,
}: {
  cred: Credential;
  subtitle: string;
  canWrite: boolean;
  /** Whether this card offers a tick box at all — write access only, since
   *  every bulk action behind it is a write. */
  selectable: boolean;
  /** A selection is in progress. The boxes are pinned visible and a plain click
   *  adds to the selection instead of opening the credential: picking twenty
   *  cards should not mean twenty modals. */
  selecting: boolean;
  isSelected: boolean;
  onToggleSelect: () => void;
  onView: () => void;
  onDelete: () => void;
  onShare: () => void;
}) {
  // Hidden until hover while nothing is picked, so the wall of cards does not
  // read as a form; pinned the moment a selection exists, because that is when
  // an unpicked card has to show that it is unpicked.
  const boxVisibility = isSelected || selecting
    ? "opacity-100"
    : "opacity-0 group-hover:opacity-100 focus-visible:opacity-100";
  return (
    <div
      className={`group border rounded-xl overflow-hidden bg-card hover:shadow-lg transition-all cursor-pointer select-none ${
        isSelected ? "border-primary ring-2 ring-primary" : ""
      }`}
      onClick={selecting ? onToggleSelect : onView}
    >
      <div
        className="relative flex h-[72px] items-center justify-center"
        style={{ backgroundColor: cardColor(cred) }}
      >
        <CardArt cred={cred} />
        {selectable && (
          <button
            type="button"
            role="checkbox"
            aria-checked={isSelected}
            aria-label={isSelected ? `Deselect ${cred.label}` : `Select ${cred.label}`}
            onClick={(e) => { e.stopPropagation(); onToggleSelect(); }}
            className={`absolute right-2 top-2 z-10 flex h-5 w-5 items-center justify-center rounded border shadow-sm transition-opacity ${boxVisibility} ${
              isSelected
                ? "border-primary bg-primary text-primary-foreground"
                : "border-white/80 bg-white/25 text-transparent hover:bg-white/40"
            }`}
          >
            <Check className="h-3.5 w-3.5" />
          </button>
        )}
        {cred.login_url && !selecting && (
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
        <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded-full border truncate ${badge(cred.credential_type)}`}>
          {typeLabel(cred.credential_type)}
        </span>
        {cred.folder_name ? (
          <span className="text-[10px] font-medium px-1.5 py-0.5 rounded-full border bg-violet-50 text-violet-700 border-violet-200 truncate max-w-[45%]">
            {cred.folder_name}
          </span>
        ) : null}
        {cred.broken ? (
          <span title="Reported as not working" className="shrink-0 text-amber-600">
            <AlertTriangle className="h-3.5 w-3.5" />
          </span>
        ) : null}
        <div
          className={`ml-auto flex items-center gap-0.5 transition-opacity ${
            selecting ? "hidden" : "opacity-0 group-hover:opacity-100"
          }`}
        >
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

function CredentialModal({
  cred, subtitle, canWrite, websites, folders, onFolderCreated, groups, canManageGroups, onClose, onDeleted, onUpdated,
}: {
  cred: Credential;
  subtitle: string;
  canWrite: boolean;
  /** The team's websites, for re-filing this credential under one. */
  websites: Website[];
  /** The team's vault folders. */
  folders: VaultFolder[];
  onFolderCreated: (folder: VaultFolder) => void;
  /** Teams this credential can be assigned to. Empty for a non-owner. */
  groups: SubTeam[];
  /** Manager or owner: may read and change this credential's group access. */
  canManageGroups: boolean;
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
    // "" means no website — the vault splits its two sections on this field
    // alone, so clearing it files the credential under Hosting & General.
    website_id: cred.website_id ?? "",
    folder_id: cred.folder_id ?? "",
  });
  const [deleteConfirm, setDeleteConfirm] = useState(false);
  const [deleting, setDeleting] = useState(false);

  // Which of the vault's two sections this credential is being filed under.
  // Kept as its own state rather than derived from `form.website_id`, because
  // "Website Login" with no site picked yet is a real intermediate state the
  // form has to be able to show — exactly as the create dialog holds it.
  const [section, setSection] = useState<Section>(
    cred.website_id ? "website" : "hosting",
  );

  // Team assignment. `grants` is the per-credential grants as the server has
  // them; `pickedTeams` is what the form currently shows. Saving diffs the two.
  // null means "not fetched yet".
  const [grants, setGrants] = useState<CredentialGroupGrant[] | null>(null);
  const [pickedTeams, setPickedTeams] = useState<Set<string>>(new Set());
  // Per team, whether it may see the password. One shared box used to cover
  // every ticked team and was pre-filled from the existing grants, so adding a
  // team to a login another team could already read handed the new team the
  // password too — the box looked "ticked by default". A team starts hidden.
  const [teamView, setTeamView] = useState<Record<string, boolean>>({});

  const showTeams = canManageGroups && groups.length > 0;

  useEffect(() => {
    if (!showTeams) return;
    let active = true;
    (async () => {
      const res = await fetch(`/api/credentials/${cred.id}/group-grants`);
      const data = res.ok ? await res.json().catch(() => []) : [];
      if (!active) return;
      const list: CredentialGroupGrant[] = Array.isArray(data) ? data : data?.data ?? [];
      // Only grants naming this credential are editable here. A team-wide or
      // type-wide rule is not something a single credential should silently
      // change.
      const mine = list.filter((g) => g.scope === "credential");
      setGrants(mine);
      setPickedTeams(new Set(mine.map((g) => g.sub_team)));
      setTeamView(Object.fromEntries(mine.map((g) => [g.sub_team, g.can_view_password])));
    })();
    return () => { active = false; };
  }, [cred.id, showTeams]);

  function toggleTeam(groupId: string) {
    const adding = !pickedTeams.has(groupId);
    setPickedTeams((prev) => {
      const next = new Set(prev);
      if (next.has(groupId)) next.delete(groupId);
      else next.add(groupId);
      return next;
    });
    // A freshly picked team starts on autofill-only.
    if (adding) setTeamView((v) => ({ ...v, [groupId]: false }));
  }

  /** Apply the team picker: remove dropped grants, add new ones. There is no
   *  PATCH for a grant, so a changed reveal flag is a delete plus a create. */
  async function saveTeams(): Promise<boolean> {
    if (!showTeams || grants === null) return true;
    const stale = grants.filter(
      (g) => !pickedTeams.has(g.sub_team) || g.can_view_password !== !!teamView[g.sub_team],
    );
    const keep = new Set(
      grants.filter((g) => !stale.includes(g)).map((g) => g.sub_team),
    );
    const toAdd = [...pickedTeams].filter((id) => !keep.has(id));

    let ok = true;
    for (const g of stale) {
      const res = await fetch(
        `/api/sub-teams/${g.sub_team}/credential-grants/${g.id}`,
        { method: "DELETE" },
      );
      if (!res.ok && res.status !== 204) ok = false;
    }
    for (const groupId of toAdd) {
      const res = await fetch(`/api/sub-teams/${groupId}/credential-grants`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          scope: "credential",
          credential: cred.id,
          can_view_password: !!teamView[groupId],
        }),
      });
      if (!res.ok) ok = false;
    }
    const res = await fetch(`/api/credentials/${cred.id}/group-grants`);
    const data = res.ok ? await res.json().catch(() => []) : [];
    const list: CredentialGroupGrant[] = Array.isArray(data) ? data : data?.data ?? [];
    setGrants(list.filter((g) => g.scope === "credential"));
    return ok;
  }

  const assignedTeamNames = (grants ?? [])
    .map((g) => g.sub_team_name ?? groups.find((x) => x.id === g.sub_team)?.name)
    .filter(Boolean) as string[];

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
    // "Website Login" with no site picked would save as `website_id: null` and
    // land back under Hosting & General — the move silently undone.
    if (section === "website" && !form.website_id) {
      toast({
        variant: "destructive",
        title: "Select a website",
        description: "A website login needs the site it belongs to, or switch it to Hosting / General.",
      });
      return;
    }
    setSaveLoading(true);
    try {
      const body: Record<string, string | null> = {
        label: form.label,
        credential_type: form.credential_type,
        login_url: form.login_url,
        // Always sent, including as an explicit null. The backend distinguishes
        // an absent key ("leave the link alone") from null ("unlink it"), which
        // is what makes moving a credential back to Hosting possible.
        website_id: section === "website" ? form.website_id : null,
      };
      if (form.username) body.username = form.username;
      if (form.password) body.password = form.password;
      if (form.notes !== undefined) body.notes = form.notes;
      // The folder fields are only sent when the backend reports them, so a
      // frontend deployed ahead of it never posts keys it would reject.
      if (cred.folder_id !== undefined) body.folder_id = form.folder_id || null;

      const res = await fetch(`/api/credentials/${cred.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        toast({
          variant: "destructive",
          title: "Failed to save",
          description: err?.errors?.[0]?.message ?? err?.detail ?? undefined,
        });
        return;
      }
      const updated: Credential = await res.json();
      const teamsOk = await saveTeams();
      toast(
        teamsOk
          ? { title: "Credential updated" }
          : {
              variant: "destructive",
              title: "Saved, but team access did not fully apply",
              description: "Check the teams on this credential and try again.",
            },
      );
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

  async function copy(text: string, label: string) {
    const ok = await copySecret(text);
    toast(
      ok
        ? { title: `${label} copied`, description: `Cleared from the clipboard in ${CLIPBOARD_CLEAR_SECONDS} seconds.` }
        : { variant: "destructive", title: "Could not copy" },
    );
  }

  // Follows the *form's* section, not the stored one. Gated on `cred.website_id`
  // this offered hosting types only to anything currently filed under Hosting,
  // so a login you had just pointed at a website still could not be called
  // "WordPress Admin" — the move and the type had to be two separate edits.
  const typeList = section === "website" ? WEBSITE_TYPES : HOSTING_TYPES;

  const NO_WEBSITE = "__none__";

  /** Move this credential between the vault's two sections.
   *
   * Moving can strand the type — "cPanel" is not on offer for a website
   * credential, and "WordPress Admin" is not on offer for a hosting one — so an
   * invalid one falls back to Custom / Other rather than leaving the Select
   * showing a value it cannot represent.
   *
   * Done here rather than in an effect watching `website_id`. The reset is a
   * consequence of this event, not of the state settling afterwards, so an
   * effect would be a second render deriving what this render already knows —
   * which is what `react-hooks/set-state-in-effect` objects to, and it is right
   * to. One update, one render, no window in which the pair is inconsistent.
   */
  function changeWebsite(nextWebsiteId: string) {
    setSection(nextWebsiteId ? "website" : "hosting");
    setForm((f) => {
      const list = nextWebsiteId ? WEBSITE_TYPES : HOSTING_TYPES;
      const typeSurvives = list.some((t) => t.value === f.credential_type);
      return {
        ...f,
        website_id: nextWebsiteId,
        credential_type: typeSurvives ? f.credential_type : "custom",
      };
    });
  }

  /** The toggle and the Website dropdown are two views of one decision, so
   *  either one moves both — the same pairing the create dialog uses. Choosing
   *  Hosting clears the website, which is what actually re-files the credential:
   *  the vault splits its two sections on `website_id` alone. */
  function changeSection(next: Section) {
    if (next === section) return;
    if (next === "hosting") { changeWebsite(""); return; }
    setSection("website");
    setForm((f) => {
      const typeSurvives = WEBSITE_TYPES.some((t) => t.value === f.credential_type);
      return { ...f, credential_type: typeSurvives ? f.credential_type : "custom" };
    });
  }

  return (
    <Dialog open onOpenChange={onClose}>
      {/* Capped at the viewport and laid out header / scrolling body / footer:
          the edit form is taller than a laptop screen, and as one fixed-size
          column it ran off the bottom with Save out of reach. */}
      <DialogContent className="sm:max-w-3xl max-h-[90vh] p-0 gap-0 overflow-hidden flex flex-col">
        <div className="flex items-center gap-4 border-b px-5 py-4 pr-12 shrink-0">
          {/* Same art as the grid card, so opening one doesn't swap a
              recognisable favicon for a generic padlock. */}
          <div
            className="flex h-14 w-14 shrink-0 items-center justify-center rounded-xl"
            style={{ backgroundColor: cardColor(cred) }}
          >
            <CardArt cred={cred} />
          </div>
          <div className="min-w-0 flex-1">
            {editMode ? (
              <>
                <DialogTitle className="sr-only">Edit {cred.label}</DialogTitle>
                <Input value={form.label} onChange={(e) => upd("label", e.target.value)} className="font-semibold text-base h-9" />
              </>
            ) : (
              <DialogTitle className="font-bold text-xl leading-tight truncate">{cred.label}</DialogTitle>
            )}
            <div className="flex items-center gap-2 mt-1.5 min-w-0">
              {editMode ? (
                <Select value={form.credential_type} onValueChange={(v) => upd("credential_type", v)}>
                  <SelectTrigger className="h-7 text-xs w-44"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {typeList.map((t) => (
                      <SelectItem key={t.value} value={t.value}>
                        <span className="flex items-center gap-2">
                          <span className="h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: dot(t.value) }} aria-hidden />
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
              <span className="text-xs text-muted-foreground truncate">{subtitle}</span>
            </div>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
          {!editMode && (
            <BrokenLoginControl cred={cred} canWrite={canWrite} onChanged={onUpdated} />
          )}

          {/* Two columns on a wide screen: where it is filed on the left, the
              login itself on the right. */}
          <div className="grid gap-x-8 gap-y-4 md:grid-cols-2">
          <div className="space-y-4 min-w-0">
          {/* Which section this credential lives in.
              The vault splits "Website Credentials" from "Hosting & General" on
              `website_id` alone, and nothing in the UI could set it — the edit
              form never sent the field, so every login saved without a website
              was stuck under Hosting for good. That is why a vault of 233 has
              229 in one section. */}
          <div>
            <Label className="text-xs text-muted-foreground uppercase tracking-wide">
              Website
            </Label>
            {editMode ? (
              <>
                {/* Same toggle, same words, as the create dialog. Editing could
                    only re-file a credential through the "Not a website login"
                    row inside the dropdown below — a section change hidden
                    inside a field that reads as a website picker. */}
                <div className="flex rounded-lg border p-1 gap-1 mt-1.5 mb-2">
                  <button
                    type="button"
                    onClick={() => changeSection("website")}
                    className={`flex-1 flex items-center justify-center gap-2 rounded-md py-1.5 text-xs font-medium transition-colors ${
                      section === "website" ? "bg-primary text-primary-foreground" : "hover:bg-muted text-muted-foreground"
                    }`}
                  >
                    <Globe className="h-3.5 w-3.5" />Website Login
                  </button>
                  <button
                    type="button"
                    onClick={() => changeSection("hosting")}
                    className={`flex-1 flex items-center justify-center gap-2 rounded-md py-1.5 text-xs font-medium transition-colors ${
                      section === "hosting" ? "bg-primary text-primary-foreground" : "hover:bg-muted text-muted-foreground"
                    }`}
                  >
                    <Server className="h-3.5 w-3.5" />Hosting / General
                  </button>
                </div>
                <Select
                  value={form.website_id || (section === "hosting" ? NO_WEBSITE : "")}
                  onValueChange={(v) => changeWebsite(v === NO_WEBSITE ? "" : v)}
                >
                  <SelectTrigger className="mt-1">
                    <SelectValue placeholder="Select website" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={NO_WEBSITE}>
                      Not a website login — keep in Hosting &amp; General
                    </SelectItem>
                    {websites.map((w) => (
                      <SelectItem key={w.id} value={w.id}>
                        {w.name || w.domain}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground mt-1.5">
                  {section === "website"
                    ? form.website_id
                      ? "Saving files this under Website Credentials."
                      : "Pick the website this login belongs to."
                    : "Saving keeps this in Hosting & General."}
                </p>
              </>
            ) : (
              <div className="flex items-center gap-2 mt-1">
                <span className="text-sm flex-1 truncate">
                  {cred.website_name ?? (
                    <span className="text-muted-foreground">
                      Not linked — filed under Hosting &amp; General
                    </span>
                  )}
                </span>
                {canWrite && !cred.website_id && (
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-7 px-2 text-xs shrink-0"
                    onClick={() => setEditMode(true)}
                    title="Link this login to a website and move it into Website Credentials"
                  >
                    <Globe className="h-3.5 w-3.5" />Move
                  </Button>
                )}
              </div>
            )}
          </div>

          {cred.folder_id !== undefined && (
            <div>
              <Label className="text-xs text-muted-foreground uppercase tracking-wide">Folder</Label>
              {editMode ? (
                <div className="mt-1">
                  <FolderPicker
                    value={form.folder_id}
                    folders={folders}
                    canCreate={canWrite}
                    onChange={(id) => upd("folder_id", id)}
                    onCreated={onFolderCreated}
                  />
                </div>
              ) : (
                <div className="flex items-center gap-2 mt-1 text-sm">
                  <Folder className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                  <span className="truncate">
                    {cred.folder_name ?? <span className="text-muted-foreground">No folder</span>}
                  </span>
                </div>
              )}
            </div>
          )}

          {fieldsFor(editMode ? form.credential_type : cred.credential_type).url !== null && (
          <div>
            <Label className="text-xs text-muted-foreground uppercase tracking-wide">
              {fieldsFor(editMode ? form.credential_type : cred.credential_type).url}
            </Label>
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
          )}

          {showTeams && (
            <div>
              <Label className="text-xs text-muted-foreground uppercase tracking-wide">
                Teams
              </Label>
              {editMode ? (
                <div className="mt-1.5 space-y-1.5">
                  {groups.map((g) => (
                    <div
                      key={g.id}
                      className="flex items-center gap-2.5 rounded-md border px-3 py-2 hover:bg-muted/50 transition-colors"
                    >
                      <label className="flex items-center gap-2.5 flex-1 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={pickedTeams.has(g.id)}
                          onChange={() => toggleTeam(g.id)}
                          className="h-4 w-4 accent-primary"
                        />
                        <span className="text-sm">{g.name}</span>
                      </label>
                      {pickedTeams.has(g.id) && (
                        <label
                          className="flex items-center gap-1.5 text-xs text-muted-foreground cursor-pointer"
                          title="Off: they can autofill this login with the extension but never see the password"
                        >
                          <input
                            type="checkbox"
                            checked={!!teamView[g.id]}
                            onChange={(e) => setTeamView((v) => ({ ...v, [g.id]: e.target.checked }))}
                            className="h-3.5 w-3.5 accent-primary"
                          />
                          See password
                        </label>
                      )}
                    </div>
                  ))}
                  <p className="text-xs text-muted-foreground pt-0.5">
                    Ticked teams can autofill this login with the extension.
                    &ldquo;See password&rdquo; also shows it to them in the
                    dashboard. Every use is logged.
                  </p>
                </div>
              ) : (
                <p className="text-sm mt-1">
                  {assignedTeamNames.length > 0 ? (
                    <span className="flex flex-wrap gap-1.5">
                      {assignedTeamNames.map((n) => (
                        <span
                          key={n}
                          className="text-xs font-medium px-2 py-0.5 rounded-full border bg-muted/50"
                        >
                          {n}
                        </span>
                      ))}
                    </span>
                  ) : (
                    <span className="text-muted-foreground">
                      No team. Only owners, managers, the creator and anyone
                      shared individually can see this.
                    </span>
                  )}
                </p>
              )}
            </div>
          )}

          </div>

          <div className="space-y-4 min-w-0">
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
              {fieldsFor(editMode ? form.credential_type : cred.credential_type).username !== null && (
              <div>
                <Label className="text-xs text-muted-foreground uppercase tracking-wide">
                  {fieldsFor(editMode ? form.credential_type : cred.credential_type).username}
                </Label>
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
              )}

              {fieldsFor(editMode ? form.credential_type : cred.credential_type).password !== null && (
              <div>
                <div className="flex items-center justify-between">
                  <Label className="text-xs text-muted-foreground uppercase tracking-wide">
                    {fieldsFor(editMode ? form.credential_type : cred.credential_type).password}
                  </Label>
                  {editMode && <GenerateButton onGenerate={(pw) => upd("password", pw)} />}
                </div>
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
              )}

              {(revealed?.notes || editMode) && (
                <div>
                  <Label className="text-xs text-muted-foreground uppercase tracking-wide">
                    {fieldsFor(editMode ? form.credential_type : cred.credential_type).notes}
                  </Label>
                  {editMode ? (
                    <Textarea
                      value={form.notes}
                      onChange={(e) => upd("notes", e.target.value)}
                      rows={form.credential_type === "secure_note" ? 8 : 2}
                      className="mt-1"
                    />
                  ) : revealed?.notes ? (
                    <p className="text-sm text-muted-foreground mt-1 whitespace-pre-wrap break-words">{revealed.notes}</p>
                  ) : null}
                </div>
              )}
            </div>
          )}

          {!editMode && fieldsFor(cred.credential_type).password !== null && (
            <PasswordHistorySection
              credId={cred.id}
              canWrite={canWrite}
              onRestored={() => { setRevealed(null); setShowPw(false); }}
            />
          )}

          {/* Managers and owners: who can see this. */}
          {!editMode && canWrite && <WhoHasAccessSection credId={cred.id} />}
          </div>
          </div>
        </div>

          {/* Pinned below the scrolling body so Save is always reachable. */}
          {canWrite && (
            <div className="flex items-center gap-2 border-t px-5 py-3 shrink-0 bg-background">
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
      </DialogContent>
    </Dialog>
  );
}

// ─── Add new credential modal ─────────────────────────────────────────────────

type Section = "website" | "hosting";

function AddItemModal({
  websites, folders, defaultFolder, onFolderCreated, defaultSection, groups, canManageGroups, onClose, onAdded,
}: {
  websites: Website[];
  folders: VaultFolder[];
  /** Pre-selected folder — the one the vault is currently showing. */
  defaultFolder: string;
  onFolderCreated: (folder: VaultFolder) => void;
  defaultSection: Section;
  /** Teams the new credential can be assigned to. Empty for a non-owner. */
  groups: SubTeam[];
  /** Manager or owner: may read and change this credential's group access. */
  canManageGroups: boolean;
  onClose: () => void;
  onAdded: (cred: Credential) => void;
}) {
  const { toast } = useToast();
  const [loading, setLoading] = useState(false);
  const [pickedTeams, setPickedTeams] = useState<Set<string>>(new Set());
  const [teamsCanView, setTeamsCanView] = useState(false);

  const showTeams = canManageGroups && groups.length > 0;

  function toggleTeam(groupId: string) {
    setPickedTeams((prev) => {
      const next = new Set(prev);
      if (next.has(groupId)) next.delete(groupId);
      else next.add(groupId);
      return next;
    });
  }
  const [section, setSection] = useState<Section>(defaultSection);
  const [form, setForm] = useState({
    website_id: "",
    credential_type: "",
    custom_type: "",
    login_url: "",
    username: "",
    password: "",
    notes: "",
    // Optional; blank falls back to the generated "<site> — <type>" label.
    name: "",
    folder_id: defaultFolder,
  });

  function upd(k: string, v: string) { setForm((f) => ({ ...f, [k]: v })); }

  const typeOptions = section === "website" ? WEBSITE_TYPES : HOSTING_TYPES;
  const isCustom = form.credential_type === "custom";
  const fields = fieldsFor(form.credential_type);
  const loginless = LOGINLESS_KINDS.has(form.credential_type);

  const NO_WEBSITE = "__none__";

  /** A type belonging to the other section cannot be represented by the Select
   *  it lands in — "cPanel" is not on offer for a website login, "WordPress
   *  Admin" is not on offer for a hosting one — so moving falls back to Custom
   *  / Other, the same rule the edit dialog applies. An unset type stays unset
   *  so the placeholder, and the platform-derived default below, still apply. */
  function typeFor(nextSection: Section, type: string): string {
    if (!type) return "";
    const list = nextSection === "website" ? WEBSITE_TYPES : HOSTING_TYPES;
    return list.some((t) => t.value === type) ? type : "custom";
  }

  // Selecting a website autofills as much as possible: the login URL derived
  // from its domain, and a sensible default type from its platform.
  function selectWebsite(id: string) {
    const site = websites.find((w) => w.id === id);
    const domain = (site?.domain || "").replace(/^https?:\/\//, "").replace(/\/$/, "");
    setSection("website");
    setForm((f) => {
      const platform = (site?.platform || "").toLowerCase();
      const kept = typeFor("website", f.credential_type);
      const type = kept || (platform === "wordpress" || !platform ? "wordpress" : "custom");
      const loginUrl = domain
        ? type === "wordpress" ? `https://${domain}/wp-admin` : `https://${domain}`
        : f.login_url;
      return { ...f, website_id: id, credential_type: type, login_url: loginUrl };
    });
  }

  /** The toggle and the Website dropdown are two views of one decision, so
   *  either one moves both. Clearing the website is what files the credential
   *  under Hosting & General — the vault splits its two sections on
   *  `website_id` alone. */
  function changeSection(next: Section) {
    setSection(next);
    setForm((f) => ({
      ...f,
      website_id: next === "website" ? f.website_id : "",
      credential_type: typeFor(next, f.credential_type),
    }));
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
    // A note or a server is not an "account".
    if (KIND_FIELDS[form.credential_type]) return typeName;
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
        label: form.name.trim() || derivedLabel(),
        credential_type: form.credential_type || (section === "website" ? "wordpress" : "siteground"),
        login_url: form.login_url,
        username: form.username,
        password: form.password,
        notes: form.notes,
        website_id: section === "website" ? form.website_id : null,
      };
      if (form.folder_id) body.folder_id = form.folder_id;

      const res = await fetch("/api/credentials", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        toast({
          variant: "destructive",
          title: "Failed to save credential",
          description: err?.errors?.[0]?.message ?? err?.detail ?? undefined,
        });
        return;
      }
      const created: Credential = await res.json();

      let teamsOk = true;
      for (const groupId of pickedTeams) {
        const grantRes = await fetch(`/api/sub-teams/${groupId}/credential-grants`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            scope: "credential",
            credential: created.id,
            can_view_password: teamsCanView,
          }),
        });
        if (!grantRes.ok) teamsOk = false;
      }
      toast(
        teamsOk
          ? { title: "Credential saved" }
          : {
              variant: "destructive",
              title: "Saved, but team access did not fully apply",
              description: "Open the credential and set its teams again.",
            },
      );
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
      <DialogContent className="sm:max-w-lg max-h-[90vh] overflow-y-auto">
        <DialogHeader><DialogTitle>New credential</DialogTitle></DialogHeader>

        {/* Section toggle */}
        <div className="flex rounded-lg border p-1 gap-1">
          <button
            type="button"
            onClick={() => changeSection("website")}
            className={`flex-1 flex items-center justify-center gap-2 rounded-md py-2 text-sm font-medium transition-colors ${
              section === "website" ? "bg-primary text-primary-foreground" : "hover:bg-muted text-muted-foreground"
            }`}
          >
            <Globe className="h-4 w-4" />Website Login
          </button>
          <button
            type="button"
            onClick={() => changeSection("hosting")}
            className={`flex-1 flex items-center justify-center gap-2 rounded-md py-2 text-sm font-medium transition-colors ${
              section === "hosting" ? "bg-primary text-primary-foreground" : "hover:bg-muted text-muted-foreground"
            }`}
          >
            <Server className="h-4 w-4" />Hosting / General
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-3">
          {/* Which section this credential lands in — shown on both sides of the
              toggle, and worded exactly as the edit dialog words it. The choice
              only ever existed as the toggle above, which reads as a filter on
              the form rather than a field being saved, so logins that belong to
              a website were routinely saved without one and filed under Hosting
              & General: 187 of 191, WordPress admins among them. */}
          <div className="space-y-1.5">
            <Label>Website</Label>
            <Select
              value={form.website_id || (section === "hosting" ? NO_WEBSITE : "")}
              onValueChange={(v) =>
                v === NO_WEBSITE ? changeSection("hosting") : selectWebsite(v)
              }
            >
              <SelectTrigger><SelectValue placeholder="Select website" /></SelectTrigger>
              <SelectContent>
                <SelectItem value={NO_WEBSITE}>
                  Not a website login — keep in Hosting &amp; General
                </SelectItem>
                {websites.map((w) => (
                  <SelectItem key={w.id} value={w.id}>{w.name || w.domain}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">
              {section === "website"
                ? form.website_id
                  ? "Saving files this under Website Credentials."
                  : "Pick the website this login belongs to."
                : "Saving keeps this in Hosting & General."}
            </p>
          </div>

          <div className="space-y-1.5">
            <Label>{section === "website" ? "CMS type" : "Type"}</Label>
            <Select
              value={form.credential_type}
              onValueChange={(v) => upd("credential_type", v)}
            >
              <SelectTrigger>
                <SelectValue placeholder={section === "website" ? "Select CMS type" : "Select type"} />
              </SelectTrigger>
              <SelectContent>
                {typeOptions.map((t) => (
                  <SelectItem key={t.value} value={t.value}>
                    <span className="flex items-center gap-2">
                      <span className="h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: dot(t.value) }} aria-hidden />
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
            <Label>Name <span className="text-muted-foreground">(optional)</span></Label>
            <Input
              placeholder={derivedLabel()}
              value={form.name}
              onChange={(e) => upd("name", e.target.value)}
              maxLength={200}
            />
          </div>

          {fields.url !== null && (
            <div className="space-y-1.5">
              <Label>{fields.url}</Label>
              <Input
                placeholder={section === "hosting" ? "https://my.siteground.com" : "https://example.com/wp-admin"}
                value={form.login_url}
                onChange={(e) => upd("login_url", e.target.value)}
              />
            </div>
          )}

          {(fields.username !== null || fields.password !== null) && (
            <div className="grid grid-cols-2 gap-3">
              {fields.username !== null && (
                <div className="space-y-1.5">
                  <Label>{fields.username}</Label>
                  <Input value={form.username} onChange={(e) => upd("username", e.target.value)} required={!loginless} />
                </div>
              )}
              {fields.password !== null && (
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between">
                    <Label>{fields.password}</Label>
                    <GenerateButton onGenerate={(pw) => upd("password", pw)} />
                  </div>
                  <PasswordInput value={form.password} onChange={(e) => upd("password", e.target.value)} autoComplete="new-password" required={!loginless} />
                </div>
              )}
            </div>
          )}

          <div className="space-y-1.5">
            <Label>Folder <span className="text-muted-foreground">(optional)</span></Label>
            <FolderPicker
              value={form.folder_id}
              folders={folders}
              canCreate
              onChange={(id) => upd("folder_id", id)}
              onCreated={onFolderCreated}
            />
          </div>

          <div className="space-y-1.5">
            <Label>{fields.notes} {form.credential_type !== "secure_note" && <span className="text-muted-foreground">(optional)</span>}</Label>
            <Textarea
              placeholder={form.credential_type === "secure_note" ? "Anything worth keeping encrypted…" : "Recovery email, account owner…"}
              value={form.notes}
              onChange={(e) => upd("notes", e.target.value)}
              rows={form.credential_type === "secure_note" ? 6 : 2}
              required={form.credential_type === "secure_note"}
            />
          </div>

          {showTeams && (
            <div className="space-y-1.5">
              <Label>Teams <span className="text-muted-foreground">(optional)</span></Label>
              <div className="space-y-1.5">
                {groups.map((g) => (
                  <label
                    key={g.id}
                    className="flex items-center gap-2.5 rounded-md border px-3 py-2 cursor-pointer hover:bg-muted/50 transition-colors"
                  >
                    <input
                      type="checkbox"
                      checked={pickedTeams.has(g.id)}
                      onChange={() => toggleTeam(g.id)}
                      className="h-4 w-4 accent-primary"
                    />
                    <span className="text-sm">{g.name}</span>
                  </label>
                ))}
                <label className="flex items-start gap-2.5 pt-1 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={teamsCanView}
                    onChange={(e) => setTeamsCanView(e.target.checked)}
                    className="mt-0.5 h-4 w-4 accent-primary"
                    disabled={pickedTeams.size === 0}
                  />
                  <span className="text-xs">
                    Let these teams see the password
                    <span className="block text-muted-foreground mt-0.5">
                      Off means they can autofill this login with the extension
                      but never see the password in the dashboard. Every autofill
                      use is logged against the person who used it.
                    </span>
                  </span>
                </label>
              </div>
            </div>
          )}

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

interface DevOption { id: string; email: string; name: string; role: string }


function ShareCredentialModal({ cred, teamId, onClose }: {
  cred: Credential;
  teamId: string | null;
  onClose: () => void;
}) {
  const { toast } = useToast();
  const [developers, setDevelopers] = useState<DevOption[]>([]);
  const [shares, setShares] = useState<CredentialShare[]>([]);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  // Off by default: sharing means "can use it"; seeing the password is a
  // separate, deliberate choice.
  const [canViewPw, setCanViewPw] = useState(false);
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
            .filter((m: { role: string }) => SHAREABLE_ROLES.has(m.role))
            .map((m: { role: string; user: { id: string; email: string; first_name: string; last_name: string } }) => ({
              id: m.user.id,
              email: m.user.email,
              name: `${m.user.first_name ?? ""} ${m.user.last_name ?? ""}`.trim(),
              role: m.role,
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
                <p className="text-sm font-semibold mb-2">Share with team members</p>
                {candidates.length === 0 ? (
                  <p className="text-xs text-muted-foreground">
                    {developers.length === 0
                      ? "No shareable members on this team yet. Owners and managers already see every credential."
                      : "Every shareable member already has access."}
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
                          <span className="flex items-baseline gap-1.5">
                            <span className="text-sm truncate">{d.name || d.email}</span>
                            <span className="shrink-0 text-[11px] text-muted-foreground">
                              {roleLabel(d.role)}
                            </span>
                          </span>
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
                      {s.expires_at && (
                        <Badge
                          variant="outline"
                          className="text-[10px] shrink-0"
                          title={new Date(s.expires_at).toLocaleString()}
                        >
                          until {new Date(s.expires_at).toLocaleDateString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
                        </Badge>
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

// ─── Bulk actions ─────────────────────────────────────────────────────────────

/** Runs `task` over `ids` a few at a time, collecting rather than throwing.
 *
 *  There is no bulk endpoint on purpose: one request per credential is what
 *  keeps `can_modify_credential` and the `CredentialAccessLog` row that a vault
 *  is supposed to leave behind. What that costs is a request per card, so the
 *  pool caps how many are open at once — a "select all" on a 191-item vault
 *  would otherwise open 191 sockets in one tick.
 *
 *  A failure is collected because a half-applied bulk action still has to say
 *  which half: the caller leaves the failures ticked so the user can see them
 *  and retry, instead of a toast that only counts.
 */
async function runPooled(
  ids: string[],
  task: (id: string) => Promise<boolean>,
  limit = 4,
): Promise<{ ok: string[]; failed: string[] }> {
  const ok: string[] = [];
  const failed: string[] = [];
  let next = 0;
  async function worker() {
    while (next < ids.length) {
      const id = ids[next++];
      let good = false;
      try {
        good = await task(id);
      } catch {
        good = false;
      }
      (good ? ok : failed).push(id);
    }
  }
  await Promise.all(Array.from({ length: Math.min(limit, ids.length) }, worker));
  return { ok, failed };
}

/** Clipboard write that reports whether it happened.
 *
 *  `navigator.clipboard` rejects outright on an insecure origin and can be
 *  refused by the browser, so a "Copy password" that assumed success would
 *  claim to have handed over a password the user has not got — and they would
 *  find out by pasting the wrong thing into a client's login form. Every
 *  caller toasts off the result. Cleared again after
 *  `CLIPBOARD_CLEAR_SECONDS`, like every other secret the vault copies.
 */
async function writeClipboard(text: string): Promise<boolean> {
  return copySecret(text);
}

/** The plaintext behind one card, or null if it could not be read.
 *
 *  Reveal is a POST rather than a GET because it is not a free read: the
 *  backend writes a `CredentialAccessLog` row for every call, which is what
 *  makes a vault a vault. Copying a password off the selection bar is exactly
 *  as logged as opening the card and pressing Reveal.
 */
async function revealCredential(id: string): Promise<RevealData | null> {
  try {
    const res = await fetch(`/api/credentials/${id}/reveal`, { method: "POST" });
    if (!res.ok) return null;
    return (await res.json()) as RevealData;
  } catch {
    return null;
  }
}

// Sentinels for the two selects: a shadcn SelectItem may not carry an empty
// value, and "leave this field alone" has to be distinguishable from "set this
// field to nothing" — the second is exactly how a login is moved back into
// Hosting & General.
const KEEP = "__keep__";
const CLEAR_WEBSITE = "__none__";

/** The list of labels a bulk action is about to act on.
 *
 *  Spelled out rather than summarised as a count because the selection outlives
 *  the search box: tick eight cards, type in the search, and the eight are
 *  still selected while the grid shows something else entirely. A count alone
 *  would be the user's only evidence of what is about to be deleted.
 */
function SelectionList({ creds }: { creds: Credential[] }) {
  return (
    <div className="max-h-40 overflow-y-auto rounded-lg border bg-muted/30 p-2 space-y-1">
      {creds.map((c) => (
        <div key={c.id} className="flex items-center gap-2 text-xs">
          <span
            className="h-2 w-2 shrink-0 rounded-full"
            style={{ backgroundColor: cardColor(c) }}
            aria-hidden
          />
          <span className="truncate font-medium">{c.label}</span>
          <span className="ml-auto shrink-0 text-muted-foreground">
            {c.website_name ?? typeLabel(c.credential_type)}
          </span>
        </div>
      ))}
    </div>
  );
}

/** Changes the two fields that mean the same thing on every selected card.
 *
 *  Deliberately not name, username, password or notes: those identify one
 *  login, and a bulk form that offered them would only ever be a way to
 *  overwrite twenty passwords with one. Type and website are the two fields
 *  that are genuinely shared — "these forty are all cPanel", "these six belong
 *  to the client we just onboarded" — and website is also what moves a card
 *  between the vault's two sections.
 */
function BulkEditDialog({ creds, websites, busy, onCancel, onApply }: {
  creds: Credential[];
  websites: Website[];
  busy: boolean;
  onCancel: () => void;
  onApply: (patch: { credential_type?: string; website_id?: string | null }) => void;
}) {
  const [type, setType] = useState<string>(KEEP);
  const [website, setWebsite] = useState<string>(KEEP);
  const nothingPicked = type === KEEP && website === KEEP;

  function apply() {
    const patch: { credential_type?: string; website_id?: string | null } = {};
    if (type !== KEEP) patch.credential_type = type;
    // Sent as an explicit null for "no website": the backend reads an absent
    // key as "leave the link alone", so null is the only way to unlink.
    if (website !== KEEP) patch.website_id = website === CLEAR_WEBSITE ? null : website;
    onApply(patch);
  }

  return (
    <Dialog open onOpenChange={() => !busy && onCancel()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            Edit {creds.length} credential{creds.length !== 1 ? "s" : ""}
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          <p className="text-sm text-muted-foreground">
            Only the fields you change here are written. Names, usernames,
            passwords and notes are left alone — those belong to one login each.
          </p>

          <div>
            <Label className="text-xs uppercase tracking-wide text-muted-foreground">Type</Label>
            <Select value={type} onValueChange={setType} disabled={busy}>
              <SelectTrigger className="mt-1"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value={KEEP}>Leave unchanged</SelectItem>
                {ALL_TYPES.map((t) => (
                  <SelectItem key={t.value} value={t.value}>
                    <span className="flex items-center gap-2">
                      <span
                        className="h-2 w-2 shrink-0 rounded-full"
                        style={{ backgroundColor: dot(t.value) }}
                        aria-hidden
                      />
                      {t.label}
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div>
            <Label className="text-xs uppercase tracking-wide text-muted-foreground">Website</Label>
            <Select value={website} onValueChange={setWebsite} disabled={busy}>
              <SelectTrigger className="mt-1"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value={KEEP}>Leave unchanged</SelectItem>
                <SelectItem value={CLEAR_WEBSITE}>
                  No website — move to Hosting &amp; General
                </SelectItem>
                {websites.map((w) => (
                  <SelectItem key={w.id} value={w.id}>{w.name || w.domain}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            {website !== KEEP && (
              <p className="mt-1.5 text-xs text-muted-foreground">
                {website === CLEAR_WEBSITE
                  ? "These move into Hosting & General."
                  : "These move into Website Credentials, filed under that site."}
              </p>
            )}
          </div>

          <SelectionList creds={creds} />
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onCancel} disabled={busy}>Cancel</Button>
          <Button onClick={apply} disabled={busy || nothingPicked}>
            {busy ? "Applying…" : `Apply to ${creds.length}`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** Grants the same people access to every selected card at once.
 *
 *  The per-card share modal has two halves — grant on the left, revoke on the
 *  right — and only the granting half survives a selection. Twenty cards have
 *  twenty different share lists, so a revoke control here would be asking to
 *  remove access that was given one card at a time, without showing whose.
 *  Revoking stays on the card it belongs to.
 *
 *  Granting is additive and re-applied: the endpoint upserts, so a member who
 *  already has some of these cards keeps them and has the password setting
 *  chosen here written across all of them. That is spelled out in the dialog
 *  rather than left to be discovered.
 */
function BulkShareDialog({ creds, teamId, busy, onCancel, onApply }: {
  creds: Credential[];
  teamId: string | null;
  busy: boolean;
  onCancel: () => void;
  onApply: (userIds: string[], canViewPassword: boolean) => void;
}) {
  const [developers, setDevelopers] = useState<DevOption[]>([]);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  // Off by default: sharing means "can use it"; seeing the password is a
  // separate, deliberate choice.
  const [canViewPw, setCanViewPw] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    async function load() {
      if (!teamId) { setLoading(false); return; }
      const res = await fetch(`/api/teams/${teamId}/members`);
      if (!active) return;
      if (res.ok) {
        const body = await res.json();
        const list = Array.isArray(body) ? body : body?.data ?? [];
        setDevelopers(
          list
            .filter((m: { role: string }) => SHAREABLE_ROLES.has(m.role))
            .map((m: { role: string; user: { id: string; email: string; first_name: string; last_name: string } }) => ({
              id: m.user.id,
              email: m.user.email,
              name: `${m.user.first_name ?? ""} ${m.user.last_name ?? ""}`.trim(),
              role: m.role,
            })),
        );
      }
      setLoading(false);
    }
    load().catch(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [teamId]);

  function toggle(id: string) {
    setPicked((prev) => {
      const next = new Set(prev);
      if (!next.delete(id)) next.add(id);
      return next;
    });
  }

  return (
    <Dialog open onOpenChange={() => !busy && onCancel()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            Share {creds.length} credential{creds.length !== 1 ? "s" : ""}
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          {loading ? (
            <p className="py-6 text-center text-sm text-muted-foreground">Loading team…</p>
          ) : developers.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No shareable members on this team yet. Owners and managers already
              see every credential in the vault.
            </p>
          ) : (
            <div className="space-y-1.5 max-h-44 overflow-y-auto pr-1">
              {developers.map((d) => (
                <label
                  key={d.id}
                  className="flex items-center gap-2.5 rounded-md border px-3 py-2 cursor-pointer hover:bg-muted/50 transition-colors"
                >
                  <input
                    type="checkbox"
                    checked={picked.has(d.id)}
                    onChange={() => toggle(d.id)}
                    disabled={busy}
                    className="h-4 w-4 accent-primary"
                  />
                  <span className="min-w-0">
                    <span className="flex items-baseline gap-1.5">
                      <span className="text-sm truncate">{d.name || d.email}</span>
                      <span className="shrink-0 text-[11px] text-muted-foreground">
                        {roleLabel(d.role)}
                      </span>
                    </span>
                    {d.name && (
                      <span className="block text-xs text-muted-foreground truncate">{d.email}</span>
                    )}
                  </span>
                </label>
              ))}
            </div>
          )}

          <label className="flex items-center gap-2.5 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={canViewPw}
              onChange={(e) => setCanViewPw(e.target.checked)}
              disabled={busy}
              className="h-4 w-4 accent-primary"
            />
            <span className="text-sm">Allow recipients to view the passwords</span>
          </label>
          <p className="text-xs text-muted-foreground -mt-2">
            {canViewPw
              ? "Applies to every card below, including any these people can already see."
              : "Recipients can autofill these logins, but the passwords stay hidden in the dashboard."}
          </p>

          <SelectionList creds={creds} />
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onCancel} disabled={busy}>Cancel</Button>
          <Button
            onClick={() => onApply([...picked], canViewPw)}
            disabled={busy || picked.size === 0}
          >
            {busy ? "Sharing…" : `Share ${creds.length} with ${picked.size}`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** Confirms a duplicate of every selected card.
 *
 *  Confirmed rather than fired straight off the menu because a clone is a
 *  write the user has to undo by hand: a mis-clicked "Clone" on forty cards
 *  leaves forty new logins to delete one at a time, and the copies sort right
 *  beside the originals.
 *
 *  A clone has to read the password to write it into the copy, so a card whose
 *  password the user may not view cannot be cloned — the alternative is a copy
 *  that looks complete and silently holds an empty password.
 */
function BulkCloneDialog({ creds, busy, onCancel, onConfirm }: {
  creds: Credential[];
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <Dialog open onOpenChange={() => !busy && onCancel()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            Clone {creds.length} credential{creds.length !== 1 ? "s" : ""}?
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <p className="text-sm text-muted-foreground">
            Each card below is copied whole — type, website, URL, username,
            password and notes — under the same name with{" "}
            <strong>(copy)</strong> on the end. Nothing is shared with the copy:
            the people you shared the original with do not get it.
          </p>
          <SelectionList creds={creds} />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onCancel} disabled={busy}>Cancel</Button>
          <Button onClick={onConfirm} disabled={busy}>
            {busy ? "Cloning…" : `Clone ${creds.length}`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ─── Import conflict dialog ───────────────────────────────────────────────────

/** Asks what to do with the CSV rows that are already in the vault.
 *
 * Shown only when the preview pass found an overlap, and only about the overlap:
 * the genuinely new rows are imported whichever button is pressed, so the choice
 * here is exactly "refresh these, leave these, or keep both".
 */
function ImportConflictsDialog({
  preview, busy, onCancel, onChoose,
}: {
  preview: ImportPreview;
  busy: boolean;
  onCancel: () => void;
  onChoose: (mode: ImportMode) => void;
}) {
  const { conflicts, duplicates, created, rows, repeats_in_file: repeats } = preview;
  const notShown = duplicates - conflicts.length;

  return (
    <Dialog open onOpenChange={(open) => { if (!open && !busy) onCancel(); }}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            {duplicates} of these logins {duplicates === 1 ? "is" : "are"} already in your vault
          </DialogTitle>
        </DialogHeader>

        <p className="text-sm text-muted-foreground">
          {rows} rows read — {created} new, {duplicates} already saved
          {repeats > 0 && `, ${repeats} repeated inside the file`}. The new ones are
          imported either way. Choose what happens to the {duplicates === 1 ? "match" : "matches"}:
        </p>

        <div className="max-h-72 overflow-y-auto rounded-md border divide-y">
          {conflicts.map((c) => (
            <div key={c.row} className="flex items-center justify-between gap-3 px-3 py-2">
              <div className="min-w-0">
                <p className="text-sm font-medium truncate">{c.label}</p>
                <p className="text-xs text-muted-foreground truncate">
                  {[c.username, c.website_name, c.login_url].filter(Boolean).join(" · ")}
                </p>
              </div>
              <span className="text-xs text-muted-foreground shrink-0 max-w-[40%] truncate">
                matches “{c.existing_label}”
              </span>
            </div>
          ))}
          {notShown > 0 && (
            <p className="px-3 py-2 text-xs text-muted-foreground">
              …and {notShown} more.
            </p>
          )}
        </div>

        <DialogFooter className="gap-2 sm:justify-between">
          <Button variant="ghost" onClick={onCancel} disabled={busy}>Cancel</Button>
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              onClick={() => onChoose("duplicate")}
              disabled={busy}
              title="Store these rows as separate entries — the vault will hold both copies"
            >
              Keep both
            </Button>
            <Button
              variant="outline"
              onClick={() => onChoose("skip")}
              disabled={busy}
              title="Import only the new rows and leave the saved logins untouched"
            >
              Skip them
            </Button>
            <Button
              onClick={() => onChoose("update")}
              disabled={busy}
              title="Refresh the saved logins with the password, name and URL from the CSV"
            >
              {busy ? "Importing…" : "Update existing"}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ─── Main vault client ─────────────────────────────────────────────────────────

export function CredentialsVaultClient({
  initialCredentials,
  websites,
  myRole,
  teamId = null,
  groups = [],
  initialFolders = [],
}: {
  initialCredentials: Credential[];
  websites: Website[];
  myRole: string;
  teamId?: string | null;
  /** Optional so a frontend deployed ahead of the backend still renders. */
  groups?: SubTeam[];
  /** The team's vault folders. Optional so an older backend still renders. */
  initialFolders?: VaultFolder[];
}) {
  const { toast } = useToast();
  const canWrite = myRole === "manager" || myRole === "owner";
  // Credential group access — reading the grants and changing them. Owner only:
  // a manager already reads every credential in the team, so what this gate
  // withholds is not what they can see but their ability to hand that reach to
  // other people. A team that needs cover while the owner is away names a
  // second owner (Team settings → Change role → Owner) instead.
  // Named for the permission rather than the role so the next person does not
  // have to infer which one the flag means — and because "owner" is now a set
  // of people, not one.
  const canManageGroups = myRole === "owner";

  const [credentials, setCredentials] = useState(initialCredentials);
  // Member roles ask for what they cannot see; owners and managers already see
  // everything, so the button would only ever say "nothing to request".
  const canRequest = SHAREABLE_ROLES.has(myRole);
  const [requestOpen, setRequestOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<SortKey>("recent");
  const [folders, setFolders] = useState<VaultFolder[]>(initialFolders);
  // ALL_FILTER shows everything; UNFILED what is in no folder.
  const [folderFilter, setFolderFilter] = useState<string>(ALL_FILTER);
  const [foldersOpen, setFoldersOpen] = useState(false);
  const [shareFolderOpen, setShareFolderOpen] = useState(false);

  async function reloadFolders(): Promise<VaultFolder[] | null> {
    const res = await fetch("/api/credentials/folders");
    if (!res.ok) return null;
    const data = await res.json().catch(() => null);
    if (!Array.isArray(data)) return null;
    setFolders(data);
    return data;
  }

  function addFolder(folder: VaultFolder) {
    setFolders((prev) =>
      [...prev, folder].sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" })),
    );
  }
  const [selected, setSelected] = useState<Credential | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Credential | null>(null);
  const [addSection, setAddSection] = useState<Section | null>(null);
  const [shareTarget, setShareTarget] = useState<Credential | null>(null);
  const [importing, setImporting] = useState(false);
  const [exporting, setExporting] = useState(false);
  // Multi-select. `selectMode` is the explicit toggle — on a touch screen there
  // is no hover, so the tick boxes need a way to be summoned that is not
  // "hover a card". A selection also keeps them visible on its own, so the
  // toggle is a starting gesture rather than a mode the user has to remember
  // to leave.
  const [selectMode, setSelectMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkEditOpen, setBulkEditOpen] = useState(false);
  const [bulkDeleteOpen, setBulkDeleteOpen] = useState(false);
  const [bulkShareOpen, setBulkShareOpen] = useState(false);
  const [bulkCloneOpen, setBulkCloneOpen] = useState(false);
  const [bulkBusy, setBulkBusy] = useState(false);
  // A file whose preview found rows the vault already holds — held here, with
  // nothing written, until the user says what to do with them.
  const [pendingImport, setPendingImport] = useState<{ file: File; preview: ImportPreview } | null>(null);

  // Built and downloaded in the browser — a static template needs no round trip.
  // The leading BOM is for Excel, which reads a BOM-less UTF-8 CSV as ANSI and
  // mangles the em dashes. The importer decodes utf-8-sig, so it strips cleanly.
  function handleDownloadSample() {
    const url = URL.createObjectURL(
      new Blob(["﻿" + SAMPLE_CSV], { type: "text/csv;charset=utf-8" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = "stacksmonitor-vault-sample.csv";
    link.click();
    URL.revokeObjectURL(url);
  }

  async function postImport(file: File, mode: "preview" | ImportMode) {
    const form = new FormData();
    form.append("file", file);
    form.append("mode", mode);
    const res = await fetch("/api/credentials/import", { method: "POST", body: form });
    const data = await res.json().catch(() => ({}));
    return { ok: res.ok, data };
  }

  // Two passes over the same file: the first only reports what it would do, and
  // the second — carrying the answer to the overlap — is the one that writes.
  // The file is re-sent rather than parked on the server between the two, so a
  // sheet of plaintext passwords never waits around in a cache.
  async function handleImportCsv(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setImporting(true);
    try {
      const { ok, data } = await postImport(file, "preview");
      if (!ok) {
        toast({ variant: "destructive", title: "Import failed", description: data?.detail ?? "Check the CSV and try again." });
        return;
      }
      if (!data.duplicates) {
        // Nothing already in the vault — there is nothing to ask about.
        await commitImport(file, "update");
        return;
      }
      setPendingImport({ file, preview: data as ImportPreview });
    } catch {
      toast({ variant: "destructive", title: "Network error" });
    } finally {
      setImporting(false);
    }
  }

  async function commitImport(file: File, mode: ImportMode) {
    setImporting(true);
    try {
      const { ok, data } = await postImport(file, mode);
      if (!ok) {
        toast({ variant: "destructive", title: "Import failed", description: data?.detail ?? "Check the CSV and try again." });
        return;
      }
      // Report against the row count so a short import is obvious straight
      // away rather than being discovered later as missing logins.
      const parts = [
        `${data.created ?? 0} added`,
        `${data.updated ?? 0} updated`,
        `${data.skipped ?? 0} skipped`,
      ];
      if (data.failed) parts.push(`${data.failed} failed`);
      // Group access is owner-only to write, so a manager's teams column is
      // reported back rather than silently dropped.
      if (data.grants_created) parts.push(`${data.grants_created} team grants added`);
      if (data.grants_ignored) parts.push(`${data.grants_ignored} team grants skipped (owner only)`);
      toast({
        title: `Import complete — ${data.rows ?? 0} rows read`,
        description: parts.join(", ") + ".",
      });
      setPendingImport(null);
      setTimeout(() => window.location.reload(), 1400);
    } catch {
      toast({ variant: "destructive", title: "Network error" });
    } finally {
      setImporting(false);
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
      link.download = "stacksmonitor-vault-export.csv";
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
    const q = search.toLowerCase();
    const match = (c: Credential) =>
      (!q ||
        c.label.toLowerCase().includes(q) ||
        (c.website_name ?? "").toLowerCase().includes(q) ||
        (c.folder_name ?? "").toLowerCase().includes(q) ||
        c.credential_type.toLowerCase().includes(q)) &&
      (folderFilter === ALL_FILTER ||
        (folderFilter === UNFILED ? !c.folder_id : c.folder_id === folderFilter));
    return {
      website: sortCredentials(websiteCreds.filter(match), sort),
      hosting: sortCredentials(hostingCreds.filter(match), sort),
    };
  }, [search, sort, websiteCreds, hostingCreds, folderFilter]);

  // Counts from the loaded vault, so they move as cards are filed.
  const folderCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const c of credentials) {
      const key = c.folder_id ?? UNFILED;
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
    return counts;
  }, [credentials]);
  const hasFolders = credentials.some((c) => c.folder_id !== undefined);
  const activeFolder = folders.find((f) => f.id === folderFilter) ?? null;
  const narrowed = !!search || folderFilter !== ALL_FILTER;

  function credSubtitle(c: Credential) {
    return c.website_name ?? typeLabel(c.credential_type);
  }

  function handleAdded(cred: Credential) {
    setCredentials((prev) => [cred, ...prev]);
  }

  function handleDeleted(id: string) {
    setCredentials((prev) => prev.filter((c) => c.id !== id));
    // A deleted card must not stay ticked, or the count in the selection bar
    // outlives the thing it is counting.
    setSelectedIds((prev) => {
      if (!prev.has(id)) return prev;
      const next = new Set(prev);
      next.delete(id);
      return next;
    });
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

  // ── Multi-select ──────────────────────────────────────────────────────────

  const selecting = selectMode || selectedIds.size > 0;
  // Ordered by the grid, not by tick order, so the confirmation list reads in
  // the same order as the cards behind it.
  const selectedCreds = useMemo(
    () => credentials.filter((c) => selectedIds.has(c.id)),
    [credentials, selectedIds],
  );

  function toggleSelected(id: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (!next.delete(id)) next.add(id);
      return next;
    });
  }

  // "All" means everything the search currently shows, not the whole vault —
  // selecting rows the user cannot see is how a filtered bulk delete takes out
  // the things that were filtered away.
  const visibleIds = useMemo(
    () => [...filtered.website, ...filtered.hosting].map((c) => c.id),
    [filtered],
  );
  const allVisibleSelected =
    visibleIds.length > 0 && visibleIds.every((id) => selectedIds.has(id));

  function clearSelection() {
    setSelectedIds(new Set());
    setSelectMode(false);
  }

  async function confirmBulkDelete() {
    setBulkBusy(true);
    const { ok, failed } = await runPooled([...selectedIds], async (id) => {
      const res = await fetch(`/api/credentials/${id}`, { method: "DELETE" });
      return res.ok || res.status === 204;
    });
    setBulkBusy(false);
    if (ok.length) {
      const gone = new Set(ok);
      setCredentials((prev) => prev.filter((c) => !gone.has(c.id)));
    }
    // Whatever failed stays ticked: retrying is then one click, and the user can
    // see which ones did not go rather than reading it off a number.
    setSelectedIds(new Set(failed));
    if (!failed.length) setSelectMode(false);
    setBulkDeleteOpen(false);
    toast(
      failed.length
        ? {
            variant: "destructive",
            title: `Deleted ${ok.length}, ${failed.length} failed`,
            description: "The ones that failed are still selected — you may not have permission to delete them.",
          }
        : { title: `Deleted ${ok.length} credential${ok.length !== 1 ? "s" : ""}` },
    );
  }

  async function applyBulkEdit(patch: { credential_type?: string; website_id?: string | null }) {
    setBulkBusy(true);
    const updates = new Map<string, Credential>();
    const { ok, failed } = await runPooled([...selectedIds], async (id) => {
      const res = await fetch(`/api/credentials/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      });
      if (!res.ok) return false;
      const updated: Credential | null = await res.json().catch(() => null);
      if (updated?.id) updates.set(updated.id, updated);
      return true;
    });
    setBulkBusy(false);
    if (updates.size) {
      setCredentials((prev) => prev.map((c) => updates.get(c.id) ?? c));
    }
    setSelectedIds(new Set(failed));
    if (!failed.length) setSelectMode(false);
    setBulkEditOpen(false);
    toast(
      failed.length
        ? {
            variant: "destructive",
            title: `Updated ${ok.length}, ${failed.length} failed`,
            description: "The ones that failed are still selected — you may not have permission to edit them.",
          }
        : { title: `Updated ${ok.length} credential${ok.length !== 1 ? "s" : ""}` },
    );
  }

  async function applyBulkShare(userIds: string[], canViewPassword: boolean) {
    if (userIds.length === 0) return;
    setBulkBusy(true);
    const { ok, failed } = await runPooled([...selectedIds], async (id) => {
      const res = await fetch(`/api/credentials/${id}/shares`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_ids: userIds, can_view_password: canViewPassword }),
      });
      return res.ok;
    });
    setBulkBusy(false);
    setSelectedIds(new Set(failed));
    if (!failed.length) setSelectMode(false);
    setBulkShareOpen(false);
    toast(
      failed.length
        ? {
            variant: "destructive",
            title: `Shared ${ok.length}, ${failed.length} failed`,
            description: "The ones that failed are still selected — you may not have permission to share them.",
          }
        : {
            title: `Shared ${ok.length} credential${ok.length !== 1 ? "s" : ""}`,
            description: `With ${userIds.length} team member${userIds.length !== 1 ? "s" : ""}.`,
          },
    );
  }

  async function confirmBulkClone() {
    setBulkBusy(true);
    const byId = new Map(credentials.map((c) => [c.id, c]));
    const created: Credential[] = [];
    const { ok, failed } = await runPooled([...selectedIds], async (id) => {
      const cred = byId.get(id);
      if (!cred) return false;
      // The list serializer never returns the secret half, so a copy has to be
      // read before it can be written — and a password this user may not view
      // cannot go into the copy. Failing is the honest answer: a clone with a
      // blank password looks complete and is not.
      const revealed = await revealCredential(id);
      if (!revealed || revealed.password_hidden) return false;
      const res = await fetch("/api/credentials", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          label: `${cred.label} (copy)`,
          credential_type: cred.credential_type,
          login_url: cred.login_url ?? "",
          website_id: cred.website_id,
          username: revealed.username,
          password: revealed.password,
          notes: revealed.notes,
        }),
      });
      if (!res.ok) return false;
      const copy: Credential | null = await res.json().catch(() => null);
      if (copy?.id) created.push(copy);
      return true;
    });
    setBulkBusy(false);
    if (created.length) setCredentials((prev) => [...created, ...prev]);
    // The originals stay ticked only where the clone failed, same as every
    // other bulk action — a clone that worked has nothing left to retry.
    setSelectedIds(new Set(failed));
    if (!failed.length) setSelectMode(false);
    setBulkCloneOpen(false);
    toast(
      failed.length
        ? {
            variant: "destructive",
            title: `Cloned ${ok.length}, ${failed.length} failed`,
            description: "The ones that failed are still selected — their passwords may be hidden from you.",
          }
        : { title: `Cloned ${ok.length} credential${ok.length !== 1 ? "s" : ""}` },
    );
  }

  // Moving a selection between folders straight off the menu rather than
  // through the edit dialog: the folder is what the submenu just named, so a
  // form asking for it again would be a second click for nothing. It is the
  // same write, and the same toast reports it.
  function moveSelectedTo(websiteId: string | null) {
    void applyBulkEdit({ website_id: websiteId });
  }

  // ── Actions on one card ───────────────────────────────────────────────────
  // Copying a username, a password or a URL — and opening it — are one-card
  // jobs: the clipboard holds one thing, and a "Go to URL" across twenty cards
  // is twenty pop-ups, nineteen of which the browser blocks. They live in the
  // same menu because that is the menu a selection puts in front of the user,
  // and they are disabled with the reason named above them rather than hidden,
  // so the menu does not change shape as cards are ticked.
  const onlyCred = selectedCreds.length === 1 ? selectedCreds[0] : null;
  const noneSelected = selectedIds.size === 0;

  async function copyFromOnly(field: "username" | "password") {
    if (!onlyCred) return;
    const data = await revealCredential(onlyCred.id);
    if (!data) {
      toast({
        variant: "destructive",
        title: "Cannot reveal credential",
        description: `You may not have permission to read ${onlyCred.label}.`,
      });
      return;
    }
    if (field === "password" && data.password_hidden) {
      toast({
        variant: "destructive",
        title: "Password hidden",
        description: `Your access to ${onlyCred.label} does not include viewing its password.`,
      });
      return;
    }
    const value = field === "password" ? data.password : data.username;
    if (!value) {
      toast({ title: `No ${field} saved`, description: `${onlyCred.label} has no ${field} stored.` });
      return;
    }
    // The write lands after a network round trip, which some browsers refuse
    // as being outside the click that started it — hence the honest failure
    // branch rather than a toast that always claims success.
    toast(
      (await writeClipboard(value))
        ? {
            title: `${field === "password" ? "Password" : "Username"} copied`,
            description: onlyCred.label,
          }
        : {
            variant: "destructive",
            title: "Could not copy",
            description: "The browser refused access to the clipboard.",
          },
    );
  }

  async function copyOnlyUrl() {
    if (!onlyCred?.login_url) return;
    toast(
      (await writeClipboard(onlyCred.login_url))
        ? { title: "URL copied", description: onlyCred.login_url }
        : {
            variant: "destructive",
            title: "Could not copy",
            description: "The browser refused access to the clipboard.",
          },
    );
  }

  function openOnlyUrl() {
    if (!onlyCred?.login_url) return;
    window.open(onlyCred.login_url, "_blank", "noopener,noreferrer");
  }

  const totalCreds = credentials.length;

  return (
    <div className="p-8 space-y-8">
      {/* Page header */}
      <div className="flex items-start justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Vault</h1>
          <p className="text-muted-foreground mt-1">
            {totalCreds > 0
              ? `${totalCreds} credential${totalCreds !== 1 ? "s" : ""} — encrypted and secured`
              : "Securely store all your logins in one place"}
          </p>
        </div>
        {canWrite && (
          <div className="flex items-center gap-2 flex-wrap">
            {/* The three CSV actions are one job, so they read as one control
                instead of three loose buttons competing with "New item". */}
            <div className="flex items-center rounded-lg border bg-card p-1 shadow-sm">
              <Button
                variant="ghost"
                size="sm"
                className="h-8 px-2.5"
                onClick={handleDownloadSample}
                title="Download a CSV template with the columns the importer expects"
              >
                <FileDown className="h-4 w-4" />Sample
              </Button>
              <span aria-hidden className="mx-1 h-5 w-px bg-border" />
              <label className="cursor-pointer">
                <input type="file" accept=".csv" className="hidden" onChange={handleImportCsv} disabled={importing} />
                <Button variant="ghost" size="sm" className="h-8 px-2.5" asChild>
                  <span><Download className="h-4 w-4" />{importing ? "Importing…" : "Import"}</span>
                </Button>
              </label>
              <span aria-hidden className="mx-1 h-5 w-px bg-border" />
              <Button
                variant="ghost"
                size="sm"
                className="h-8 px-2.5"
                onClick={handleExportCsv}
                disabled={exporting || totalCreds === 0}
                title="Download the whole vault as a CSV — includes plaintext passwords"
              >
                <Upload className="h-4 w-4" />{exporting ? "Exporting…" : "Export"}
              </Button>
            </div>
            <Button variant="outline" size="sm" className="h-10 px-4" asChild>
              <a href="/logs?view=credentials" title="Who revealed, copied, changed or shared what — across every client">
                <ScrollText className="h-4 w-4" />Vault activity
              </a>
            </Button>
            <Button size="sm" className="h-10 px-4" onClick={() => setAddSection("hosting")}>
              <Plus className="h-4 w-4" />New item
            </Button>
          </div>
        )}
        {canRequest && (
          <Button
            variant="outline"
            size="sm"
            className="h-10 px-4"
            onClick={() => setRequestOpen(true)}
            title="Ask for a login you cannot see"
          >
            <KeyRound className="h-4 w-4" />Request access
          </Button>
        )}
      </div>

      {/* Requests on credentials this person may share — owners, managers, and
          any creator. Renders nothing when there are none. */}
      <AccessRequestsPanel />

      {/* Search + sort — pinned to the top of the viewport, because the vault is
          a wall of cards several screens tall and the controls that narrow it
          were only reachable by scrolling back up. The page itself is what
          scrolls (the dashboard layout puts no overflow container in the way),
          so `sticky top-0` has something to stick to. Negative margins undo the
          page's p-8 so the bar spans the full width and its background actually
          covers the cards passing underneath. */}
      {totalCreds > 0 && (
        <div className="sticky top-0 z-30 -mx-8 border-b bg-background/95 px-8 py-4 backdrop-blur supports-[backdrop-filter]:bg-background/80">
          <div className="flex flex-wrap items-center gap-3">
            <div className="relative w-full max-w-sm">
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
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-muted-foreground whitespace-nowrap">Sort By:</span>
              <Select value={sort} onValueChange={(v) => setSort(v as SortKey)}>
                <SelectTrigger className="h-10 w-[176px]" aria-label="Sort credentials">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {SORT_OPTIONS.map((o) => (
                    <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            {canWrite && (
              <Button
                variant={selecting ? "secondary" : "outline"}
                size="sm"
                className="h-10 ml-auto"
                aria-pressed={selecting}
                onClick={() => (selecting ? clearSelection() : setSelectMode(true))}
                title="Pick several credentials to edit, move, share, clone or delete at once"
              >
                <CheckSquare className="h-4 w-4" />
                {selecting ? "Done" : "Select"}
              </Button>
            )}
          </div>

          {/* Folders, LastPass-style: one click narrows the vault to a folder. */}
          {hasFolders && (folders.length > 0 || canWrite) && (
            <div className="mt-3 flex flex-wrap items-center gap-1.5">
              {[
                { id: ALL_FILTER, name: "All", count: credentials.length },
                ...folders
                  .map((f) => ({ id: f.id, name: f.name, count: folderCounts.get(f.id) ?? 0 }))
                  // A member sees only the folders that hold something for them
                  // — e.g. the one a manager shared with them.
                  .filter((chip) => canWrite || chip.count > 0),
                { id: UNFILED, name: "No folder", count: folderCounts.get(UNFILED) ?? 0 },
              ].map((chip) => (
                <button
                  key={chip.id}
                  type="button"
                  onClick={() => setFolderFilter(chip.id)}
                  aria-pressed={folderFilter === chip.id}
                  className={`flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
                    folderFilter === chip.id
                      ? "bg-primary text-primary-foreground border-primary"
                      : "bg-card hover:bg-muted text-muted-foreground"
                  }`}
                >
                  {chip.id !== ALL_FILTER && chip.id !== UNFILED && <Folder className="h-3 w-3" />}
                  {chip.name}
                  <span className="opacity-70">{chip.count}</span>
                </button>
              ))}
              {canWrite && (
                <button
                  type="button"
                  onClick={() => setFoldersOpen(true)}
                  className="ml-1 text-xs font-medium text-primary hover:underline"
                >
                  Manage folders
                </button>
              )}
            </div>
          )}

          {/* With a folder open: hand the whole folder to someone in one step,
              or pick some of its logins and share those. */}
          {canWrite && activeFolder && !selecting && (
            <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
              <Button size="sm" className="h-8" onClick={() => setShareFolderOpen(true)}>
                <Share2 className="h-3.5 w-3.5" />Share folder
              </Button>
              <Button size="sm" variant="outline" className="h-8" onClick={() => setSelectMode(true)}>
                <CheckSquare className="h-3.5 w-3.5" />Select logins to share
              </Button>
              <span className="text-muted-foreground">
                {activeFolder.members?.length
                  ? `Shared with ${activeFolder.members.map((m) => m.name).join(", ")}`
                  : "Not shared with anyone yet"}
              </span>
            </div>
          )}

          {/* The bulk bar lives in the same sticky element as the search, so it
              stays reachable while the user scrolls a vault several screens
              tall picking cards — which is the only way a selection of any size
              gets made. */}
          {canWrite && selecting && (
            <div className="mt-3 flex flex-wrap items-center gap-3 border-t pt-3">
              <span className="text-sm font-medium">
                {bulkBusy
                  ? "Working…"
                  : selectedIds.size === 0
                    ? "Pick the cards you want to change"
                    : `${selectedIds.size} item${selectedIds.size !== 1 ? "s" : ""} selected`}
              </span>
              {/* One "Actions" menu rather than a row of loose buttons: the bar
                  sits above the grid on every scroll while cards are being
                  picked, and a destructive button parked there permanently is
                  one mis-click from deleting the selection. */}
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="outline" size="sm" className="h-8">
                    Actions
                    <ChevronDown className="h-3.5 w-3.5" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start" className="w-60">
                  {visibleIds.length > 0 && (
                    <DropdownMenuItem
                      className="gap-2"
                      onClick={() =>
                        setSelectedIds((prev) => {
                          const next = new Set(prev);
                          if (allVisibleSelected) visibleIds.forEach((id) => next.delete(id));
                          else visibleIds.forEach((id) => next.add(id));
                          return next;
                        })
                      }
                    >
                      <CheckSquare className="h-3.5 w-3.5" />
                      {allVisibleSelected
                        ? `Deselect these ${visibleIds.length}`
                        : `Select all ${visibleIds.length}${search ? " shown" : ""}`}
                    </DropdownMenuItem>
                  )}
                  <DropdownMenuSeparator />

                  <DropdownMenuItem
                    className="gap-2"
                    disabled={noneSelected || bulkBusy}
                    onClick={() => (onlyCred ? setSelected(onlyCred) : setBulkEditOpen(true))}
                  >
                    <Pencil className="h-3.5 w-3.5" />
                    {onlyCred ? "Edit this card…" : "Edit selected…"}
                  </DropdownMenuItem>

                  {/* The vault stores no folder of its own: a card's folder is
                      the website it is filed under, and "no website" is the
                      Hosting & General shelf. So the submenu is the website
                      list, and picking one is the move. */}
                  <DropdownMenuSub>
                    <DropdownMenuSubTrigger
                      className="gap-2"
                      disabled={noneSelected || bulkBusy}
                    >
                      <FolderInput className="h-3.5 w-3.5" />
                      Move to folder
                    </DropdownMenuSubTrigger>
                    <DropdownMenuSubContent className="max-h-72 w-64 overflow-y-auto">
                      <DropdownMenuItem className="gap-2" onClick={() => moveSelectedTo(null)}>
                        <Server className="h-3.5 w-3.5 shrink-0" />
                        Hosting &amp; General
                      </DropdownMenuItem>
                      {websites.length > 0 && <DropdownMenuSeparator />}
                      {websites.length === 0 ? (
                        <DropdownMenuLabel className="text-[11px] font-normal text-muted-foreground">
                          No websites on this team yet.
                        </DropdownMenuLabel>
                      ) : (
                        websites.map((w) => (
                          <DropdownMenuItem
                            key={w.id}
                            className="gap-2"
                            onClick={() => moveSelectedTo(w.id)}
                          >
                            <Globe className="h-3.5 w-3.5 shrink-0" />
                            <span className="truncate">{w.name || w.domain}</span>
                          </DropdownMenuItem>
                        ))
                      )}
                    </DropdownMenuSubContent>
                  </DropdownMenuSub>

                  <DropdownMenuItem
                    className="gap-2"
                    disabled={noneSelected || bulkBusy}
                    onClick={() => setBulkShareOpen(true)}
                  >
                    <Share2 className="h-3.5 w-3.5" />
                    Share selected…
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    className="gap-2"
                    disabled={noneSelected || bulkBusy}
                    onClick={() => setBulkCloneOpen(true)}
                  >
                    <CopyPlus className="h-3.5 w-3.5" />
                    Clone selected…
                  </DropdownMenuItem>

                  <DropdownMenuSeparator />
                  {/* Named rather than left as four greyed rows: a disabled
                      item with no reason beside it reads as broken. */}
                  <DropdownMenuLabel className="text-[11px] font-normal text-muted-foreground">
                    {onlyCred ? (
                      <span className="block truncate">{onlyCred.label}</span>
                    ) : (
                      "Tick one card on its own for these"
                    )}
                  </DropdownMenuLabel>
                  <DropdownMenuItem
                    className="gap-2"
                    disabled={!onlyCred}
                    onClick={() => void copyFromOnly("username")}
                  >
                    <User className="h-3.5 w-3.5" />
                    Copy username
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    className="gap-2"
                    disabled={!onlyCred}
                    onClick={() => void copyFromOnly("password")}
                  >
                    <KeyRound className="h-3.5 w-3.5" />
                    Copy password
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    className="gap-2"
                    disabled={!onlyCred?.login_url}
                    onClick={() => void copyOnlyUrl()}
                  >
                    <Link2 className="h-3.5 w-3.5" />
                    Copy URL
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    className="gap-2"
                    disabled={!onlyCred?.login_url}
                    onClick={openOnlyUrl}
                  >
                    <ExternalLink className="h-3.5 w-3.5" />
                    Go to URL
                  </DropdownMenuItem>

                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    disabled={noneSelected || bulkBusy}
                    onClick={() => setBulkDeleteOpen(true)}
                    className="gap-2 text-destructive focus:text-destructive"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                    Delete selected…
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem className="gap-2" onClick={clearSelection}>
                    <X className="h-3.5 w-3.5" />
                    Clear selection
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
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
            label={narrowed ? "No website credentials match your search or filters." : "No website logins saved yet — add a WordPress admin, Wix, Shopify, or other site login."}
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
                selectable={canWrite}
                selecting={selecting}
                isSelected={selectedIds.has(cred.id)}
                onToggleSelect={() => toggleSelected(cred.id)}
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
            label={narrowed ? "No hosting credentials match your search or filters." : "No hosting or general logins saved yet — add SiteGround, cPanel, GoDaddy, Cloudflare, and more."}
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
                selectable={canWrite}
                selecting={selecting}
                isSelected={selectedIds.has(cred.id)}
                onToggleSelect={() => toggleSelected(cred.id)}
                onView={() => setSelected(cred)}
                onDelete={() => setDeleteTarget(cred)}
                onShare={() => setShareTarget(cred)}
              />
            ))}
          </div>
        )}
      </section>

      {/* Modals */}
      {requestOpen && <RequestAccessDialog onClose={() => setRequestOpen(false)} />}
      {shareFolderOpen && activeFolder && (
        <ShareFolderDialog
          folder={activeFolder}
          teamId={teamId}
          onChanged={async () => { await reloadFolders(); }}
          onClose={() => setShareFolderOpen(false)}
        />
      )}
      {foldersOpen && (
        <FolderManagerDialog
          folders={folders}
          groups={groups}
          canShare={canManageGroups}
          onChanged={async () => {
            const next = await reloadFolders();
            if (!next) return;
            // A rename or delete changes what cards say. Patched locally: the
            // list endpoint pages at 25, so refetching it would drop cards.
            const byId = new Map(next.map((f) => [f.id, f.name]));
            setCredentials((prev) => prev.map((c) => {
              if (!c.folder_id) return c;
              const name = byId.get(c.folder_id);
              return name === undefined
                ? { ...c, folder_id: null, folder_name: null }
                : { ...c, folder_name: name };
            }));
            if (folderFilter !== ALL_FILTER && folderFilter !== UNFILED && !byId.has(folderFilter)) {
              setFolderFilter(ALL_FILTER);
            }
          }}
          onClose={() => setFoldersOpen(false)}
        />
      )}
      {selected && (
        <CredentialModal
          cred={selected}
          subtitle={credSubtitle(selected)}
          canWrite={canWrite}
          websites={websites}
          folders={folders}
          onFolderCreated={addFolder}
          groups={groups}
          canManageGroups={canManageGroups}
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

      {bulkEditOpen && selectedCreds.length > 0 && (
        <BulkEditDialog
          creds={selectedCreds}
          websites={websites}
          busy={bulkBusy}
          onCancel={() => setBulkEditOpen(false)}
          onApply={applyBulkEdit}
        />
      )}

      {bulkShareOpen && selectedCreds.length > 0 && (
        <BulkShareDialog
          creds={selectedCreds}
          teamId={teamId}
          busy={bulkBusy}
          onCancel={() => setBulkShareOpen(false)}
          onApply={applyBulkShare}
        />
      )}

      {bulkCloneOpen && selectedCreds.length > 0 && (
        <BulkCloneDialog
          creds={selectedCreds}
          busy={bulkBusy}
          onCancel={() => setBulkCloneOpen(false)}
          onConfirm={confirmBulkClone}
        />
      )}

      {bulkDeleteOpen && selectedCreds.length > 0 && (
        <Dialog open onOpenChange={() => !bulkBusy && setBulkDeleteOpen(false)}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>
                Delete {selectedCreds.length} credential{selectedCreds.length !== 1 ? "s" : ""}?
              </DialogTitle>
            </DialogHeader>
            <div className="space-y-3">
              <p className="text-sm text-muted-foreground">
                This permanently deletes every login listed below, along with its
                stored password. It cannot be undone.
              </p>
              <SelectionList creds={selectedCreds} />
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setBulkDeleteOpen(false)} disabled={bulkBusy}>
                Cancel
              </Button>
              <Button variant="destructive" onClick={confirmBulkDelete} disabled={bulkBusy}>
                {bulkBusy ? "Deleting…" : `Delete ${selectedCreds.length}`}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}

      {pendingImport && (
        <ImportConflictsDialog
          preview={pendingImport.preview}
          busy={importing}
          onCancel={() => setPendingImport(null)}
          onChoose={(mode) => commitImport(pendingImport.file, mode)}
        />
      )}

      {canWrite && addSection && (
        <AddItemModal
          websites={websites}
          folders={folders}
          defaultFolder={folderFilter === ALL_FILTER || folderFilter === UNFILED ? "" : folderFilter}
          onFolderCreated={addFolder}
          defaultSection={addSection}
          groups={groups}
          canManageGroups={canManageGroups}
          onClose={() => setAddSection(null)}
          onAdded={handleAdded}
        />
      )}
    </div>
  );
}
