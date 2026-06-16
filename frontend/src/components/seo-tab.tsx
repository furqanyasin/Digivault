"use client";

import { useState } from "react";
import { Loader2, RefreshCw, CheckCircle2, XCircle, AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";

interface PageRow { url: string; indexable: boolean; reason: string }
export interface SeoReport {
  last_checked_at: string | null;
  check_status: string;
  robots_status: string;
  robots_blocks_all: boolean;
  sitemap_status: string;
  sitemap_url: string;
  sitemap_url_count: number;
  homepage_indexable: boolean | null;
  pages_checked: PageRow[];
  noindex_count: number;
  seo_scan_interval_days: number;
}

const INTERVALS = [
  { v: 0, label: "Off" },
  { v: 3, label: "Every 3 days" },
  { v: 7, label: "Every 7 days" },
  { v: 14, label: "Every 14 days" },
  { v: 30, label: "Every 30 days" },
];

function StatusIcon({ ok, warn }: { ok: boolean; warn?: boolean }) {
  if (warn) return <AlertTriangle className="h-4 w-4 text-amber-500" />;
  return ok ? <CheckCircle2 className="h-4 w-4 text-emerald-500" /> : <XCircle className="h-4 w-4 text-red-500" />;
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
              : `${data.noindex_count} noindex of ${data.pages_checked.length} checked`}
          </p>
        </div>
      </div>

      {data.pages_checked.length > 0 && (
        <div className="border rounded-lg divide-y">
          {data.pages_checked.map((p) => (
            <div key={p.url} className="flex items-center justify-between px-3 py-2 text-xs">
              <span className="font-mono truncate max-w-[60%]" title={p.url}>{p.url}</span>
              <span className={p.indexable ? "text-emerald-600" : "text-red-600"}>
                {p.indexable ? "indexable" : (p.reason || "noindex")}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
