"use client";

/* eslint-disable @next/next/no-img-element */

import { Camera, Globe, ImageOff, Loader2 } from "lucide-react";

export type BackdropMode = "snapshot" | "live" | "blank";

export interface Snapshot {
  id: string;
  page_url: string;
  device: string;
  status: "pending" | "ready" | "failed" | "blocked" | "unavailable";
  width: number;
  height: number;
  image_url: string | null;
  error_message: string;
  captured_at: string | null;
}

interface Props {
  mode: BackdropMode;
  snapshot: Snapshot | null;
  pageUrl: string;
  width: number;
  height: number;
  capturing: boolean;
  onCapture: () => void;
}

/**
 * What the heatmap is drawn on top of.
 *
 * Three sources, in descending order of usefulness:
 *
 * - **snapshot** — a screenshot captured server-side at a known width and
 *   height. The only one that reliably lines up, because the overlay's
 *   percentage grid maps onto exactly the geometry that was captured.
 * - **live** — an `<iframe>` of the page. Free and always current, but most
 *   origins refuse to be framed (`X-Frame-Options` / CSP `frame-ancestors`) and
 *   there is no way to detect that from the parent page: a blocked frame fires
 *   `load` just like a good one, and reading into it throws. So this mode is
 *   never silently chosen for a page with no snapshot — it says up front that a
 *   blank frame means the site refused, rather than leaving a grey box and an
 *   operator wondering which part is broken.
 * - **blank** — a measured grid. Honest about showing no page at all, and it is
 *   the right backdrop when what you want to read is the shape of the heat.
 */
export function Backdrop({
  mode,
  snapshot,
  pageUrl,
  width,
  height,
  capturing,
  onCapture,
}: Props) {
  if (mode === "snapshot" && snapshot?.image_url) {
    // Routed through the Next proxy, which attaches the bearer token the
    // backend's team-scoped image view requires. `captured_at` busts the
    // browser cache: a recapture reuses the same snapshot row, so the id on its
    // own is not a version.
    const src =
      `/api/heatmap/snapshot/image?id=${encodeURIComponent(snapshot.id)}` +
      `&v=${encodeURIComponent(snapshot.captured_at ?? "")}`;
    return (
      <img
        src={src}
        alt=""
        width={width}
        height={height}
        className="absolute inset-0 h-full w-full object-cover object-top"
      />
    );
  }

  if (mode === "live") {
    return (
      <>
        <iframe
          src={pageUrl}
          title="Live page preview"
          className="absolute inset-0 h-full w-full border-0 bg-white"
          loading="lazy"
          referrerPolicy="no-referrer"
          sandbox="allow-scripts allow-same-origin"
        />
        <p className="absolute inset-x-0 bottom-0 z-20 bg-black/70 px-2 py-1 text-center text-[10px] text-white/90">
          Live preview. If this stays blank the site refuses to be embedded —
          capture a screenshot instead for an overlay that lines up.
        </p>
      </>
    );
  }

  // Blank / no snapshot yet.
  return (
    <div className="absolute inset-0 bg-muted">
      <div
        className="absolute inset-0 opacity-40"
        style={{
          backgroundImage:
            "linear-gradient(to right, rgba(127,127,127,0.25) 1px, transparent 1px)," +
            "linear-gradient(to bottom, rgba(127,127,127,0.25) 1px, transparent 1px)",
          // One square per heatmap grid cell horizontally, so the backdrop
          // shows the actual resolution of the data being drawn on it.
          backgroundSize: `${width / 20}px ${width / 20}px`,
        }}
      />
      {mode === "snapshot" && (
        <div className="absolute inset-x-0 top-8 z-20 flex flex-col items-center gap-3 px-6 text-center">
          {snapshot?.status === "unavailable" ? (
            <>
              <ImageOff className="h-6 w-6 text-muted-foreground" />
              <p className="max-w-md text-sm text-muted-foreground">
                Screenshot capture is not enabled on this deployment. The overlay
                still renders — switch the backdrop to <strong>Live page</strong>{" "}
                or read it against the grid.
              </p>
            </>
          ) : snapshot?.status === "blocked" ? (
            <>
              <ImageOff className="h-6 w-6 text-muted-foreground" />
              <p className="max-w-md text-sm text-muted-foreground">
                The site refused the capture request. It will be retried on the
                next sweep.
                {snapshot.error_message ? ` (${snapshot.error_message})` : ""}
              </p>
            </>
          ) : (
            <>
              <Camera className="h-6 w-6 text-muted-foreground" />
              <p className="max-w-md text-sm text-muted-foreground">
                No screenshot of this page yet. Capture one so the overlay lands
                on the real page at the right size.
              </p>
              <button
                type="button"
                onClick={onCapture}
                disabled={capturing}
                className="inline-flex items-center gap-2 rounded-md border bg-background px-3 py-1.5 text-sm font-medium shadow-sm hover:bg-accent disabled:opacity-60"
              >
                {capturing ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Camera className="h-4 w-4" />
                )}
                {capturing ? "Capturing…" : "Capture screenshot"}
              </button>
            </>
          )}
          <a
            href={pageUrl}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1.5 text-xs text-muted-foreground underline underline-offset-2"
          >
            <Globe className="h-3 w-3" />
            Open the page
          </a>
        </div>
      )}
    </div>
  );
}
