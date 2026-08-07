"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import Link from "next/link";
import {
  Upload, Plus, ExternalLink, Download, ChevronLeft, ChevronRight,
  Check, Minus, Pencil, Search, Users,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  DEPARTMENT_LABELS, DEPARTMENT_OPTIONS, TIER_OPTIONS,
  HOSTING_OPTIONS, ACCESS_LEVEL_OPTIONS,
} from "@/lib/client-fields";
import { cn } from "@/lib/utils";
import type { ClientRecord } from "@/app/(dashboard)/clients/page";

const HOSTING_LABELS: Record<string, string> = {
  wpengine: "WPEngine", siteground: "SiteGround", cloudways: "Cloudways",
  bluehost: "Bluehost", godaddy: "GoDaddy", squarespace: "Squarespace",
  wix: "Wix", shopify: "Shopify", other: "Other", "": "—",
};

const ACCESS_LEVEL_TABLE_LABELS: Record<string, string> = {
  full_admin: "Full admin", delegate: "Delegate", none: "No access",
  not_working: "Not working",
};

/** Keep in step with the header/body cell counts below — it drives the colSpan
 *  on the loading and empty rows, which otherwise stop spanning the table. */
const COLUMN_COUNT = 11;

/* ---------------------------------------------------------------------------
   Sticky geometry.

   Three sticky layers overlap in this table, so the z-order is explicit: the
   corner cells (pinned both ways) sit above the header rows, which sit above
   the pinned first column, or they overlap during diagonal scrolling. Every
   sticky cell needs an opaque background or rows show through underneath.

   The header is two rows — labels, then filter controls — so the labels align
   across columns instead of each cell sizing itself around whatever control it
   carries. The filter row pins directly under the label row, hence top-9
   matching the label row's h-9.
   --------------------------------------------------------------------------- */
const CLIENT_COL = "min-w-[264px] w-[264px] max-w-[264px]";
/** Table auto-layout treats a cell's `width` as a suggestion and grows the
 *  column to fit its min-content, and `truncate` sets white-space:nowrap — so a
 *  long client name would widen the whole pinned column rather than ellipsing.
 *  A fixed-width inner box is what actually caps it. */
const CLIENT_TEXT_COL = "w-[192px]";
/** Hairline down the right edge of the pinned column. Drawn as a pseudo-element
 *  rather than a border because collapsed table borders don't paint reliably on
 *  sticky cells. */
const PIN_EDGE = "after:absolute after:inset-y-0 after:right-0 after:w-px after:bg-border";

const HEAD_CELL =
  "h-9 bg-muted px-4 align-middle whitespace-nowrap text-[11px] font-semibold uppercase tracking-wider text-muted-foreground";
const HEAD_LABEL = `sticky top-0 z-20 ${HEAD_CELL}`;
const HEAD_LABEL_PINNED = `sticky left-0 top-0 z-30 ${HEAD_CELL} ${CLIENT_COL} ${PIN_EDGE}`;

/** Inset shadow rather than border-b for the same collapsed-border reason. */
const FILTER_CELL =
  "h-12 bg-muted px-4 py-0 align-middle shadow-[inset_0_-1px_0_var(--border)]";
const FILTER_ROW = `sticky top-9 z-20 ${FILTER_CELL}`;
const FILTER_ROW_PINNED = `sticky left-0 top-9 z-30 ${FILTER_CELL} ${CLIENT_COL} ${PIN_EDGE}`;

/** Body cells inherit the row's background so the pinned column picks up the
 *  zebra stripe and the hover tint instead of punching a flat card-coloured
 *  hole through them. */
const BODY_PINNED = `sticky left-0 z-10 bg-inherit ${CLIENT_COL} ${PIN_EDGE}`;

/* --------------------------------------------------------------------------- */

type Tone = "neutral" | "violet" | "green" | "amber" | "red" | "slate" | "orange";

