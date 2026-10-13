"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  Camera,
  Flame,
  Image as ImageIcon,
  Loader2,
  Monitor,
  MousePointerClick,
  Move,
  Power,
  Scroll,
  Smartphone,
  Square,
  Zap,
} from "lucide-react";
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
import type { HeatmapGradient } from "heatmap.js";
import type { Website } from "@/lib/api";
import { HeatmapOverlay } from "@/components/heatmap/heatmap-overlay";
import { ScrollOverlay, type ScrollStop } from "@/components/heatmap/scroll-overlay";
import { Backdrop, type BackdropMode, type Snapshot } from "@/components/heatmap/backdrop";

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
  /** Full document height in CSS px, as last observed by the snippet. */
  page_height: number;
  /** Viewport width the page_height was measured at. */
  viewport_width: number;
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
type VisitorFilter = "all" | "new" | "returning";
type SourceFilter = "all" | "direct" | "organic" | "social" | "email" | "referral";

// Rage clicks get a red-dominant scale so bursts of frustrated clicking read as
// distinct from ordinary click/move heat rather than as "more of the same".
const RAGE_GRADIENT: HeatmapGradient = {
  "0.0": "rgba(255,0,60,0)",
  "0.3": "rgba(255,40,40,0.45)",
  "0.6": "rgba(255,120,0,0.8)",
  "0.85": "rgba(255,210,0,0.92)",
  "1.0": "rgba(255,255,220,1)",
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

const BACKDROPS: { value: BackdropMode; label: string; icon: typeof ImageIcon }[] = [
  { value: "snapshot", label: "Screenshot", icon: ImageIcon },
  { value: "live", label: "Live page", icon: Camera },
  { value: "blank", label: "Blank", icon: Square },
];

const VISITOR_OPTIONS: { value: VisitorFilter; label: string }[] = [
  { value: "all", label: "All visitors" },
  { value: "new", label: "New" },
  { value: "returning", label: "Returning" },
];

const SOURCE_OPTIONS: { value: SourceFilter; label: string }[] = [
  { value: "all", label: "All sources" },
  { value: "direct", label: "Direct" },
  { value: "organic", label: "Organic" },
  { value: "social", label: "Social" },
  { value: "email", label: "Email" },
  { value: "referral", label: "Referral" },
];

// Widths the snippet's x-percentages are rendered against, matching
// `VIEWPORTS` in apps/heatmap/capture.py. Capturing at one width and rendering
// at another is exactly the misalignment the snapshot exists to remove.
const REFERENCE_WIDTH: Record<DeviceFilter, number> = { desktop: 1280, mobile: 375 };

// Used only when neither a snapshot nor a snippet-reported page height exists —
// rows written before the snippet started sending geometry.
const FALLBACK_ASPECT = 2.0;

function scrollStopsFrom(histogram: Record<string, number> | null): ScrollStop[] {
  if (!histogram) return [];
  const stops: ScrollStop[] = [];
  for (const [bucket, share] of Object.entries(histogram)) {
    const y = Number(bucket);
    const s = Number(share);
    if (Number.isFinite(y) && y >= 0 && y <= 100 && Number.isFinite(s)) {
      stops.push({ y, share: s });
    }
  }
  stops.sort((a, b) => a.y - b.y);
  return stops;
}

/** The snapshot row for one page + device, or null when none exists yet. */
async function fetchSnapshot(
  websiteId: string,
  pageUrl: string,
  device: DeviceFilter
): Promise<Snapshot | null> {
  // A 404 here is a normal state, not an error: nothing has been captured yet.
  return fetch(
    `/api/heatmap/snapshot?website=${websiteId}&page_url=${encodeURIComponent(
      pageUrl
    )}&device=${device}`
  )
    .then((r) => (r.ok ? (r.json() as Promise<Snapshot>) : null))
    .catch(() => null);
}

/** Container width, tracked so the overlay can be sized in real pixels. */
function useMeasuredWidth() {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width ?? 0;
      setWidth(Math.floor(w));
    });
    observer.observe(el);
    setWidth(Math.floor(el.getBoundingClientRect().width));
    return () => observer.disconnect();
  }, []);
  return { ref, width };
}

