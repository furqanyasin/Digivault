"use client";

import { useEffect, useRef, useState } from "react";
import type { HeatmapGradient, HeatmapInstance } from "heatmap.js";

export interface HeatmapCell {
  x: number;
  y: number;
  count: number;
}

interface Props {
  cells: HeatmapCell[];
  /** Rendered width of the backdrop, in CSS px. */
  width: number;
  /** Rendered height of the backdrop, in CSS px. */
  height: number;
  gradient?: HeatmapGradient;
  /** 0..1 — how strongly the heat covers the page underneath. */
  intensity?: number;
}

interface HeatmapModule {
  create(config: {
    container: HTMLElement;
    radius?: number;
    maxOpacity?: number;
    minOpacity?: number;
    blur?: number;
    gradient?: HeatmapGradient;
  }): HeatmapInstance;
}

function loadHeatmap(): Promise<HeatmapModule> {
  return import("heatmap.js").then(
    (m) =>
      (m.default as unknown as HeatmapModule) ??
      (window as unknown as { h337: HeatmapModule }).h337
  );
}

// The data is a 100x100 grid of *percentages*, so one cell is 1% of the page
// wide and 1% of the page tall. On a page three screens long that cell is three
// times taller than it is wide, and heatmap.js only draws circles — a radius
// big enough to close the vertical gaps smears badly across the horizontal.
//
// So the canvas is rendered SQUARE (side = width) and stretched vertically with
// a CSS transform. In that square space one grid cell is square, a circular
// kernel covers it evenly, and the stretch turns each blob into exactly the
// ellipse the cell's real aspect calls for.
const GRID = 100;
// Kernel radius in grid units — ~2 cells, enough that neighbouring cells merge
// into a continuous field rather than reading as a dot grid.
const RADIUS_IN_CELLS = 2.1;
const MIN_RADIUS_PX = 6;

/**
 * The heatmap.js canvas layer.
 *
 * heatmap.js has no destroy/remove method — it appends a canvas to the
 * container and never offers to take it back. (An earlier version of this
 * component called `instance.remove()`, which does not exist: it type-checked
 * against a hand-written declaration and then threw `TypeError` at runtime on
 * every device/page/map-kind change, so the overlay worked exactly once per
 * page load.) Teardown here empties the container element instead.
 *
 * heatmap.js also forces `position: relative` onto its container, which would
 * knock an `absolute inset-0` overlay out of place. The element it owns is
 * therefore a plain inner div, wrapped by a positioned one we control.
 */
export function HeatmapOverlay({
  cells,
  width,
  height,
  gradient,
  intensity = 0.6,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  // heatmap.js arrives via a dynamic import, so the instance does not exist on
  // the first render. Keeping it in state (rather than a ref) is what makes the
  // painting effect re-run the moment it lands — with a ref, a data effect that
  // ran before the import resolved would find nothing to paint and never fire
  // again until the next selection change.
  const [instance, setInstance] = useState<HeatmapInstance | null>(null);

  // Re-create the instance when anything baked in at construction changes.
  // radius, gradient and canvas size are all read by heatmap.js when the
  // renderer is built, so they cannot be applied by setData alone.
  const radius = Math.max(
    MIN_RADIUS_PX,
    Math.round((width / GRID) * RADIUS_IN_CELLS)
  );
  const gradientKey = gradient ? JSON.stringify(gradient) : "default";

  useEffect(() => {
    const container = containerRef.current;
    if (!container || width <= 0) return;

    let disposed = false;
    loadHeatmap()
      .then((h337) => {
        if (disposed) return;
        // Drop any canvas from a previous configuration before adding another,
        // or they stack up one per re-render.
        container.replaceChildren();
        setInstance(
          h337.create({
            container,
            radius,
            maxOpacity: intensity,
            minOpacity: 0,
            blur: 0.78,
            ...(gradient ? { gradient } : {}),
          })
        );
      })
      .catch(() => {
        // A failed chunk load must not take the page down; the backdrop and
        // the hotspot list below it still tell the story.
      });

    return () => {
      disposed = true;
      container.replaceChildren();
    };
    // `gradientKey` stands in for `gradient`: it is an object literal from the
    // caller, so comparing it by identity would rebuild the canvas every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [width, radius, gradientKey, intensity]);

  // Feed the data separately so changing pages does not rebuild the canvas.
  // Percentage cells map onto the SQUARE grid space, so both axes scale against
  // `width` (the CSS transform below turns that back into the page's aspect).
  useEffect(() => {
    if (!instance || width <= 0) return;
    const max = Math.max(1, ...cells.map((c) => c.count));
    instance.setData({
      max,
      min: 0,
      data: cells.map((c) => ({
        x: Math.round((c.x / 100) * width),
        y: Math.round((c.y / 100) * width),
        value: c.count,
      })),
    });
  }, [instance, cells, width]);

  if (width <= 0) return null;

  const scaleY = height / width;

  return (
    <div
      className="pointer-events-none absolute inset-0 z-10 overflow-hidden"
      aria-hidden="true"
    >
      <div
        style={{
          width,
          height: width,
          transform: `scaleY(${scaleY})`,
          transformOrigin: "top left",
        }}
      >
        {/* heatmap.js owns this element outright, including its position. */}
        <div ref={containerRef} style={{ width, height: width }} />
      </div>
    </div>
  );
}
