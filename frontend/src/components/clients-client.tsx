"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import {
  Search, Upload, RefreshCw, Plus, ExternalLink,
  CheckCircle2, XCircle, ChevronDown, ChevronUp, Download,
  ChevronLeft, ChevronRight,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import type { ClientRecord } from "@/app/(dashboard)/clients/page";

const HOSTING_LABELS: Record<string, string> = {
  wpengine: "WPEngine", siteground: "SiteGround", cloudways: "Cloudways",
  bluehost: "Bluehost", godaddy: "GoDaddy", squarespace: "Squarespace",
  wix: "Wix", shopify: "Shopify", other: "Other", "": "—",
};

interface LookupResult {
  id: string;
  name: string;
  website_url: string;
  status: string;
  has_access: boolean;
  access_summary: string;
  hosting_platform: string;
  running_ppc_ads: string;
  website_built_by_digi: string;
  website_maintained_by_digi: string;
  domain_access_location: string;
  migration_status: string;
}

interface Props {
  initialClients: ClientRecord[];
}

const PAGE_SIZES = [25, 50, 100] as const;

export function ClientsClient({ initialClients }: Props) {
  const [clients, setClients] = useState<ClientRecord[]>(initialClients);
  const [count, setCount] = useState(initialClients.length);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState<25 | 50 | 100>(25);
  const [loading, setLoading] = useState(false);

  const [statusFilter, setStatusFilter] = useState<"" | "active" | "inactive">("");

  // Lookup (CSM quick-answer)
  const [lookupQuery, setLookupQuery] = useState("");
  const [lookupResults, setLookupResults] = useState<LookupResult[] | null>(null);
  const [lookupLoading, setLookupLoading] = useState(false);
  const [lookupExpanded, setLookupExpanded] = useState(true);

  // Import / export
  const [importing, setImporting] = useState(false);
  const [importMsg, setImportMsg] = useState("");
  const [exporting, setExporting] = useState(false);

  // Sync all
  const [syncing, setSyncing] = useState(false);
  const [syncMsg, setSyncMsg] = useState("");

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

  const totalPages = Math.ceil(count / pageSize);

  async function handleLookup(e: React.FormEvent) {
    e.preventDefault();
    if (!lookupQuery.trim()) return;
    setLookupLoading(true);
    setLookupResults(null);
    try {
      const res = await fetch(`/api/clients/search?q=${encodeURIComponent(lookupQuery)}`);
      const data = await res.json();
      setLookupResults(data.results ?? []);
    } finally {
      setLookupLoading(false);
    }
  }

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
      "Task ID", "Task Name", "Websites URL (short text)", "Hosting Platform (drop down)",
      "Hosting Renewal Date", "Contract Renewal Date", "Domain Access", "Website Built by Digi",
      "Website Maintained by Digi", "Migration Status (drop down)",
      "Confirmation from CSM for Migration (drop down)",
      "Are we running PPC Ads (drop down)", "Notes", "Comments (short text)",
    ];
    const example = [
      "86evnnba3", "Example Client Ltd", "https://example.com", "SiteGround",
      "2027-03-15", "2027-06-30", "Khurram GoDaddy Account", "Yes",
      "Yes", "No - We didn't do",
      "Yes, We can do Migration", "No",
      "Internal note about this client", "Renewal due in March",
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

  async function handleSyncAll() {
    setSyncing(true);
    setSyncMsg("");
    try {
      const res = await fetch("/api/clients/sync-all", { method: "POST" });
      const data = await res.json();
      setSyncMsg(`Synced: ${data.synced ?? 0} ok, ${data.failed ?? 0} failed.`);
      fetchClients(page, pageSize, "", statusFilter);
    } finally {
      setSyncing(false);
    }
  }

  function handleStatusFilter(s: "" | "active" | "inactive") {
    setStatusFilter(s);
    setPage(1);
  }

  return (
    <div className="p-8 space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
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
          <Button variant="outline" size="sm" onClick={handleSyncAll} disabled={syncing}>
            <RefreshCw className={`h-4 w-4 mr-1 ${syncing ? "animate-spin" : ""}`} />
            {syncing ? "Syncing…" : "Sync ClickUp"}
          </Button>
          <Button size="sm" asChild>
            <Link href="/clients/new"><Plus className="h-4 w-4 mr-1" />Add client</Link>
          </Button>
        </div>
      </div>

      {importMsg && (
        <p className="text-sm text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-md px-3 py-2">{importMsg}</p>
      )}
      {syncMsg && (
        <p className="text-sm text-blue-700 bg-blue-50 border border-blue-200 rounded-md px-3 py-2">{syncMsg}</p>
      )}

      {/* CSM Lookup */}
      <Card>
        <CardHeader className="pb-2">
          <button
            type="button"
            className="flex items-center justify-between w-full text-left"
            onClick={() => setLookupExpanded((v) => !v)}
          >
            <CardTitle className="text-base flex items-center gap-2">
              <Search className="h-4 w-4" />
              Quick Lookup — "Do we have access to this website?"
            </CardTitle>
            {lookupExpanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
          </button>
        </CardHeader>
        {lookupExpanded && (
          <CardContent className="space-y-4">
            <form onSubmit={handleLookup} className="flex gap-2">
              <Input
                placeholder="Type domain or client name, e.g. abc.com"
                value={lookupQuery}
                onChange={(e) => setLookupQuery(e.target.value)}
                className="flex-1"
              />
              <Button type="submit" disabled={lookupLoading}>
                {lookupLoading ? "Searching…" : "Search"}
              </Button>
            </form>
            {lookupResults !== null && (
              lookupResults.length === 0 ? (
                <div className="flex items-center gap-2 rounded-md border bg-red-50 border-red-200 px-4 py-3">
                  <XCircle className="h-5 w-5 text-red-500 shrink-0" />
                  <div>
                    <p className="font-medium text-sm text-red-800">Not found</p>
                    <p className="text-xs text-red-600">No client matches &ldquo;{lookupQuery}&rdquo;.</p>
                  </div>
                </div>
              ) : lookupResults.map((r) => (
                <div key={r.id} className={`rounded-md border px-4 py-3 space-y-2 ${r.has_access ? "bg-emerald-50 border-emerald-200" : "bg-amber-50 border-amber-200"}`}>
                  <div className="flex items-center gap-2">
                    {r.has_access
                      ? <CheckCircle2 className="h-5 w-5 text-emerald-600 shrink-0" />
                      : <XCircle className="h-5 w-5 text-amber-600 shrink-0" />}
                    <div>
                      <p className="font-semibold text-sm">{r.name}</p>
                      <p className="text-xs text-muted-foreground">{r.website_url}</p>
                    </div>
                    <Badge variant={r.status === "active" ? "success" : "secondary"} className="ml-auto capitalize">
                      {r.status}
                    </Badge>
                  </div>
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-6 gap-y-1 text-xs pt-1 border-t border-current/10">
                    <LookupRow label="Domain Access" value={r.access_summary} />
                    <LookupRow label="Hosting" value={(HOSTING_LABELS[r.hosting_platform] ?? r.hosting_platform) || "—"} />
                    <LookupRow label="Built by Digi" value={r.website_built_by_digi || "—"} />
                    <LookupRow label="Maintained by Digi" value={r.website_maintained_by_digi || "—"} />
                    <LookupRow label="Migration" value={r.migration_status || "—"} />
                  </div>
                  <div className="text-right">
                    <Link href={`/clients/${r.id}`} className="text-xs underline text-muted-foreground hover:text-foreground">
                      View full details →
                    </Link>
                  </div>
                </div>
              ))
            )}
          </CardContent>
        )}
      </Card>

      {/* Filters */}
      <div className="flex gap-2 flex-wrap items-center">
        <div className="flex rounded-md border overflow-hidden text-sm">
          {(["", "active", "inactive"] as const).map((s) => (
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
        <span className="text-sm text-muted-foreground">{count} client{count !== 1 ? "s" : ""}</span>
        <div className="ml-auto flex items-center gap-2 text-sm">
          <span className="text-muted-foreground">Per page:</span>
          {PAGE_SIZES.map((ps) => (
            <button
              key={ps}
              type="button"
              onClick={() => { setPageSize(ps); setPage(1); }}
              className={`px-2 py-1 rounded border text-xs ${pageSize === ps ? "bg-primary text-primary-foreground border-primary" : "hover:bg-muted"}`}
            >
              {ps}
            </button>
          ))}
        </div>
      </div>

      {/* Clients table */}
      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Client</TableHead>
                <TableHead>Hosting</TableHead>
                <TableHead>Domain Access</TableHead>
                <TableHead>Built by Digi</TableHead>
                <TableHead>Maintained by Digi</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="w-10" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading && (
                <TableRow>
                  <TableCell colSpan={7} className="text-center text-muted-foreground py-8">Loading…</TableCell>
                </TableRow>
              )}
              {!loading && clients.length === 0 && (
                <TableRow>
                  <TableCell colSpan={7} className="text-center text-muted-foreground py-8">No clients found.</TableCell>
                </TableRow>
              )}
              {!loading && clients.map((c) => (
                <TableRow key={c.id} className={c.status === "inactive" ? "opacity-50" : ""}>
                  <TableCell>
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
                  <TableCell className="text-sm">{(HOSTING_LABELS[c.hosting_platform] ?? c.hosting_platform) || "—"}</TableCell>
                  <TableCell className="text-xs text-muted-foreground max-w-[180px] truncate">
                    {c.domain_access_location || "—"}
                  </TableCell>
                  <TableCell className="text-sm">{c.website_built_by_digi || "—"}</TableCell>
                  <TableCell className="text-sm">{c.website_maintained_by_digi || "—"}</TableCell>
                  <TableCell>
                    <Badge variant={c.status === "active" ? "success" : "secondary"} className="capitalize">
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
        </CardContent>
      </Card>

      {/* Pagination controls */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between text-sm">
          <span className="text-muted-foreground">
            Page {page} of {totalPages} &middot; {count} total
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

function LookupRow({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span className="text-muted-foreground">{label}: </span>
      <span className="font-medium">{value}</span>
    </div>
  );
}
