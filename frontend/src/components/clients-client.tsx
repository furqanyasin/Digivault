"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import Link from "next/link";
import {
  Upload, Plus, ExternalLink, Download, ChevronLeft, ChevronRight,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  DEPARTMENT_LABELS, DEPARTMENT_OPTIONS, TIER_OPTIONS,
  HOSTING_OPTIONS, ACCESS_LEVEL_OPTIONS,
} from "@/lib/client-fields";
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

// The pinned column needs an opaque background of its own: without it the
// scrolling columns slide visibly underneath. `bg-card` matches the Card.
// Three sticky layers overlap in this table, so the z-order is explicit:
// the corner cell (pinned both ways) must sit above the header row, which must
// sit above the pinned first column, or they overlap during diagonal scrolling.
// All of them need an opaque background or rows show through underneath.
// align-top on the header cells so labels line up across columns whose cells
// now differ in height — the filterable ones carry a control underneath.
const STICKY_HEAD =
  "sticky left-0 top-0 z-30 bg-card align-top py-2 min-w-[220px] after:absolute after:inset-y-0 after:right-0 after:w-px after:bg-border";
const STICKY_HEAD_ROW = "sticky top-0 z-20 bg-card align-top py-2";
const STICKY_CELL =
  "sticky left-0 z-10 bg-card min-w-[220px] after:absolute after:inset-y-0 after:right-0 after:w-px after:bg-border";

