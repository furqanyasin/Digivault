"use client";

import { useEffect, useRef, useState } from "react";
import { Flame, Loader2, MousePointerClick, Move, Scroll, Monitor, Smartphone, Zap } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { HeatmapInstance } from "heatmap.js";
import type { Website } from "@/lib/api";

interface Props {
  websites: Website[];
}

interface PageStats {
  id: string;
  page_url: string;
  device: "desktop" | "mobile";
  visits: number;
  total_clicks: number;
  max_scroll_percent: number;
  scroll_histogram: Record<string, number>;
  last_seen_at: string | null;
}

interface Cell {
  kind: "click" | "move" | "scroll" | "rage";
  x: number;
  y: number;
  count: number;
  device: string;
  element?: string;
}

type DeviceFilter = "desktop" | "mobile";
type MapKind = "click" | "move" | "scroll" | "rage";

interface HeatmapModule {
  create(config: {
    container: HTMLElement;
    radius?: number;
    maxOpacity?: number;
    minOpacity?: number;
    blur?: number;
    gradient?: Record<string, string>;
  }): HeatmapInstance;
}

// Rage clicks are shown with a red-dominant scale so bursts of frustrated
// clicking stand out from the ordinary click/move heat.
const RAGE_GRADIENT: Record<string, string> = {
  "0.0": "rgba(255,0,60,0)",
  "0.3": "rgba(255,40,40,0.4)",
  "0.6": "rgba(255,120,0,0.75)",
  "0.85": "rgba(255,210,0,0.9)",
  "1.0": "rgba(255,255,200,1)",
};

const DEVICES: { value: DeviceFilter; label: string; icon: typeof Monitor }[] = [
  { value: "desktop", label: "Desktop", icon: Monitor },
  { value: "mobile", label: "Mobile", icon: Smartphone },
];

const MAP_KINDS: { value: MapKind; label: string; icon: typeof MousePointerClick }[] = [
  { value: "click", label: "Click", icon: MousePointerClick },
  { value: "move", label: "Move", icon: Move },
  { value: "scroll", label: "Scroll", icon: Scroll },
  { value: "rage", label: "Rage", icon: Zap },
];

function loadHeatmap(): Promise<HeatmapModule> {
  return import("heatmap.js").then((m) =>
    (m.default as HeatmapModule) ?? (window as unknown as { h337: HeatmapModule }).h337
  );
}

// ---- Scroll-depth strip helpers -------------------------------------------------
// The snippet reports scroll_histogram as { depthPercent: shareReached } for
// buckets 5..100 step 5. We turn that into a vertical gradient where each
// page-depth band is coloured by how many visitors reached at least that far —
// green = reached by (almost) everyone, red = reached by few.
function reachColor(share: number): string {
  const t = Math.max(0, Math.min(1, share));
  const r = Math.round(255 - 225 * t);
  const g = Math.round(60 + 120 * t);
  const b = Math.round(60 + 30 * t);
  return `rgba(${r}, ${g}, ${b}, 0.85)`;
}

function scrollStops(histogram: Record<string, number>): { y: number; share: number }[] {
  const stops: { y: number; share: number }[] = [];
  for (const [bucket, share] of Object.entries(histogram || {})) {
    const y = Number(bucket);
    const s = Number(share);
    if (Number.isFinite(y) && y >= 0 && y <= 100 && Number.isFinite(s)) {
      stops.push({ y, share: s });
    }
  }
  stops.sort((a, b) => a.y - b.y);
  return stops;
}

function scrollGradient(histogram: Record<string, number>): string {
  const stops = scrollStops(histogram);
  if (!stops.length) return "rgba(0,0,0,0)";
  const parts = stops.map((s) => `${reachColor(s.share)} ${s.y}%`);
  if (stops[stops.length - 1].y < 100) parts.push(`${reachColor(0)} 100%`);
  return `linear-gradient(to bottom, ${parts.join(", ")})`;
}

