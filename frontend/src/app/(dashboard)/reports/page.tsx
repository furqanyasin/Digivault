"use client";

import { useCallback, useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { FileText, RefreshCw, Download, Loader2 } from "lucide-react";

interface Report {
  id: string;
  website: string;
  website_domain: string;
  period_start: string;
  period_end: string;
  report_format: "pdf" | "csv";
  status: "pending" | "done" | "failed";
  download_url: string | null;
  error: string;
  generated_at: string | null;
  created_at: string;
}

interface WebsiteOption {
  id: string;
  name: string;
  domain: string;
}

function unwrap<T>(env: unknown): T {
  const e = env as { data?: unknown; results?: unknown };
  const inner = e?.data ?? env;
  return inner as T;
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

export default function ReportsPage() {
  const [reports, setReports] = useState<Report[]>([]);
  const [websites, setWebsites] = useState<WebsiteOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const period = defaultPeriod();
  const [websiteId, setWebsiteId] = useState("");
  const [periodStart, setPeriodStart] = useState(period.start);
  const [periodEnd, setPeriodEnd] = useState(period.end);
  const [format, setFormat] = useState<"pdf" | "csv">("pdf");

  const fetchReports = useCallback(async () => {
    setLoading(true);
    const res = await fetch("/api/reports");
    if (res.ok) {
      const env = await res.json();
      setReports(asList<Report>(unwrap<unknown>(env)));
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    (async () => {
      const res = await fetch("/api/websites");
      if (res.ok) {
        const env = await res.json();
        const list = asList<WebsiteOption>(unwrap<unknown>(env));
        setWebsites(list);
        if (list.length > 0) setWebsiteId(list[0].id);
      }
      await fetchReports();
    })();
  }, [fetchReports]);

  async function handleGenerate(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!websiteId) {
      setError("Select a website.");
      return;
    }
    setGenerating(true);
    const res = await fetch("/api/reports/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        website_id: websiteId,
        period_start: periodStart,
        period_end: periodEnd,
        report_format: format,
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
    <div className="p-8 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight flex items-center gap-2">
            <FileText className="h-7 w-7" />
            Reports
          </h1>
          <p className="text-muted-foreground mt-1">
            Generate and download client reports (PDF / CSV).
          </p>
        </div>
        <button
          onClick={fetchReports}
          className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground"
        >
          <RefreshCw className="h-4 w-4" />
          Refresh
        </button>
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Generate a report</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleGenerate} className="flex flex-wrap items-end gap-3">
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-muted-foreground">Website</label>
              <select
                value={websiteId}
                onChange={(e) => setWebsiteId(e.target.value)}
                className="border rounded-md px-3 py-1.5 text-sm bg-background min-w-48"
              >
                {websites.length === 0 && <option value="">No websites</option>}
                {websites.map((w) => (
                  <option key={w.id} value={w.id}>
                    {w.name || w.domain}
                  </option>
                ))}
              </select>
            </div>
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
            <button
              type="submit"
              disabled={generating || !websiteId}
              className="inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            >
              {generating && <Loader2 className="h-4 w-4 animate-spin" />}
              Generate
            </button>
          </form>
          {error && <p className="text-sm text-destructive mt-3">{error}</p>}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-0">
          <CardTitle className="text-base">Generated reports</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {loading ? (
            <div className="text-center py-12 text-muted-foreground text-sm">Loading…</div>
          ) : reports.length === 0 ? (
            <div className="text-center py-12 text-muted-foreground text-sm">
              No reports yet. Generate one above.
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b">
                  <th className="text-left px-4 py-3 font-medium text-muted-foreground">Website</th>
                  <th className="text-left px-4 py-3 font-medium text-muted-foreground">Period</th>
                  <th className="text-left px-4 py-3 font-medium text-muted-foreground">Format</th>
                  <th className="text-left px-4 py-3 font-medium text-muted-foreground">Status</th>
                  <th className="text-left px-4 py-3 font-medium text-muted-foreground">Generated</th>
                  <th className="text-right px-4 py-3 font-medium text-muted-foreground">Download</th>
                </tr>
              </thead>
              <tbody>
                {reports.map((r) => (
                  <tr key={r.id} className="border-b last:border-0 hover:bg-muted/30">
                    <td className="px-4 py-3 font-medium">{r.website_domain}</td>
                    <td className="px-4 py-3 text-muted-foreground text-xs whitespace-nowrap">
                      {r.period_start} → {r.period_end}
                    </td>
                    <td className="px-4 py-3 uppercase text-xs">{r.report_format}</td>
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
                    <td className="px-4 py-3 text-right">
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
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