export function HeatmapClient({ websites }: Props) {
  // Collection is opt-in per site, so the first site with it switched on is a
  // far better landing selection than the first site alphabetically — that one
  // is usually off, and the page opened on a permanent empty state.
  const [websiteId, setWebsiteId] = useState<string>(
    () => (websites.find((w) => w.heatmap_enabled) ?? websites[0])?.id ?? ""
  );
  // Which sites are collecting, tracked locally so the enable button can flip
  // the UI without a round trip through the server component.
  const [enabled, setEnabled] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(websites.map((w) => [w.id, Boolean(w.heatmap_enabled)]))
  );
  const [enabling, setEnabling] = useState(false);
  const [captureError, setCaptureError] = useState<string | null>(null);
  const [pages, setPages] = useState<PageStats[]>([]);
  const [pageUrl, setPageUrl] = useState<string>("");
  const [device, setDevice] = useState<DeviceFilter>("desktop");
  const [kind, setKind] = useState<MapKind>("click");
  const [visitor, setVisitor] = useState<VisitorFilter>("all");
  const [source, setSource] = useState<SourceFilter>("all");
  const [backdrop, setBackdrop] = useState<BackdropMode>("snapshot");
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [capturing, setCapturing] = useState(false);
  const [manualAspect, setManualAspect] = useState<number | null>(null);
  const [summary, setSummary] = useState<
    Record<string, { visits: number; total_clicks: number; max_scroll_percent: number }>
  >({});

  const pageUrlRef = useRef<string>("");
  const { ref: frameRef, width: availableWidth } = useMeasuredWidth();

  const website = websites.find((w) => w.id === websiteId) ?? null;
  const collecting = websiteId ? enabled[websiteId] === true : false;
  const selectedPage = pages.find((p) => p.page_url === pageUrl) ?? null;
  const siteSummary = summary[device];

  /** Switch collection on for the selected site. */
  async function enableCollection() {
    if (!websiteId || enabling) return;
    setEnabling(true);
    try {
      const res = await fetch(`/api/websites/${websiteId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ heatmap_enabled: true }),
      });
      if (res.ok) setEnabled((prev) => ({ ...prev, [websiteId]: true }));
    } finally {
      setEnabling(false);
    }
  }

  async function disableCollection() {
    if (!websiteId || enabling) return;
    setEnabling(true);
    try {
      const res = await fetch(`/api/websites/${websiteId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ heatmap_enabled: false }),
      });
      if (res.ok) setEnabled((prev) => ({ ...prev, [websiteId]: false }));
    } finally {
      setEnabling(false);
    }
  }

  // Segment params are omitted entirely when set to "all" — the backend reads an
  // absent param as "don't filter".
  const segmentQuery = useMemo(() => {
    const params = new URLSearchParams();
    params.set("device", device);
    if (visitor !== "all") params.set("visitor_type", visitor);
    if (source !== "all") params.set("source", source);
    return params.toString();
  }, [device, visitor, source]);

  useEffect(() => {
    pageUrlRef.current = pageUrl;
  }, [pageUrl]);

  // Pages + site summary for the selected website and segment. A site that has
  // never collected has nothing to fetch, but one that collected and was then
  // switched off keeps its history until the retention purge — so this is
  // gated on having a website, not on `collecting`.
  useEffect(() => {
    if (!websiteId) return;
    let cancelled = false;
    (async () => {
      const [pageList, summaryData] = await Promise.all([
        // Unpaginated by design: the endpoint aggregates the per-segment rows
        // to one entry per page and returns the busiest 500, so there is no
        // `meta.next` to follow and no truncated read to mistake for a
        // complete one.
        fetch(`/api/heatmap/pages?website=${websiteId}&${segmentQuery}`)
          .then((r) => (r.ok ? r.json() : []))
          .catch(() => []),
        fetch(`/api/heatmap/summary?website=${websiteId}&${segmentQuery}`)
          .then((r) => (r.ok ? r.json() : {}))
          .catch(() => ({})),
      ]);
      if (cancelled) return;
      const list = Array.isArray(pageList) ? (pageList as PageStats[]) : [];
      setPages(list);
      setSummary((summaryData as typeof summary) ?? {});
      const current = pageUrlRef.current;
      if (!current || !list.some((p) => p.page_url === current)) {
        setPageUrl(list[0]?.page_url ?? "");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [websiteId, segmentQuery]);

  // Activity cells, tagged with the selection they belong to. Deriving
  // "loading" from that tag rather than storing a flag is what stops a stale
  // spinner: the previous version set the flag in the selector handlers but
  // returned early for the scroll map without ever clearing it, so switching to
  // Scroll left a spinner running forever over the empty state.
  const requestKey = `${websiteId}|${pageUrl}|${kind}|${segmentQuery}`;
  const [result, setResult] = useState<{ key: string; cells: Cell[] } | null>(null);

  useEffect(() => {
    if (!websiteId || !pageUrl || kind === "scroll") return;
    let cancelled = false;
    (async () => {
      const data = await fetch(
        `/api/heatmap/activity?website=${websiteId}&page_url=${encodeURIComponent(
          pageUrl
        )}&kind=${kind}&${segmentQuery}`
      )
        .then((r) => (r.ok ? r.json() : []))
        .catch(() => []);
      if (cancelled) return;
      setResult({ key: requestKey, cells: Array.isArray(data) ? (data as Cell[]) : [] });
    })();
    return () => {
      cancelled = true;
    };
  }, [websiteId, pageUrl, kind, segmentQuery, requestKey]);

  const cells = useMemo(
    () => (result?.key === requestKey ? result.cells : []),
    [result, requestKey]
  );
  const loadingCells =
    kind !== "scroll" && Boolean(websiteId) && Boolean(pageUrl) && result?.key !== requestKey;

  // The backdrop screenshot. Snapshots are per page + device — segments share
  // one, because a snapshot is a picture of a page, not of a cohort.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const data =
        websiteId && pageUrl ? await fetchSnapshot(websiteId, pageUrl, device) : null;
      if (!cancelled) setSnapshot(data);
    })();
    return () => {
      cancelled = true;
    };
  }, [websiteId, pageUrl, device]);

  async function requestCapture() {
    if (!websiteId || !pageUrl) return;
    const previous = snapshot?.captured_at ?? null;
    setCapturing(true);
    setCaptureError(null);
    try {
      const queued = await fetch("/api/heatmap/snapshot/refresh", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ website: websiteId, page_url: pageUrl, device }),
      });
      if (!queued.ok) {
        // The backend answers 503 when Chromium is not installed. Saying so
        // beats the old behaviour of polling for thirty-six seconds and then
        // going quiet, which was indistinguishable from a slow capture.
        const detail = await queued
          .json()
          .then((body) => (body?.detail as string) ?? null)
          .catch(() => null);
        setCaptureError(
          detail ?? `Capture could not be queued (HTTP ${queued.status}).`
        );
        return;
      }
      // Capture runs in Celery, so nothing is ready when the request returns.
      // Poll for a change rather than making the operator reload. A page can
      // legitimately take ~30s (navigation + settle), so allow for that.
      for (let attempt = 0; attempt < 12; attempt++) {
        await new Promise((r) => setTimeout(r, 3000));
        const fresh = await fetchSnapshot(websiteId, pageUrl, device);
        if (!fresh) continue;
        setSnapshot(fresh);
        const settled =
          fresh.status !== "pending" &&
          (fresh.status !== "ready" || fresh.captured_at !== previous);
        if (settled) break;
      }
    } finally {
      setCapturing(false);
    }
  }

  // ---- geometry -----------------------------------------------------------
  // The overlay's y axis is a percentage of the full page height, so the render
  // aspect has to match the page's real aspect or nothing lines up. Three
  // sources, best first — this used to be a "page height x1-4" slider the
  // operator had to eyeball.
  const referenceWidth = snapshot?.width || REFERENCE_WIDTH[device];
  const renderWidth = Math.max(0, Math.min(availableWidth, referenceWidth));

  const geometryAspect =
    snapshot?.status === "ready" && snapshot.width > 0 && snapshot.height > 0
      ? snapshot.height / snapshot.width
      : selectedPage && selectedPage.page_height > 0 && selectedPage.viewport_width > 0
        ? selectedPage.page_height / selectedPage.viewport_width
        : null;

  const aspect = geometryAspect ?? manualAspect ?? FALLBACK_ASPECT;
  const renderHeight = Math.round(renderWidth * aspect);

  const aspectSource =
    snapshot?.status === "ready" && snapshot.height > 0
      ? "screenshot"
      : geometryAspect !== null
        ? "snippet"
        : "estimate";

  // ---- derived stats ------------------------------------------------------
  const totalEvents = cells.reduce((s, c) => s + c.count, 0);
  const maxValue = Math.max(0, ...cells.map((c) => c.count));

  const scrollStops = scrollStopsFrom(selectedPage?.scroll_histogram ?? null);
  const hasScrollData = scrollStops.length > 0;
  const maxScroll = selectedPage?.max_scroll_percent ?? siteSummary?.max_scroll_percent ?? 0;

  const topHotspots = useMemo(
    () => [...cells].sort((a, b) => b.count - a.count).slice(0, 6),
    [cells]
  );

  const overlayCells = useMemo(
    () => cells.map((c) => ({ x: c.x, y: c.y, count: c.count })),
    [cells]
  );

  const showEmptyState = !loadingCells && kind !== "scroll" && cells.length === 0;
  const showScrollEmpty = kind === "scroll" && !hasScrollData;

  return (
    <div className="space-y-6">
      {/* Toolbar */}
      <Card>
        <CardContent className="space-y-4 p-4">
          <div className="grid gap-4 lg:grid-cols-4">
            <div>
              <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
                Website
              </label>
              <Select value={websiteId} onValueChange={setWebsiteId}>
                <SelectTrigger className="w-full">
                  <SelectValue placeholder="Select a website" />
                </SelectTrigger>
                <SelectContent>
                  {websites.map((w) => (
                    <SelectItem key={w.id} value={w.id}>
                      {/* Marked in the list rather than hidden from it: a site
                          you cannot find is indistinguishable from a site that
                          was never added, and enabling collection is the whole
                          reason to come looking for one. */}
                      {w.name || w.domain}
                      {enabled[w.id] ? "" : " · off"}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div>
              <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
                Page
              </label>
              <Select value={pageUrl} onValueChange={setPageUrl} disabled={!pages.length}>
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
                Visitors
              </label>
              <Select value={visitor} onValueChange={(v) => setVisitor(v as VisitorFilter)}>
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {VISITOR_OPTIONS.map((o) => (
                    <SelectItem key={o.value} value={o.value}>
                      {o.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div>
              <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
                Traffic source
              </label>
              <Select value={source} onValueChange={(v) => setSource(v as SourceFilter)}>
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {SOURCE_OPTIONS.map((o) => (
                    <SelectItem key={o.value} value={o.value}>
                      {o.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="flex flex-wrap items-end gap-4">
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
                    onClick={() => setDevice(d.value)}
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
                    onClick={() => setKind(m.value)}
                  >
                    <m.icon className="h-4 w-4" />
                    {m.label}
                  </Button>
                ))}
              </div>
            </div>

            <div>
              <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
                Backdrop
              </label>
              <div className="inline-flex rounded-md border bg-muted p-0.5">
                {BACKDROPS.map((b) => (
                  <Button
                    key={b.value}
                    type="button"
                    variant={backdrop === b.value ? "default" : "ghost"}
                    size="sm"
                    className="gap-1.5"
                    onClick={() => setBackdrop(b.value)}
                  >
                    <b.icon className="h-4 w-4" />
                    {b.label}
                  </Button>
                ))}
              </div>
            </div>

            {backdrop === "snapshot" && pageUrl && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="gap-1.5"
                onClick={requestCapture}
                disabled={capturing}
              >
                {capturing ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Camera className="h-4 w-4" />
                )}
                {snapshot?.status === "ready" ? "Recapture" : "Capture"}
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Collection status. Behaviour analytics is opt-in per site — the
          snippet is one shared file, so without this switch every client site
          carrying it was streaming click and scroll data whether or not anyone
          had asked for a heatmap of it. */}
      {website && !collecting && (
        <Card className="border-amber-500/40 bg-amber-500/5">
          <CardContent className="flex flex-wrap items-center justify-between gap-4 p-4">
            <div className="min-w-0">
              <p className="text-sm font-semibold">
                Heatmap collection is off for {website.name || website.domain}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                Behaviour tracking is enabled per site. Turn it on and the
                tracking snippet starts recording clicks, movement and scroll
                depth on the next pageview — no re-paste needed. Anything shown
                below is history from before it was switched off.
              </p>
            </div>
            <Button
              type="button"
              size="sm"
              className="gap-1.5"
              onClick={enableCollection}
              disabled={enabling}
            >
              {enabling ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Power className="h-4 w-4" />
              )}
              Enable heatmap
            </Button>
          </CardContent>
        </Card>
      )}
      {website && collecting && (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span className="inline-flex h-2 w-2 rounded-full bg-emerald-500" />
          Collecting behaviour data for {website.name || website.domain}.
          <button
            type="button"
            onClick={disableCollection}
            disabled={enabling}
            className="underline underline-offset-2 hover:text-foreground disabled:opacity-50"
          >
            Turn off
          </button>
        </div>
      )}

      {captureError && (
        <div className="rounded-lg border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm text-muted-foreground">
          {captureError}
        </div>
      )}

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
            <div className="text-2xl font-bold">{maxScroll}%</div>
            <p className="text-xs text-muted-foreground">Deepest page region reached</p>
          </CardContent>
        </Card>
      </div>

      {/* Heatmap */}
      <Card>
        <CardContent className="p-4">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-2 text-sm">
              {kind === "scroll" ? (
                <Badge variant="default">
                  {maxScroll}% deepest reach
                  {hasScrollData ? ` · ${scrollStops.length} depth bands` : ""}
                </Badge>
              ) : kind === "rage" ? (
                <Badge variant="destructive">{totalEvents} rage clicks</Badge>
              ) : (
                <Badge variant={kind === "click" ? "default" : "secondary"}>
                  {totalEvents} {kind === "click" ? "clicks" : "move samples"}
                </Badge>
              )}
              {kind !== "scroll" && maxValue > 0 && (
                <span className="text-xs text-muted-foreground">peak cell ×{maxValue}</span>
              )}
              <span className="text-xs text-muted-foreground">
                {renderWidth}×{renderHeight}px ·{" "}
                {aspectSource === "screenshot"
                  ? "sized from the screenshot"
                  : aspectSource === "snippet"
                    ? "sized from the page height the snippet reported"
                    : "estimated page height"}
              </span>
            </div>

            {/* Only offered when neither source knows the real geometry — rows
                written before the snippet started reporting page height. */}
            {aspectSource === "estimate" && (
              <div className="flex items-center gap-2">
                <span className="text-xs text-muted-foreground">Page height</span>
                <input
                  type="range"
                  min={1}
                  max={6}
                  step={0.25}
                  value={manualAspect ?? FALLBACK_ASPECT}
                  onChange={(e) => setManualAspect(Number(e.target.value))}
                  className="w-32"
                />
                <span className="text-xs tabular-nums text-muted-foreground">
                  ×{(manualAspect ?? FALLBACK_ASPECT).toFixed(2)}
                </span>
              </div>
            )}
          </div>

          <div ref={frameRef} className="w-full">
            <div
              className="relative overflow-hidden rounded-lg border bg-muted"
              style={{ width: renderWidth || "100%", height: renderHeight || 400 }}
            >
              {website && pageUrl && renderWidth > 0 && (
                <Backdrop
                  mode={backdrop}
                  snapshot={snapshot}
                  pageUrl={pageUrl}
                  width={renderWidth}
                  height={renderHeight}
                  capturing={capturing}
                  onCapture={requestCapture}
                />
              )}

              {kind !== "scroll" && overlayCells.length > 0 && renderWidth > 0 && (
                <HeatmapOverlay
                  cells={overlayCells}
                  width={renderWidth}
                  height={renderHeight}
                  intensity={kind === "move" ? 0.55 : 0.68}
                  gradient={kind === "rage" ? RAGE_GRADIENT : undefined}
                />
              )}

              {kind === "scroll" && hasScrollData && (
                <ScrollOverlay stops={scrollStops} height={renderHeight} />
              )}

              {loadingCells && (
                <div className="absolute inset-0 z-20 flex items-center justify-center bg-background/40">
                  <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                </div>
              )}
              {showEmptyState && (
                <div className="absolute inset-x-0 top-1/3 z-20 text-center text-sm text-muted-foreground">
                  <span className="rounded bg-background/85 px-3 py-1.5">
                    No {kind} data for this selection yet
                  </span>
                </div>
              )}
              {showScrollEmpty && (
                <div className="absolute inset-x-0 top-1/3 z-20 text-center text-sm text-muted-foreground">
                  <span className="rounded bg-background/85 px-3 py-1.5">
                    No scroll depth data for this selection yet
                  </span>
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
                  <li key={`${c.x}-${c.y}-${i}`} className="flex items-baseline gap-2 text-xs">
                    <span className="w-14 shrink-0 font-mono text-muted-foreground">
                      {c.x}%,{c.y}%
                    </span>
                    <span
                      className="min-w-0 flex-1 truncate font-medium"
                      title={c.element || undefined}
                    >
                      {c.element || (kind === "rage" ? "Unattributed rage" : "Unattributed click")}
                    </span>
                    <span className="shrink-0 tabular-nums text-muted-foreground">
                      ×{c.count}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <p className="mt-2 text-xs text-muted-foreground">
            {kind === "scroll"
              ? "The page is tinted by how many visitors reached each depth — warm where nearly everyone saw, cold where almost nobody did. The dashed line marks the average fold, where half the audience has dropped away."
              : `Positions come from the tracking snippet as percentages of the page, rendered here at ${renderWidth}px wide. Capture a screenshot for a backdrop that lines up exactly.`}
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