export function HeatmapClient({ websites }: Props) {
  const [websiteId, setWebsiteId] = useState<string>(websites[0]?.id ?? "");
  const [pages, setPages] = useState<PageStats[]>([]);
  const [pageUrl, setPageUrl] = useState<string>("");
  const [device, setDevice] = useState<DeviceFilter>("desktop");
  const [kind, setKind] = useState<MapKind>("click");
  const [cells, setCells] = useState<Cell[]>([]);
  const [loadingCells, setLoadingCells] = useState(false);
  const [pageHeight, setPageHeight] = useState(2.0);
  const [summary, setSummary] = useState<Record<string, { visits: number; total_clicks: number; max_scroll_percent: number }>>({});

  const heatmapRef = useRef<HTMLDivElement>(null);
  const instanceRef = useRef<HeatmapInstance | null>(null);
  const pageUrlRef = useRef<string>("");

  const website = websites.find((w) => w.id === websiteId) ?? null;
  const refWidth = device === "mobile" ? 375 : 1280;
  const selectedPage = pages.find((p) => p.page_url === pageUrl) ?? null;
  const siteSummary = summary[device];

  useEffect(() => {
    pageUrlRef.current = pageUrl;
  }, [pageUrl]);

  // Load the pages + summary for the selected website.
  useEffect(() => {
    if (!websiteId) return;
    let cancelled = false;
    (async () => {
      const [pageList, summaryData] = await Promise.all([
        fetch(`/api/heatmap/pages?website=${websiteId}&page_size=100`).then((r) =>
          r.ok ? r.json() : []
        ),
        fetch(`/api/heatmap/summary?website=${websiteId}`).then((r) =>
          r.ok ? r.json() : {}
        ),
      ]);
      if (cancelled) return;
      const list = Array.isArray(pageList) ? (pageList as PageStats[]) : [];
      setPages(list);
      setSummary((summaryData as typeof summary) ?? {});
      const current = pageUrlRef.current;
      if (!current || !list.some((p) => p.page_url === current)) {
        setPageUrl(list[0]?.page_url ?? "");
        setCells([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [websiteId]);

  // Load the activity cells whenever the selection changes. The scroll map has
  // no cells — it reads the page's scroll_histogram instead — so skip the fetch.
  useEffect(() => {
    if (!websiteId || !pageUrl) return;
    if (kind === "scroll") return;
    let cancelled = false;
    (async () => {
      const data = (await fetch(
        `/api/heatmap/activity?website=${websiteId}&page_url=${encodeURIComponent(pageUrl)}&kind=${kind}&device=${device}`
      ).then((r) => (r.ok ? r.json() : []))) as Cell[];
      if (cancelled) return;
      setCells(Array.isArray(data) ? data : []);
      setLoadingCells(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [websiteId, pageUrl, kind, device]);

  // Render/refresh the heatmap overlay whenever the data changes.
  useEffect(() => {
    const container = heatmapRef.current;
    if (!container || !cells.length) {
      if (instanceRef.current) {
        instanceRef.current.remove();
        instanceRef.current = null;
      }
      return;
    }
    let disposed = false;
    loadHeatmap().then((h337) => {
      if (disposed || !container) return;
      if (instanceRef.current) instanceRef.current.remove();
      const W = container.clientWidth || refWidth;
      const H = container.clientHeight || Math.round(refWidth * pageHeight);
      const instance = h337.create({
        container,
        radius: 40,
        maxOpacity: 0.5,
        minOpacity: 0.05,
        blur: 0.75,
        ...(kind === "rage" ? { gradient: RAGE_GRADIENT } : {}),
      });
      instanceRef.current = instance;
      const max = Math.max(1, ...cells.map((c) => c.count));
      instance.setData({
        max,
        data: cells.map((c) => ({
          x: Math.round((c.x / 100) * W),
          y: Math.round((c.y / 100) * H),
          value: c.count,
        })),
      });
    });
    return () => {
      disposed = true;
    };
  }, [cells, pageHeight, refWidth, pageUrl, kind]);

  function selectWebsite(id: string) {
    setWebsiteId(id);
    setCells([]);
    setPageUrl("");
  }

  function selectPage(url: string) {
    setPageUrl(url);
    setCells([]);
    setLoadingCells(true);
  }

  function selectDevice(value: DeviceFilter) {
    setDevice(value);
    setCells([]);
    setLoadingCells(true);
  }

  function selectKind(value: MapKind) {
    setKind(value);
    setCells([]);
    setLoadingCells(true);
  }

  const totalClicks = cells.reduce((s, c) => s + c.count, 0);
  const maxValue = Math.max(0, ...cells.map((c) => c.count));

  const scrollHistogram = selectedPage?.scroll_histogram ?? null;
  const scrollStopsList = scrollHistogram ? scrollStops(scrollHistogram) : [];
  const scrollGrad = scrollHistogram ? scrollGradient(scrollHistogram) : "";
  const maxScroll = selectedPage?.max_scroll_percent ?? siteSummary?.max_scroll_percent ?? 0;
  const hasScrollData = scrollHistogram != null && scrollStopsList.length > 0;

  // Strongest cells, surfaced with their element descriptor so a hotspot can be
  // attributed ("users rage-clicking the checkout button"), not just visualised.
  const topHotspots = [...cells]
    .sort((a, b) => b.count - a.count)
    .slice(0, 6);

  return (
    <div className="space-y-6">
      {/* Toolbar */}
      <Card>
        <CardContent className="p-4">
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto_auto] items-end">
            <div>
              <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
                Website
              </label>
              <Select value={websiteId} onValueChange={selectWebsite}>
                <SelectTrigger className="w-full">
                  <SelectValue placeholder="Select a website" />
                </SelectTrigger>
                <SelectContent>
                  {websites.map((w) => (
                    <SelectItem key={w.id} value={w.id}>
                      {w.name || w.domain}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div>
              <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
                Page
              </label>
              <Select value={pageUrl} onValueChange={selectPage} disabled={!pages.length}>
                <SelectTrigger className="w-full">
                  <SelectValue placeholder={pages.length ? "Select a page" : "No data yet"} />
                </SelectTrigger>
                <SelectContent>
                  {pages.map((p) => (
                    <SelectItem key={p.id} value={p.page_url}>
                      {p.page_url}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div>
              <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
                Device
              </label>
              <div className="inline-flex rounded-md border bg-muted p-0.5">
                {DEVICES.map((d) => (
                  <Button
                    key={d.value}
                    type="button"
                    variant={device === d.value ? "default" : "ghost"}
                    size="sm"
                    className="gap-1.5"
                    onClick={() => selectDevice(d.value)}
                  >
                    <d.icon className="h-4 w-4" />
                    {d.label}
                  </Button>
                ))}
              </div>
            </div>

            <div>
              <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
                Map
              </label>
              <div className="inline-flex rounded-md border bg-muted p-0.5">
                {MAP_KINDS.map((m) => (
                  <Button
                    key={m.value}
                    type="button"
                    variant={kind === m.value ? "default" : "ghost"}
                    size="sm"
                    className="gap-1.5"
                    onClick={() => selectKind(m.value)}
                  >
                    <m.icon className="h-4 w-4" />
                    {m.label}
                  </Button>
                ))}
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Summary */}
      <div className="grid gap-4 sm:grid-cols-3">
        <Card>
          <CardHeader className="flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Observations</CardTitle>
            <Flame className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {selectedPage ? selectedPage.visits : siteSummary?.visits ?? 0}
            </div>
            <p className="text-xs text-muted-foreground">
              {selectedPage ? "Page observations" : "Site-wide"}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Clicks</CardTitle>
            <MousePointerClick className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {selectedPage ? selectedPage.total_clicks : siteSummary?.total_clicks ?? 0}
            </div>
            <p className="text-xs text-muted-foreground">
              Totals for the selected {device} view
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Max scroll</CardTitle>
            <Scroll className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {selectedPage ? selectedPage.max_scroll_percent : siteSummary?.max_scroll_percent ?? 0}%
            </div>
            <p className="text-xs text-muted-foreground">Depthest page region reached</p>
          </CardContent>
        </Card>
      </div>

      {/* Heatmap */}
      <Card>
        <CardContent className="p-4">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2 text-sm">
              {kind === "scroll" ? (
                <Badge variant="default">
                  {maxScroll}% avg. max scroll{hasScrollData ? ` · ${scrollStopsList.length} depth bands` : ""}
                </Badge>
              ) : kind === "rage" ? (
                <Badge variant="destructive">
                  {totalClicks} rage clicks
                </Badge>
              ) : (
                <Badge variant={kind === "click" ? "default" : "secondary"}>
                  {totalClicks} {kind === "click" ? "clicks" : "move samples"}
                </Badge>
              )}
              {kind !== "scroll" && maxValue > 0 && (
                <span className="text-xs text-muted-foreground">peak cell ×{maxValue}</span>
              )}
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground">Page height</span>
              <input
                type="range"
                min={1}
                max={4}
                step={0.5}
                value={pageHeight}
                onChange={(e) => setPageHeight(Number(e.target.value))}
                className="w-32"
              />
              <span className="text-xs text-muted-foreground tabular-nums">
                ×{pageHeight.toFixed(1)}
              </span>
            </div>
          </div>

          <div className="relative overflow-hidden rounded-lg border bg-muted" style={{ width: refWidth + 24 }}>
            <div className="relative" style={{ width: refWidth, height: Math.round(refWidth * pageHeight) }}>
              {website && (
                <iframe
                  src={`https://${website.domain}`}
                  title="Page"
                  className="absolute inset-0 h-full w-full border-0"
                  loading="lazy"
                  referrerPolicy="no-referrer"
                />
              )}
              {kind !== "scroll" && (
                <div
                  ref={heatmapRef}
                  className="pointer-events-none absolute inset-0 z-10"
                  style={{ opacity: 0.85 }}
                />
              )}
              {kind === "scroll" && (
                <div className="pointer-events-none absolute inset-y-0 left-1 z-10 flex flex-col">
                  <div
                    className="w-3.5 flex-1 overflow-hidden rounded-sm border border-border"
                    style={{ background: hasScrollData ? scrollGrad : "rgba(120,120,120,0.15)" }}
                    title={
                      hasScrollData
                        ? scrollStopsList
                            .map((s) => `${s.y}% → ${Math.round(s.share * 100)}% reached`)
                            .join("\n")
                        : "No scroll histogram yet"
                    }
                  />
                  <span
                    className="mt-1 self-center text-[10px] font-medium leading-none text-muted-foreground"
                  >
                    {maxScroll}%
                  </span>
                </div>
              )}
              {/* Max-scroll marker line */}
              {kind === "scroll" && maxScroll > 0 && hasScrollData && (
                <div
                  className="pointer-events-none absolute inset-x-0 z-10 border-t border-dashed border-red-500/70"
                  style={{ top: `${Math.min(100, maxScroll)}%` }}
                />
              )}
              {loadingCells && kind !== "scroll" && (
                <div className="absolute inset-0 z-20 flex items-center justify-center bg-background/40">
                  <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                </div>
              )}
              {!loadingCells && kind !== "scroll" && cells.length === 0 && (
                <div className="absolute inset-0 z-20 flex items-center justify-center bg-background/40 text-sm text-muted-foreground">
                  No {kind} data for this selection yet
                </div>
              )}
              {!loadingCells && kind === "scroll" && !hasScrollData && (
                <div className="absolute inset-0 z-20 flex items-center justify-center bg-background/40 text-sm text-muted-foreground">
                  No scroll depth data for this selection yet
                </div>
              )}
            </div>
          </div>
          {(kind === "click" || kind === "rage") && cells.length > 0 && (
            <div className="mt-3 rounded-lg border bg-muted/40 p-3">
              <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Top {kind} hotspots
              </h4>
              <ul className="space-y-1.5">
                {topHotspots.map((c, i) => (
                  <li key={i} className="flex items-baseline gap-2 text-xs">
                    <span className="w-14 shrink-0 font-mono text-muted-foreground">
                      {c.x}%,{c.y}%
                    </span>
                    <span
                      className="min-w-0 flex-1 truncate font-medium"
                      title={c.element || undefined}
                    >
                      {c.element || (kind === "rage" ? "Unattributed rage" : "Unattributed click")}
                    </span>
                    <span className="shrink-0 tabular-nums text-muted-foreground">×{c.count}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <p className="mt-2 text-xs text-muted-foreground">
            {kind === "scroll"
              ? "The left strip shows the share of visitors that scrolled past each page-depth band (0% top to 100% bottom); the dashed line marks the deepest region reached. Adjust the page height to match the live page's aspect."
              : "Overlay is normalised to percentage coordinates from the tracking snippet and mapped onto a {refWidth}px reference width. Drag the page height slider to match the live page's aspect so the overlay lines up."}
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