const TONES: Record<Tone, string> = {
  neutral: "bg-muted text-muted-foreground ring-border",
  violet: "bg-violet-50 text-violet-700 ring-violet-200 dark:bg-violet-500/15 dark:text-violet-300 dark:ring-violet-500/25",
  green: "bg-emerald-50 text-emerald-700 ring-emerald-200 dark:bg-emerald-500/15 dark:text-emerald-300 dark:ring-emerald-500/25",
  amber: "bg-amber-50 text-amber-800 ring-amber-200 dark:bg-amber-500/15 dark:text-amber-300 dark:ring-amber-500/25",
  red: "bg-red-50 text-red-700 ring-red-200 dark:bg-red-500/15 dark:text-red-300 dark:ring-red-500/25",
  slate: "bg-slate-100 text-slate-700 ring-slate-200 dark:bg-slate-400/15 dark:text-slate-300 dark:ring-slate-400/25",
  orange: "bg-orange-50 text-orange-800 ring-orange-200 dark:bg-orange-500/15 dark:text-orange-300 dark:ring-orange-500/25",
};

/** Two pill shapes carry two different kinds of value, so the shape itself is
 *  readable at a glance: rounded-full = a state the client is currently in
 *  (status, access), rounded-md = a category it belongs to (package,
 *  department). */
function Pill({ tone = "neutral", shape = "tag", className, children }: {
  tone?: Tone;
  shape?: "tag" | "state";
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center whitespace-nowrap px-2 py-0.5 text-xs font-medium ring-1 ring-inset",
        shape === "state" ? "rounded-full" : "rounded-md",
        TONES[tone],
        className
      )}
    >
      {children}
    </span>
  );
}

/** One dash for every empty cell, quiet enough that a sparse row reads as
 *  sparse rather than as a wall of punctuation. */
function Dash() {
  return <span className="text-muted-foreground/40">—</span>;
}

const TIER_TONE: Record<string, Tone> = { gold: "amber", silver: "slate", bronze: "orange" };

const ACCESS_TONE: Record<string, Tone> = {
  full_admin: "green", delegate: "amber", not_working: "red", none: "neutral",
};

const STATUS_TONE: Record<string, Tone> = {
  active: "green", paused: "amber", offboarded: "neutral",
};

/** Deterministic tint for the client monogram — the same client keeps the same
 *  colour across pages, which is what makes it useful for finding a row again
 *  after scrolling sideways. */
const MONOGRAM_TONES = [
  "bg-violet-100 text-violet-700 dark:bg-violet-500/20 dark:text-violet-300",
  "bg-sky-100 text-sky-700 dark:bg-sky-500/20 dark:text-sky-300",
  "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-300",
  "bg-amber-100 text-amber-700 dark:bg-amber-500/20 dark:text-amber-300",
  "bg-rose-100 text-rose-700 dark:bg-rose-500/20 dark:text-rose-300",
  "bg-teal-100 text-teal-700 dark:bg-teal-500/20 dark:text-teal-300",
];

function monogramTone(seed: string): string {
  let h = 0;
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) >>> 0;
  return MONOGRAM_TONES[h % MONOGRAM_TONES.length];
}

/** "Built by" / "Maintained by" arrive as free text and the imported data is
 *  inconsistent about it — YES, Yes, No, blank. Read the common answers and
 *  render them one way; anything else shows through as typed. */
function YesNo({ value }: { value: string }) {
  const v = (value ?? "").trim();
  if (!v) return <Dash />;
  const yes = /^y(es)?$/i.test(v);
  const no = /^n(o)?$/i.test(v);
  if (!yes && !no) return <span className="text-sm">{v}</span>;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 text-sm",
        yes ? "font-medium text-emerald-700 dark:text-emerald-400" : "text-muted-foreground"
      )}
    >
      {yes ? <Check className="h-3.5 w-3.5" /> : <Minus className="h-3.5 w-3.5" />}
      {yes ? "Yes" : "No"}
    </span>
  );
}

