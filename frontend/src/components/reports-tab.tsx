"use client";

import { useCallback, useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { RefreshCw, Download, Loader2, Trash2 } from "lucide-react";

interface Report {
  id: string;
  website: string;
  website_domain: string;
  period_start: string;
  period_end: string;
  report_format: "pdf" | "csv";
  sections: string[];
  status: "pending" | "done" | "failed";
  download_url: string | null;
  error: string;
  generated_at: string | null;
  created_at: string;
}

// Keys mirror Report.SECTION_KEYS on the backend. Overview is always included.
const SECTION_OPTIONS: { key: string; label: string; description: string }[] = [
  { key: "active_scripts", label: "Active Scripts", description: "Third-party scripts currently on the site" },
  { key: "script_changes", label: "Script Changes", description: "Changes detected during the period" },
  { key: "performance", label: "Performance", description: "Latest PageSpeed scores (mobile & desktop)" },
  { key: "uptime", label: "Uptime & Downtime", description: "Monitor uptime % and downtime over the period" },
  { key: "security", label: "Security", description: "Vulnerabilities and PHP errors" },
  { key: "domain_ssl", label: "Domain & SSL", description: "Registrar, hosting, expiry dates" },
  { key: "recommendations", label: "Recommendations", description: "Suggested actions based on findings" },
];

const SECTION_LABELS: Record<string, string> = Object.fromEntries(
  SECTION_OPTIONS.map((o) => [o.key, o.label])
);

function unwrap<T>(env: unknown): T {
  const e = env as { data?: unknown };
  return (e?.data ?? env) as T;
}

function asList<T>(value: unknown): T[] {
  if (Array.isArray(value)) return value as T[];
  const v = value as { results?: T[] } | null;
  return v?.results ?? [];
}

function formatDate(iso: string | null) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function statusVariant(s: Report["status"]): "default" | "secondary" | "destructive" {
  if (s === "done") return "default";
  if (s === "failed") return "destructive";
  return "secondary";
}

function defaultPeriod() {
  const end = new Date();
  const start = new Date();
  start.setMonth(start.getMonth() - 1);
  const iso = (d: Date) => d.toISOString().slice(0, 10);
  return { start: iso(start), end: iso(end) };
}

export function ReportsTab({ websiteId }: { websiteId: string }) {
  const [reports, setReports] = useState<Report[]>([]);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const period = defaultPeriod();
  const [periodStart, setPeriodStart] = useState(period.start);
  const [periodEnd, setPeriodEnd] = useState(period.end);
  const [format, setFormat] = useState<"pdf" | "csv">("pdf");
  const [selected, setSelected] = useState<Set<string>>(
    new Set(SECTION_OPTIONS.map((o) => o.key))
  );

  const fetchReports = useCallback(async () => {
    setLoading(true);
    const res = await fetch(`/api/reports?website_id=${websiteId}`);
    if (res.ok) {
      const env = await res.json();
      setReports(asList<Report>(unwrap<unknown>(env)));
    }
    setLoading(false);
  }, [websiteId]);

  useEffect(() => {
    fetchReports();
  }, [fetchReports]);

  function toggleSection(key: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  const allSelected = selected.size === SECTION_OPTIONS.length;

  function toggleAll() {
    setSelected(allSelected ? new Set() : new Set(SECTION_OPTIONS.map((o) => o.key)));
  }

  async function handleDelete(id: string) {
    if (!window.confirm("Delete this report? This cannot be undone.")) return;
    setError(null);
    setDeletingId(id);
    const res = await fetch(`/api/reports/${id}`, { method: "DELETE" });
    setDeletingId(null);
    if (res.ok) {
      setReports((prev) => prev.filter((r) => r.id !== id));
    } else {
      setError("Failed to delete report.");
    }
  }

  async function handleGenerate(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setGenerating(true);
    const res = await fetch("/api/reports/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        website_id: websiteId,
        period_start: periodStart,
        period_end: periodEnd,
        report_format: format,
        // Sending all keys and sending none both mean a full report; the
        // backend treats an empty list as "all sections".
        sections: allSelected ? [] : Array.from(selected),
      }),
    });
    setGenerating(false);
    if (res.ok) {
      await fetchReports();
    } else {
      const env = await res.json().catch(() => ({}));
      setError((env as { detail?: string })?.detail ?? "Failed to generate report.");
    }
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Generate a report</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <form onSubmit={handleGenerate} className="space-y-4">
            <div className="flex flex-wrap items-end gap-3">
              <div className="flex flex-col gap-1">
                <label className="text-xs font-medium text-muted-foreground">From</label>
                <input
                  type="date"
                  value={periodStart}
                  onChange={(e) => setPeriodStart(e.target.value)}
                  className="border rounded-md px-3 py-1.5 text-sm bg-background"
                />
              </div>
              <div className="flex flex-col gap-1">
                <label className="text-xs font-medium text-muted-foreground">To</label>
                <input
                  type="date"
                  value={periodEnd}
                  onChange={(e) => setPeriodEnd(e.target.value)}
                  className="border rounded-md px-3 py-1.5 text-sm bg-background"
                />
              </div>
              <div className="flex flex-col gap-1">
                <label className="text-xs font-medium text-muted-foreground">Format</label>
                <select
                  value={format}
                  onChange={(e) => setFormat(e.target.value as "pdf" | "csv")}
                  className="border rounded-md px-3 py-1.5 text-sm bg-background"
                >
                  <option value="pdf">PDF</option>
                  <option value="csv">CSV</option>
                </select>
              </div>
            </div>

            <div>
              <div className="flex items-center justify-between mb-2">
                <p className="text-xs font-medium text-muted-foreground">Include in report</p>
                <button
                  type="button"
                  onClick={toggleAll}
                  className="text-xs text-primary hover:underline"
                >
                  {allSelected ? "Deselect all" : "Select all"}
                </button>
              </div>
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                <label className="flex items-start gap-2 rounded-md border p-3 opacity-70 cursor-not-allowed">
                  <input type="checkbox" checked disabled className="mt-0.5 accent-primary" />
                  <span>
                    <span className="block text-sm font-medium">Overview</span>
                    <span className="block text-xs text-muted-foreground">
                      Health score and site summary (always included)
                    </span>
                  </span>
                </label>
                {SECTION_OPTIONS.map((o) => (
                  <label
                    key={o.key}
                    className={`flex items-start gap-2 rounded-md border p-3 cursor-pointer transition-colors ${
                      selected.has(o.key) ? "border-primary/50 bg-primary/5" : "hover:bg-muted/50"
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={selected.has(o.key)}
                      onChange={() => toggleSection(o.key)}
                      className="mt-0.5 accent-primary"
                    />
                    <span>
                      <span className="block text-sm font-medium">{o.label}</span>
                      <span className="block text-xs text-muted-foreground">{o.description}</span>
                    </span>
                  </label>
                ))}
              </div>
            </div>

            <button
              type="submit"
              disabled={generating}
              className="inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            >
              {generating && <Loader2 className="h-4 w-4 animate-spin" />}
              Generate report
            </button>
          </form>
          {error && <p className="text-sm text-destructive">{error}</p>}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-0 flex flex-row items-center justify-between">
          <CardTitle className="text-base">Generated reports</CardTitle>
          <button
            onClick={fetchReports}
            className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground"
          >
            <RefreshCw className="h-4 w-4" />
            Refresh
          </button>
        </CardHeader>
        <CardContent className="p-0">
          {loading ? (
            <div className="text-center py-12 text-muted-foreground text-sm">Loading…</div>
          ) : reports.length === 0 ? (
            <div className="text-center py-12 text-muted-foreground text-sm">
              No reports yet for this website. Generate one above.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b">
                    <th className="text-left px-4 py-3 font-medium text-muted-foreground">Period</th>
                    <th className="text-left px-4 py-3 font-medium text-muted-foreground">Format</th>
                    <th className="text-left px-4 py-3 font-medium text-muted-foreground">Sections</th>
                    <th className="text-left px-4 py-3 font-medium text-muted-foreground">Status</th>
                    <th className="text-left px-4 py-3 font-medium text-muted-foreground">Generated</th>
                    <th className="text-right px-4 py-3 font-medium text-muted-foreground">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {reports.map((r) => (
                    <tr key={r.id} className="border-b last:border-0 hover:bg-muted/30">
                      <td className="px-4 py-3 text-muted-foreground text-xs whitespace-nowrap">
                        {r.period_start} → {r.period_end}
                      </td>
                      <td className="px-4 py-3 uppercase text-xs">{r.report_format}</td>
                      <td className="px-4 py-3 text-xs text-muted-foreground max-w-[260px]">
                        {!r.sections || r.sections.length === 0
                          ? "All sections"
                          : r.sections.map((s) => SECTION_LABELS[s] ?? s).join(", ")}
                      </td>
                      <td className="px-4 py-3">
                        <Badge variant={statusVariant(r.status)} className="text-xs">
                          {r.status}
                        </Badge>
                        {r.status === "failed" && r.error && (
                          <div className="text-xs text-destructive/70 mt-0.5">{r.error}</div>
                        )}
                      </td>
                      <td className="px-4 py-3 text-muted-foreground text-xs whitespace-nowrap">
                        {formatDate(r.generated_at)}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center justify-end gap-3">
                          {r.download_url ? (
                            <a
                              href={`/api/reports/${r.id}/download`}
                              className="inline-flex items-center gap-1 text-primary hover:underline text-xs"
                            >
                              <Download className="h-3.5 w-3.5" />
                              Download
                            </a>
                          ) : (
                            <span className="text-muted-foreground text-xs">—</span>
                          )}
                          <button
                            onClick={() => handleDelete(r.id)}
                            disabled={deletingId === r.id}
                            aria-label="Delete report"
                            className="inline-flex items-center gap-1 text-muted-foreground hover:text-destructive text-xs disabled:opacity-50"
                          >
                            {deletingId === r.id ? (
                              <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            ) : (
                              <Trash2 className="h-3.5 w-3.5" />
                            )}
                            Delete
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