const TIER_TONE: Record<string, string> = {
  gold: "border-amber-400 text-amber-700 dark:text-amber-400",
  silver: "border-slate-400 text-slate-600 dark:text-slate-300",
  bronze: "border-orange-400 text-orange-700 dark:text-orange-400",
};

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
  if (!value) return <span className="text-muted-foreground">—</span>;
  const today = new Date();
  const iso = (d: Date) =>
    `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const soon = new Date(today);
  soon.setDate(today.getDate() + 30);
  const overdue = value < iso(today);
  const dueSoon = !overdue && value <= iso(soon);
  return (
    <span
      className={
        overdue ? "font-semibold text-red-600" : dueSoon ? "font-semibold text-amber-600" : ""
      }
      title={overdue ? "Past due" : dueSoon ? "Due within 30 days" : undefined}
    >
      {value}
    </span>
  );
}

/** Filter controls sit under their column's label inside the sticky header, so
 *  they scroll sideways with the column they belong to and stay visible while
 *  scrolling down. Kept small and font-normal so they don't compete with the
 *  header label above them. */
const FILTER_CONTROL =
  "mt-1.5 w-full border rounded px-1.5 py-1 text-xs font-normal bg-background text-foreground";

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
    <div className="h-[calc(100dvh-var(--chat-safe-area))] flex flex-col overflow-hidden p-8 gap-6">
      <div className="shrink-0 flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Clients</h1>
          <p className="text-muted-foreground mt-1">Hosting, access, and operational details for all clients</p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <Button variant="outline" size="sm" onClick={handleDownloadSample}>
            <Download className="h-4 w-4 mr-1" />Sample CSV
          </Button>
          <label className="cursor-pointer">
            <input type="file" accept=".csv" className="hidden" onChange={handleImport} disabled={importing} />
            <Button variant="outline" size="sm" asChild>
              <span><Upload className="h-4 w-4 mr-1" />{importing ? "Importing…" : "Import CSV"}</span>
            </Button>
          </label>
          <Button variant="outline" size="sm" onClick={handleExport} disabled={exporting}>
            <Download className="h-4 w-4 mr-1" />{exporting ? "Exporting…" : "Export CSV"}
          </Button>
          <Button size="sm" asChild>
            <Link href="/clients/new"><Plus className="h-4 w-4 mr-1" />Add client</Link>
          </Button>
        </div>
      </div>

      {importMsg && (
        <p className="shrink-0 text-sm text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-md px-3 py-2">{importMsg}</p>
      )}


      {/* Filters */}
      <div className="shrink-0 flex gap-2 flex-wrap items-center">
        <div className="flex rounded-md border overflow-hidden text-sm">
          {(["", "active", "paused", "offboarded"] as const).map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => handleStatusFilter(s)}
              className={`px-3 py-1.5 transition-colors ${statusFilter === s ? "bg-primary text-primary-foreground" : "hover:bg-muted"}`}
            >
              {s === "" ? "All" : s.charAt(0).toUpperCase() + s.slice(1)}
            </button>
          ))}
        </div>
        <span className="text-sm text-muted-foreground">
          {shownCount} client{shownCount !== 1 ? "s" : ""}
          {shownCount !== count && <span className="ml-1">of {count}</span>}
        </span>
        <div className="ml-auto flex items-center gap-2 text-sm">
          <label htmlFor="per-page" className="text-muted-foreground">Per page:</label>
          {/* A dropdown rather than one button per size — eight buttons crowded
              the filter row, and adding sizes later now costs no width. */}
          <select
            id="per-page"
            value={pageSize}
            onChange={(e) => { setPageSize(Number(e.target.value) as PageSize); setPage(1); }}
            className="border rounded-md px-2 py-1 text-xs bg-background"
          >
            {PAGE_SIZES.map((ps) => <option key={ps} value={ps}>{ps}</option>)}
          </select>
        </div>
      </div>

      {/* Clients table.
          The client name is pinned left and everything else scrolls, so a row
          stays identifiable however far across you are. The scroll lives on this
          wrapper — not the page — so the sidebar and filters never move.

          min-h-0 on the Card and CardContent is load-bearing: flex items default
          to min-height:auto and refuse to shrink below their content, so without
          it the Card grows to the full height of every row and the inner
          overflow-auto never engages. */}
      <Card className="flex-1 min-h-0 flex flex-col">
        <CardContent className="p-0 flex-1 min-h-0">
          <div className="h-full overflow-auto">
            {/* overflow-visible on Table's own wrapper is required: by default it
                is a scroll container as tall as every row, so it would own the
                horizontal scrollbar and park it below the last row. Opting out
                hands both scroll axes to the pane above. */}
            <Table wrapperClassName="overflow-visible" className="min-w-[1100px]">
              <TableHeader>
                <TableRow>
                  <TableHead className={STICKY_HEAD}>
                    Client
                    <input
                      type="search"
                      aria-label="Filter by client name or domain"
                      placeholder="Search name or domain…"
                      value={colFilters.name}
                      onChange={(e) => setColFilter("name", e.target.value)}
                      className={FILTER_CONTROL}
                    />
                  </TableHead>
                  <TableHead className={`${STICKY_HEAD_ROW} min-w-[150px]`}>
                    Package
                    <FilterSelect
                      label="Package" value={colFilters.tier}
                      onChange={(v) => setColFilter("tier", v)} options={TIER_OPTIONS}
                    />
                  </TableHead>
                  <TableHead className={`${STICKY_HEAD_ROW} min-w-[190px]`}>
                    Departments
                    <FilterSelect
                      label="Departments" value={colFilters.department}
                      onChange={(v) => setColFilter("department", v)} options={DEPARTMENT_OPTIONS}
                    />
                  </TableHead>
                  <TableHead className={`${STICKY_HEAD_ROW} min-w-[140px]`}>
                    Hosting
                    <FilterSelect
                      label="Hosting" value={colFilters.hosting}
                      onChange={(v) => setColFilter("hosting", v)} options={HOSTING_OPTIONS}
                    />
                  </TableHead>
                  <TableHead className={`${STICKY_HEAD_ROW} min-w-[130px]`}>Hosting renewal</TableHead>
                  <TableHead className={`${STICKY_HEAD_ROW} min-w-[180px]`}>Domain Access</TableHead>
                  <TableHead className={`${STICKY_HEAD_ROW} min-w-[150px]`}>
                    Website Access
                    <FilterSelect
                      label="Website Access" value={colFilters.access}
                      onChange={(v) => setColFilter("access", v)} options={ACCESS_LEVEL_OPTIONS}
                    />
                  </TableHead>
                  <TableHead className={`${STICKY_HEAD_ROW} min-w-[150px]`}>Built By Digilatics</TableHead>
                  <TableHead className={`${STICKY_HEAD_ROW} min-w-[170px]`}>Maintained By Digilatics</TableHead>
                  <TableHead className={`${STICKY_HEAD_ROW} min-w-[110px]`}>Status</TableHead>
                  <TableHead className={`${STICKY_HEAD_ROW} w-16`} />
                </TableRow>
              </TableHeader>
              <TableBody>
                {loading && (
                  <TableRow>
                    <TableCell colSpan={COLUMN_COUNT} className="text-center text-muted-foreground py-8">
                      Loading…
                    </TableCell>
                  </TableRow>
                )}
                {!loading && clients.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={COLUMN_COUNT} className="text-center text-muted-foreground py-8">
                      No clients found.
                    </TableCell>
                  </TableRow>
                )}
                {!loading && pageClients.map((c) => (
                  <TableRow key={c.id} className={c.status === "offboarded" ? "opacity-50" : ""}>
                    {/* Sticky cell needs its own background, or the scrolling
                        columns show through underneath it. */}
                    <TableCell className={STICKY_CELL}>
                      <div className="font-medium text-sm">{c.name}</div>
                      <a
                        href={`https://${c.domain}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-xs text-muted-foreground hover:underline flex items-center gap-1"
                      >
                        {c.domain} <ExternalLink className="h-3 w-3" />
                      </a>
                    </TableCell>

                    <TableCell>
                      {c.tier ? (
                        <Badge variant="outline" className={`capitalize ${TIER_TONE[c.tier] ?? ""}`}>
                          {c.tier}
                        </Badge>
                      ) : (
                        <span className="text-sm text-muted-foreground">—</span>
                      )}
                    </TableCell>

                    <TableCell>
                      {c.departments?.length ? (
                        <div className="flex flex-wrap gap-1">
                          {c.departments.map((d) => (
                            <Badge key={d} variant="secondary" className="text-xs font-normal">
                              {DEPARTMENT_LABELS[d] ?? d}
                            </Badge>
                          ))}
                        </div>
                      ) : (
                        <span className="text-sm text-muted-foreground">—</span>
                      )}
                    </TableCell>

                    <TableCell className="text-sm">
                      {hostingLabel(c) || <span className="text-muted-foreground">—</span>}
                    </TableCell>
                    <TableCell className="text-sm whitespace-nowrap">
                      <RenewalDate value={c.hosting_renewal_date} />
                    </TableCell>

                    <TableCell className="text-xs text-muted-foreground max-w-[220px] truncate"
                      title={c.domain_access_location || undefined}>
                      {c.domain_access_location || "—"}
                    </TableCell>

                    <TableCell>
                      {c.website_access_level ? (
                        <Badge
                          variant={
                            c.website_access_level === "full_admin" ? "success" :
                            c.website_access_level === "delegate" ? "warning" :
                            c.website_access_level === "not_working" ? "destructive" : "secondary"
                          }
                        >
                          {ACCESS_LEVEL_TABLE_LABELS[c.website_access_level] ?? c.website_access_level}
                        </Badge>
                      ) : (
                        <span className="text-sm text-muted-foreground">—</span>
                      )}
                    </TableCell>

                    <TableCell className="text-sm">{c.website_built_by_digi || "—"}</TableCell>
                    <TableCell className="text-sm">{c.website_maintained_by_digi || "—"}</TableCell>

                    <TableCell>
                      <Badge
                        variant={c.status === "active" ? "success" : c.status === "paused" ? "warning" : "secondary"}
                        className="capitalize"
                      >
                        {c.status}
                      </Badge>
                    </TableCell>

                    <TableCell>
                      <Link href={`/clients/${c.id}`} className="text-xs text-muted-foreground hover:text-foreground underline">
                        Edit
                      </Link>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      {/* Pagination controls */}
      {totalPages > 1 && (
        <div className="shrink-0 flex items-center justify-between text-sm">
          <span className="text-muted-foreground">
            Page {page} of {totalPages} &middot; {shownCount} total
          </span>
          <div className="flex items-center gap-1">
            <Button variant="outline" size="sm" onClick={() => setPage(1)} disabled={page === 1}>«</Button>
            <Button variant="outline" size="sm" onClick={() => setPage((p) => p - 1)} disabled={page === 1}>
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
                  className={`w-8 h-8 rounded border text-xs ${p === page ? "bg-primary text-primary-foreground border-primary" : "hover:bg-muted"}`}
                >
                  {p}
                </button>
              );
            })}
            <Button variant="outline" size="sm" onClick={() => setPage((p) => p + 1)} disabled={page === totalPages}>
              <ChevronRight className="h-4 w-4" />
            </Button>
            <Button variant="outline" size="sm" onClick={() => setPage(totalPages)} disabled={page === totalPages}>»</Button>
          </div>
        </div>
      )}
    </div>
  );
}