/** Match a record's stored value against a chosen filter option.
 *  The shared option lists use a sentinel (`_none` / `_unknown`) for the blank
 *  state, since "" is already taken by the "All" choice. */
function matchesOption(stored: string, chosen: string, blankSentinel: string): boolean {
  return chosen === blankSentinel ? !stored : stored === chosen;
}

function hostingLabel(c: ClientRecord): string {
  if (c.hosting_platform === "other") return c.hosting_platform_other || "Other";
  return HOSTING_LABELS[c.hosting_platform] === "—"
    ? ""
    : HOSTING_LABELS[c.hosting_platform] ?? c.hosting_platform;
}

/** A renewal date, flagged once it is close. Dates are stored as plain
 *  YYYY-MM-DD, so they're compared as strings to avoid a timezone shifting the
 *  day — `new Date("2026-07-30")` is UTC midnight and can render as the 29th. */
function RenewalDate({ value }: { value: string | null }) {
  if (!value) return <Dash />;
  const today = new Date();
  const iso = (d: Date) =>
    `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const soon = new Date(today);
  soon.setDate(today.getDate() + 30);
  const overdue = value < iso(today);
  const dueSoon = !overdue && value <= iso(soon);
  if (!overdue && !dueSoon) return <span className="tabular-nums text-sm">{value}</span>;
  return (
    <Pill tone={overdue ? "red" : "amber"} shape="state" className="tabular-nums">
      <span title={overdue ? "Past due" : "Due within 30 days"}>{value}</span>
    </Pill>
  );
}

/** Filter controls sit in their own header row under the column labels, so the
 *  labels stay on one baseline across the table and the controls line up as a
 *  band. Kept small and font-normal so they don't compete with the label above. */
const FILTER_CONTROL =
  "h-8 w-full rounded-md border border-input bg-background px-2 text-xs font-normal text-foreground " +
  "shadow-sm outline-none transition-colors focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/30";

function FilterSelect({ label, value, onChange, options }: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <select
      aria-label={`Filter by ${label}`}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={FILTER_CONTROL}
    >
      <option value="">All</option>
      {options.map((o) => (
        <option key={o.value} value={o.value}>{o.label}</option>
      ))}
    </select>
  );
}

interface Props {
  initialClients: ClientRecord[];
}

// Small sizes are useful on a laptop where the table pane only shows a handful
// of rows at a time. Safe at any value: the clients endpoint is unpaginated, so
// the full list arrives and pageClients slices it here — page_size sent upstream
// is ignored. All values stay within the API's max_page_size of 100.
const PAGE_SIZES = [5, 10, 15, 20, 25, 30, 50, 100] as const;
type PageSize = (typeof PAGE_SIZES)[number];

/** Departments run to six per client, which stacked three rows deep and made
 *  every other row half the height of this one. Two plus a count always fit on
 *  one line, even for the widest pair ("Lead Insight" + "Social Media"); the
 *  rest are named on hover. */
const MAX_DEPT_TAGS = 2;

export function ClientsClient({ initialClients }: Props) {
  const [clients, setClients] = useState<ClientRecord[]>(initialClients);
  const [count, setCount] = useState(initialClients.length);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState<PageSize>(25);
  const [loading, setLoading] = useState(false);

  const [statusFilter, setStatusFilter] = useState<"" | "active" | "paused" | "offboarded">("");

  // Per-column filters, applied client-side — the list endpoint is unpaginated
  // so every client is already here and narrowing is instant. "" means "All";
  // the _none / _unknown sentinels come from the shared option lists and match
  // records whose field is blank.
  const [colFilters, setColFilters] = useState({
    name: "", tier: "", department: "", hosting: "", access: "",
  });

  function setColFilter(key: keyof typeof colFilters, value: string) {
    setColFilters((f) => ({ ...f, [key]: value }));
    setPage(1); // a narrower list can have fewer pages than the current one
  }

  // Import / export
  const [importing, setImporting] = useState(false);
  const [importMsg, setImportMsg] = useState("");
  const [exporting, setExporting] = useState(false);


  const fetchClients = useCallback(async (p: number, ps: number, q: string, s: string) => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ page: String(p), page_size: String(ps) });
      if (q) params.set("q", q);
      if (s) params.set("status", s);
      const res = await fetch(`/api/clients?${params}`);
      const data = await res.json();
      setClients(data.clients ?? []);
      setCount(data.count ?? 0);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchClients(page, pageSize, "", statusFilter);
  }, [page, pageSize, statusFilter, fetchClients]);

  const filtered = useMemo(() => {
    const q = colFilters.name.trim().toLowerCase();
    return clients.filter((c) => {
      // The Client cell shows name over domain, so match either.
      if (q && !`${c.name} ${c.domain}`.toLowerCase().includes(q)) return false;
      if (colFilters.tier && !matchesOption(c.tier, colFilters.tier, "_none")) return false;
      if (colFilters.hosting && !matchesOption(c.hosting_platform, colFilters.hosting, "_unknown")) return false;
      if (colFilters.access && !matchesOption(c.website_access_level, colFilters.access, "_unknown")) return false;
      if (colFilters.department && !(c.departments ?? []).includes(colFilters.department)) return false;
      return true;
    });
  }, [clients, colFilters]);

  // Counts follow the filters, so "N clients" and the page count describe what
  // is actually on screen rather than what the server returned.
  const shownCount = filtered.length;
  const totalPages = Math.ceil(shownCount / pageSize);
  // The API returns the full (unpaginated) list, so slice for the current page
  // here — this is what makes the "Per page" control actually paginate.
  const pageClients = filtered.slice((page - 1) * pageSize, page * pageSize);
  const rangeFrom = shownCount === 0 ? 0 : (page - 1) * pageSize + 1;
  const rangeTo = Math.min(page * pageSize, shownCount);

  async function handleImport(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setImporting(true);
    setImportMsg("");
    const form = new FormData();
    form.append("file", file);
    try {
      const res = await fetch("/api/clients/import", { method: "POST", body: form });
      const data = await res.json();
      if (res.ok) {
        setImportMsg(`Imported: ${data.created} created, ${data.updated} updated, ${data.skipped} skipped.`);
        fetchClients(1, pageSize, "", statusFilter);
        setPage(1);
      } else {
        setImportMsg(data?.detail ?? "Import failed.");
      }
    } finally {
      setImporting(false);
      e.target.value = "";
    }
  }

  // Canonical column order — must match the backend EXPORT_HEADERS so an export
  // can be edited and re-imported without remapping.
  function handleDownloadSample() {
    const headers = [
      "Client Name", "Websites URL (short text)", "Status", "Tier",
      "Hosting Platform (drop down)", "Hosting Platform (Other)",
      "Website Access Level", "Domain Access",
      "Hosting Renewal Date", "Domain Renewal Date",
      "Website Built by Digi", "Website Maintained by Digi", "Departments",
      "Desktop Notifications", "Email Notifications", "Notes",
    ];
    const example = [
      "Example Client Ltd", "https://example.com", "active", "Gold",
      "SiteGround", "",
      "Delegate access", "Khurram GoDaddy Account",
      "2027-03-15", "2027-06-30",
      "Yes", "No", "seo,ads",
      "Yes", "Yes", "Internal note about this client",
    ];
    const csv = [headers, example].map((r) => r.map((v) => `"${v}"`).join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "clients-import-sample.csv";
    a.click();
    URL.revokeObjectURL(url);
  }

  async function handleExport() {
    setExporting(true);
    try {
      const res = await fetch("/api/clients/export");
      if (!res.ok) return;
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "clients-export.csv";
      a.click();
      URL.revokeObjectURL(url);
    } finally {
      setExporting(false);
    }
  }

  function handleStatusFilter(s: "" | "active" | "paused" | "offboarded") {
    setStatusFilter(s);
    setPage(1);
  }

  return (
    // Viewport-tall column that never scrolls itself — only the table pane
    // below does. That keeps the table's horizontal scrollbar at the bottom of
    // the screen instead of below the last row, where 100 rows put it off
    // screen. h-dvh (not h-screen) so mobile browser chrome can't push the
    // scrollbar out of view.
    // Height subtracts the chat safe area that <main> pads by, so the two add
    // back up to exactly one viewport and the page still never scrolls.
    <div className="h-[calc(100dvh-var(--chat-safe-area))] flex flex-col overflow-hidden p-8 gap-5">
      <div className="shrink-0 flex items-start justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Clients</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Hosting, access, and operational details for all clients
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {/* The three CSV actions are one job, so they read as one control
              instead of three loose buttons competing with "Add client". */}
          <div className="flex items-center rounded-lg border bg-card p-1 shadow-sm">
            <Button variant="ghost" size="sm" className="h-8 px-2.5" onClick={handleDownloadSample}>
              <Download className="h-4 w-4" />Sample
            </Button>
            <span aria-hidden className="mx-1 h-5 w-px bg-border" />
            <label className="cursor-pointer">
              <input type="file" accept=".csv" className="hidden" onChange={handleImport} disabled={importing} />
              <Button variant="ghost" size="sm" className="h-8 px-2.5" asChild>
                <span><Upload className="h-4 w-4" />{importing ? "Importing…" : "Import"}</span>
              </Button>
            </label>
            <span aria-hidden className="mx-1 h-5 w-px bg-border" />
            <Button variant="ghost" size="sm" className="h-8 px-2.5" onClick={handleExport} disabled={exporting}>
              <Download className="h-4 w-4" />{exporting ? "Exporting…" : "Export"}
            </Button>
          </div>
          <Button size="sm" className="h-10 px-4" asChild>
            <Link href="/clients/new"><Plus className="h-4 w-4" />Add client</Link>
          </Button>
        </div>
      </div>

      {importMsg && (
        <p className="shrink-0 text-sm text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-md px-3 py-2">{importMsg}</p>
      )}

      {/* One card holds the whole table surface: toolbar, scrolling grid, and
          pagination. Splitting them across three floating blocks was what made
          the page read as unfinished.

          min-h-0 on the Card and the scroll pane is load-bearing: flex items
          default to min-height:auto and refuse to shrink below their content, so
          without it the Card grows to the full height of every row and the inner
          overflow-auto never engages. */}
      <Card className="flex-1 min-h-0 flex flex-col overflow-hidden py-0 gap-0">
        {/* Toolbar */}
        <div className="shrink-0 flex flex-wrap items-center gap-3 border-b px-4 py-3">
          <div className="flex items-center gap-1 rounded-lg bg-muted p-1">
            {(["", "active", "paused", "offboarded"] as const).map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => handleStatusFilter(s)}
                className={cn(
                  "rounded-md px-3 py-1 text-sm font-medium transition-colors",
                  statusFilter === s
                    ? "bg-card text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground"
                )}
              >
                {s === "" ? "All" : s.charAt(0).toUpperCase() + s.slice(1)}
              </button>
            ))}
          </div>
          <span className="text-sm text-muted-foreground">
            <span className="font-medium text-foreground">{shownCount}</span>
            {" "}client{shownCount !== 1 ? "s" : ""}
            {shownCount !== count && <span className="ml-1">of {count}</span>}
          </span>
          <div className="ml-auto flex items-center gap-2 text-sm">
            <label htmlFor="per-page" className="text-muted-foreground">Rows per page</label>
            {/* A dropdown rather than one button per size — eight buttons crowded
                the filter row, and adding sizes later now costs no width. */}
            <select
              id="per-page"
              value={pageSize}
              onChange={(e) => { setPageSize(Number(e.target.value) as PageSize); setPage(1); }}
              className="h-8 rounded-md border border-input bg-background px-2 text-xs shadow-sm outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/30"
            >
              {PAGE_SIZES.map((ps) => <option key={ps} value={ps}>{ps}</option>)}
            </select>
          </div>
        </div>

        <CardContent className="p-0 flex-1 min-h-0">
          {/* The client name is pinned left and everything else scrolls, so a
              row stays identifiable however far across you are. The scroll lives
              on this pane — not the page — so the sidebar and toolbar never
              move. */}
          <div className="h-full overflow-auto">
            {/* overflow-visible on Table's own wrapper is required: by default it
                is a scroll container as tall as every row, so it would own the
                horizontal scrollbar and park it below the last row. Opting out
                hands both scroll axes to the pane above. */}
            <Table wrapperClassName="overflow-visible" className="min-w-[1500px]">
              <TableHeader className="[&_tr]:border-b-0">
                <TableRow className="hover:bg-transparent">
                  <TableHead className={HEAD_LABEL_PINNED}>Client</TableHead>
                  <TableHead className={`${HEAD_LABEL} min-w-[120px]`}>Package</TableHead>
                  <TableHead className={`${HEAD_LABEL} min-w-[250px]`}>Departments</TableHead>
                  <TableHead className={`${HEAD_LABEL} min-w-[140px]`}>Hosting</TableHead>
                  <TableHead className={`${HEAD_LABEL} min-w-[140px]`}>Hosting renewal</TableHead>
                  <TableHead className={`${HEAD_LABEL} min-w-[200px]`}>Domain access</TableHead>
                  <TableHead className={`${HEAD_LABEL} min-w-[150px]`}>Website access</TableHead>
                  <TableHead className={`${HEAD_LABEL} min-w-[130px]`}>Built by us</TableHead>
                  <TableHead className={`${HEAD_LABEL} min-w-[150px]`}>Maintained by us</TableHead>
                  <TableHead className={`${HEAD_LABEL} min-w-[110px]`}>Status</TableHead>
                  <TableHead className={`${HEAD_LABEL} w-20 text-right`}>Edit</TableHead>
                </TableRow>
                <TableRow className="hover:bg-transparent">
                  <TableHead className={FILTER_ROW_PINNED}>
                    <div className="relative">
                      <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                      <input
                        type="search"
                        aria-label="Filter by client name or domain"
                        placeholder="Search name or domain…"
                        value={colFilters.name}
                        onChange={(e) => setColFilter("name", e.target.value)}
                        className={`${FILTER_CONTROL} pl-7`}
                      />
                    </div>
                  </TableHead>
                  <TableHead className={FILTER_ROW}>
                    <FilterSelect
                      label="Package" value={colFilters.tier}
                      onChange={(v) => setColFilter("tier", v)} options={TIER_OPTIONS}
                    />
                  </TableHead>
                  <TableHead className={FILTER_ROW}>
                    <FilterSelect
                      label="Departments" value={colFilters.department}
                      onChange={(v) => setColFilter("department", v)} options={DEPARTMENT_OPTIONS}
                    />
                  </TableHead>
                  <TableHead className={FILTER_ROW}>
                    <FilterSelect
                      label="Hosting" value={colFilters.hosting}
                      onChange={(v) => setColFilter("hosting", v)} options={HOSTING_OPTIONS}
                    />
                  </TableHead>
                  <TableHead className={FILTER_ROW} />
                  <TableHead className={FILTER_ROW} />
                  <TableHead className={FILTER_ROW}>
                    <FilterSelect
                      label="Website Access" value={colFilters.access}
                      onChange={(v) => setColFilter("access", v)} options={ACCESS_LEVEL_OPTIONS}
                    />
                  </TableHead>
                  <TableHead className={FILTER_ROW} />
                  <TableHead className={FILTER_ROW} />
                  <TableHead className={FILTER_ROW} />
                  <TableHead className={FILTER_ROW} />
                </TableRow>
              </TableHeader>
              <TableBody>
                {loading && (
                  <TableRow className="hover:bg-transparent">
                    <TableCell colSpan={COLUMN_COUNT} className="py-16 text-center text-sm text-muted-foreground">
                      Loading clients…
                    </TableCell>
                  </TableRow>
                )}
                {!loading && pageClients.length === 0 && (
                  <TableRow className="hover:bg-transparent">
                    <TableCell colSpan={COLUMN_COUNT} className="py-16">
                      <div className="flex flex-col items-center gap-2 text-center">
                        <div className="rounded-full bg-muted p-3">
                          <Users className="h-5 w-5 text-muted-foreground" />
                        </div>
                        <p className="text-sm font-medium">No clients match these filters</p>
                        <p className="text-sm text-muted-foreground">
                          Clear a filter above, or add a client to get started.
                        </p>
                      </div>
                    </TableCell>
                  </TableRow>
                )}
                {!loading && pageClients.map((c) => (
                  <TableRow
                    key={c.id}
                    className={cn(
                      // Zebra stripe carries the eye across eleven columns, and
                      // the pinned cell picks it up via bg-inherit so it stripes
                      // and highlights with the rest of the row.
                      //
                      // Every one of these must be FULLY OPAQUE. An alpha value
                      // (bg-muted/40) reaches the pinned cell as a translucent
                      // background and the scrolling columns then show through
                      // it. muted/accent are opaque and correctly spaced in
                      // light mode; in dark mode they sit far enough from card
                      // to band the table, so the dark steps are opaque colours
                      // picked to land between the two — not alpha.
                      "bg-card even:bg-muted hover:bg-accent",
                      "dark:even:bg-[oklch(0.215_0.014_290)] dark:hover:bg-[oklch(0.25_0.035_290)]",
                      c.status === "offboarded" && "[&>td]:text-muted-foreground"
                    )}
                  >
                    <TableCell className={`${BODY_PINNED} py-2.5`}>
                      <div className="flex items-center gap-3">
                        <span
                          aria-hidden
                          className={cn(
                            "grid h-8 w-8 shrink-0 place-items-center rounded-lg text-xs font-semibold uppercase",
                            monogramTone(c.name || c.domain || c.id)
                          )}
                        >
                          {(c.name || c.domain || "?").charAt(0)}
                        </span>
                        <div className={CLIENT_TEXT_COL}>
                          <div className="truncate text-sm font-medium" title={c.name}>{c.name}</div>
                          {c.domain ? (
                            <a
                              href={`https://${c.domain}`}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="flex items-center gap-1 truncate text-xs text-muted-foreground hover:text-foreground hover:underline"
                            >
                              <span className="truncate">{c.domain}</span>
                              <ExternalLink className="h-3 w-3 shrink-0" />
                            </a>
                          ) : (
                            <span className="text-xs text-muted-foreground/60">No domain</span>
                          )}
                        </div>
                      </div>
                    </TableCell>

                    <TableCell className="px-4 py-2.5">
                      {c.tier ? (
                        <Pill tone={TIER_TONE[c.tier] ?? "neutral"} className="capitalize">{c.tier}</Pill>
                      ) : <Dash />}
                    </TableCell>

                    <TableCell className="px-4 py-2.5">
                      {c.departments?.length ? (
                        <div className="flex flex-nowrap items-center gap-1">
                          {c.departments.slice(0, MAX_DEPT_TAGS).map((d) => (
                            <Pill key={d} tone="violet">{DEPARTMENT_LABELS[d] ?? d}</Pill>
                          ))}
                          {/* The overflowed departments stay readable on hover,
                              so collapsing them doesn't hide data. */}
                          {c.departments.length > MAX_DEPT_TAGS && (
                            <Pill tone="neutral" className="cursor-default">
                              <span
                                title={c.departments
                                  .slice(MAX_DEPT_TAGS)
                                  .map((d) => DEPARTMENT_LABELS[d] ?? d)
                                  .join(", ")}
                              >
                                +{c.departments.length - MAX_DEPT_TAGS}
                              </span>
                            </Pill>
                          )}
                        </div>
                      ) : <Dash />}
                    </TableCell>

                    <TableCell className="px-4 py-2.5 text-sm">
                      {hostingLabel(c) || <Dash />}
                    </TableCell>
                    <TableCell className="whitespace-nowrap px-4 py-2.5 text-sm">
                      <RenewalDate value={c.hosting_renewal_date} />
                    </TableCell>

                    <TableCell className="max-w-[220px] px-4 py-2.5 text-sm">
                      {c.domain_access_location ? (
                        <span className="block truncate" title={c.domain_access_location}>
                          {c.domain_access_location}
                        </span>
                      ) : <Dash />}
                    </TableCell>

                    <TableCell className="px-4 py-2.5">
                      {c.website_access_level ? (
                        <Pill tone={ACCESS_TONE[c.website_access_level] ?? "neutral"} shape="state">
                          {ACCESS_LEVEL_TABLE_LABELS[c.website_access_level] ?? c.website_access_level}
                        </Pill>
                      ) : <Dash />}
                    </TableCell>

                    <TableCell className="px-4 py-2.5">
                      <YesNo value={c.website_built_by_digi} />
                    </TableCell>
                    <TableCell className="px-4 py-2.5">
                      <YesNo value={c.website_maintained_by_digi} />
                    </TableCell>

                    <TableCell className="px-4 py-2.5">
                      <Pill tone={STATUS_TONE[c.status] ?? "neutral"} shape="state" className="capitalize">
                        {c.status}
                      </Pill>
                    </TableCell>

                    <TableCell className="px-4 py-2.5 text-right">
                      <Link
                        href={`/clients/${c.id}`}
                        title={`Edit ${c.name}`}
                        className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-transparent text-muted-foreground transition-colors hover:border-border hover:bg-background hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      >
                        <Pencil className="h-3.5 w-3.5" />
                        <span className="sr-only">Edit {c.name}</span>
                      </Link>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </CardContent>

        {/* Pagination lives inside the card so the range and the controls that
            change it sit on the same surface as the rows they describe. */}
        <div className="shrink-0 flex flex-wrap items-center justify-between gap-3 border-t px-4 py-3 text-sm">
          <span className="text-muted-foreground">
            {shownCount === 0
              ? "No clients to show"
              : <>Showing <span className="font-medium text-foreground">{rangeFrom}–{rangeTo}</span> of {shownCount}</>}
          </span>
          {totalPages > 1 && (
            <div className="flex items-center gap-1">
              <Button variant="outline" size="sm" className="h-8 w-8 p-0" onClick={() => setPage(1)} disabled={page === 1} title="First page">«</Button>
              <Button variant="outline" size="sm" className="h-8 w-8 p-0" onClick={() => setPage((p) => p - 1)} disabled={page === 1} title="Previous page">
                <ChevronLeft className="h-4 w-4" />
              </Button>
              {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                const start = Math.max(1, Math.min(page - 2, totalPages - 4));
                const p = start + i;
                return (
                  <button
                    key={p}
                    type="button"
                    onClick={() => setPage(p)}
                    aria-current={p === page ? "page" : undefined}
                    className={cn(
                      "h-8 w-8 rounded-md border text-xs font-medium transition-colors",
                      p === page
                        ? "border-primary bg-primary text-primary-foreground"
                        : "border-input hover:bg-muted"
                    )}
                  >
                    {p}
                  </button>
                );
              })}
              <Button variant="outline" size="sm" className="h-8 w-8 p-0" onClick={() => setPage((p) => p + 1)} disabled={page === totalPages} title="Next page">
                <ChevronRight className="h-4 w-4" />
              </Button>
              <Button variant="outline" size="sm" className="h-8 w-8 p-0" onClick={() => setPage(totalPages)} disabled={page === totalPages} title="Last page">»</Button>
            </div>
          )}
        </div>
      </Card>
    </div>
  );
}
