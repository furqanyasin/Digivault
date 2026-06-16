"use client";

import { useState } from "react";
import { Loader2, RefreshCw, CheckCircle2, XCircle, AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";

interface PageRow { url: string; indexable: boolean; reason: string; checked_at?: string }
export interface SeoReport {
  last_checked_at: string | null;
  check_status: string;
  robots_status: string;
  robots_blocks_all: boolean;
  robots_content: string;
  sitemap_status: string;
  sitemap_url: string;
  sitemap_url_count: number;
  sitemap_pages: string[];
  homepage_indexable: boolean | null;
  pages_checked: PageRow[];
  noindex_count: number;
  seo_scan_interval_days: number;
  meta_title: string;
  meta_description: string;
  h1: string;
  canonical_url: string;
  schema_types: string[];
}

const INTERVALS = [
  { v: 0, label: "Off" },
  { v: 1, label: "Daily" },
  { v: 3, label: "Every 3 days" },
  { v: 7, label: "Every 7 days" },
  { v: 14, label: "Every 14 days" },
  { v: 30, label: "Every 30 days" },
];

function StatusIcon({ ok, warn }: { ok: boolean; warn?: boolean }) {
  if (warn) return <AlertTriangle className="h-4 w-4 text-amber-500" />;
  return ok ? <CheckCircle2 className="h-4 w-4 text-emerald-500" /> : <XCircle className="h-4 w-4 text-red-500" />;
}

function MetaRow({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex gap-3 px-3 py-2 text-xs">
      <span className="text-muted-foreground w-32 shrink-0">{label}</span>
      <span className={`flex-1 break-words ${mono ? "font-mono" : ""} ${value ? "" : "text-muted-foreground"}`}>
        {value || "—"}
      </span>
    </div>
  );
}

export function SeoTab({ websiteId, report }: { websiteId: string; report: SeoReport | null }) {
  const [data, setData] = useState<SeoReport | null>(report);
  const [busy, setBusy] = useState(false);
  const [interval, setIntervalVal] = useState<number>(report?.seo_scan_interval_days ?? 0);

  async function recheck() {
    setBusy(true);
    try {
      await fetch(`/api/websites/${websiteId}/seo`, { method: "POST" });
      // Poll once after a short delay for fresh results.
      setTimeout(async () => {
        const res = await fetch(`/api/websites/${websiteId}/seo`);
        if (res.ok) setData(await res.json());
        setBusy(false);
      }, 4000);
    } catch {
      setBusy(false);
    }
  }

  async function changeInterval(v: number) {
    setIntervalVal(v);
    await fetch(`/api/websites/${websiteId}/seo`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ seo_scan_interval_days: v }),
    });
  }

  if (!data || data.check_status === "never") {
    return (
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">No SEO check has run yet.</p>
        <Button size="sm" variant="outline" onClick={recheck} disabled={busy}>
          {busy ? <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5 mr-1.5" />}
          Run check
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-4">
        <p className="text-xs text-muted-foreground">
          {data.last_checked_at ? `Last checked ${new Date(data.last_checked_at).toLocaleString()}` : "Never checked"}
        </p>
        <div className="flex items-center gap-2">
          <select
            value={interval}
            onChange={(e) => changeInterval(Number(e.target.value))}
            className="border rounded-md px-2 py-1 text-xs bg-background"
          >
            {INTERVALS.map((i) => <option key={i.v} value={i.v}>{i.label}</option>)}
          </select>
          <Button size="sm" variant="outline" onClick={recheck} disabled={busy}>
            {busy ? <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5 mr-1.5" />}
            Re-check
          </Button>
        </div>
      </div>

      <div className="grid sm:grid-cols-3 gap-3">
        <div className="border rounded-lg p-3 space-y-1">
          <div className="flex items-center gap-2 text-sm font-medium">
            <StatusIcon ok={data.robots_status === "found" && !data.robots_blocks_all} warn={data.robots_blocks_all} />
            robots.txt
          </div>
          <p className="text-xs text-muted-foreground">
            {data.robots_status === "found"
              ? (data.robots_blocks_all ? "Blocks all crawlers" : "Present")
              : "Missing"}
          </p>
        </div>
        <div className="border rounded-lg p-3 space-y-1">
          <div className="flex items-center gap-2 text-sm font-medium">
            <StatusIcon ok={data.sitemap_status === "found"} />
            Sitemap
          </div>
          <p className="text-xs text-muted-foreground">
            {data.sitemap_status === "found" ? `${data.sitemap_url_count} URLs` : "Missing"}
          </p>
        </div>
        <div className="border rounded-lg p-3 space-y-1">
          <div className="flex items-center gap-2 text-sm font-medium">
            <StatusIcon ok={data.homepage_indexable === true} />
            Indexable
          </div>
          <p className="text-xs text-muted-foreground">
            {data.homepage_indexable === false
              ? "Homepage is noindex"
              : `${data.noindex_count} noindex of ${data.pages_checked.length} pages tracked`}
          </p>
        </div>
      </div>

      {(data.meta_title || data.meta_description || data.h1 || data.canonical_url || data.schema_types?.length > 0) && (
        <div className="border rounded-lg divide-y">
          <div className="px-3 py-2 text-sm font-medium">On-page SEO <span className="text-xs text-muted-foreground font-normal">· homepage · changes raise a Site Event</span></div>
          <MetaRow label="Title" value={data.meta_title} />
          <MetaRow label="Meta description" value={data.meta_description} />
          <MetaRow label="H1" value={data.h1} />
          <MetaRow label="Canonical" value={data.canonical_url} mono />
          <div className="flex gap-3 px-3 py-2 text-xs">
            <span className="text-muted-foreground w-32 shrink-0">Schema</span>
            <span className="flex-1">
              {data.schema_types?.length > 0 ? (
                <span className="flex flex-wrap gap-1">
                  {data.schema_types.map((t) => (
                    <span key={t} className="rounded bg-muted px-1.5 py-0.5 font-mono">{t}</span>
                  ))}
                </span>
              ) : (
                <span className="text-muted-foreground">None detected</span>
              )}
            </span>
          </div>
        </div>
      )}

      {data.robots_content && (
        <details className="border rounded-lg">
          <summary className="cursor-pointer select-none px-3 py-2 text-sm font-medium">robots.txt</summary>
          <pre className="px-3 pb-3 text-xs font-mono whitespace-pre-wrap break-all text-muted-foreground max-h-96 overflow-auto">
            {data.robots_content}
          </pre>
        </details>
      )}

      {data.sitemap_pages?.length > 0 && (
        <details className="border rounded-lg">
          <summary className="cursor-pointer select-none px-3 py-2 text-sm font-medium">
            Sitemap <span className="text-xs text-muted-foreground font-normal">· {data.sitemap_url_count} URLs{data.sitemap_url ? ` · ${data.sitemap_url}` : ""}</span>
          </summary>
          <div className="px-3 pb-3 max-h-96 overflow-auto space-y-0.5">
            {data.sitemap_pages.map((u) => (
              <div key={u} className="text-xs font-mono text-muted-foreground break-all">{u}</div>
            ))}
          </div>
        </details>
      )}

      {data.pages_checked.length > 0 && (
        <div className="space-y-1.5">
          <p className="text-xs text-muted-foreground">
            Indexability is checked on a rotating batch of ~15 pages per run and accumulates here, so
            every page is covered over a few runs (set the cadence to <span className="font-medium">Daily</span> above
            for fastest coverage) — no heavy one-shot crawl. The set is the homepage, pages the tracking
            snippet has actually seen (where a hidden <span className="font-medium">noindex</span> turns up,
            since those are kept out of the sitemap), and sitemap entries.
          </p>
          <div className="border rounded-lg divide-y">
            {data.pages_checked.map((p) => (
              <div key={p.url} className="flex items-center justify-between gap-3 px-3 py-2 text-xs">
                <span className="font-mono truncate max-w-[55%]" title={p.url}>{p.url}</span>
                <span className="flex items-center gap-3 shrink-0">
                  {p.checked_at && (
                    <span className="text-muted-foreground/60">{new Date(p.checked_at).toLocaleDateString()}</span>
                  )}
                  <span className={p.indexable ? "text-emerald-600" : "text-red-600"}>
                    {p.indexable ? "indexable" : (p.reason || "noindex")}
                  </span>
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
