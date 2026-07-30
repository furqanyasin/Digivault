"use client";

import { useEffect, useRef, useTransition } from "react";
import { useRouter, useSearchParams } from "next/navigation";
// flatpickr is imported dynamically inside the effect, NOT at module scope:
// these vanilla widgets touch `document` while they evaluate, which throws
// "document is not defined" during SSR, fails this subtree's server render and
// makes React abort the Suspense boundary (#419) and re-render on the client.
// Type-only imports are erased at compile time, so they are safe up here.
import type { Instance as FlatpickrInstance } from "flatpickr/dist/types/instance";
import { CalendarRange, Loader2, X } from "lucide-react";
import "flatpickr/dist/flatpickr.min.css";

interface Props {
  /** Rolling-window presets, in days. */
  presets?: number[];
}

const ISO = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

/** One filter row above everything it scopes — never per-chart filters.
 *
 *  State lives in the URL rather than component state, so the server component
 *  re-renders with the new window and every chart on the page moves together.
 *  That also makes a filtered view linkable and survives a refresh.
 *
 *  The client dropdown that used to live here was removed: on a team whose
 *  websites aren't assigned to clients, every selection scoped the page to zero
 *  sites, which reads as a broken control. Filter by client on /clients and
 *  /websites, where the rows carry the assignment.
 */
export function DashboardFilters({ presets = [7, 14, 30, 90] }: Props) {
  const router = useRouter();
  const params = useSearchParams();
  const [pending, startTransition] = useTransition();

  const dateRef = useRef<HTMLInputElement>(null);
  const pickerRef = useRef<FlatpickrInstance | null>(null);

  const from = params.get("from");
  const to = params.get("to");
  const days = params.get("days");
  const activeDays = !from && !to ? Number(days) || 14 : null;

  /** Writes params and lets the server re-render. Nulls delete the key.
   *
   *  Reads the live URL rather than the `params` render snapshot: during a
   *  transition the snapshot can lag the address bar, so a second filter change
   *  landing mid-navigation would be computed against stale values and appear to
   *  do nothing. window.location is always current.
   */
  const apply = (patch: Record<string, string | null>) => {
    const current =
      typeof window === "undefined" ? params.toString() : window.location.search;
    const next = new URLSearchParams(current);
    for (const [k, v] of Object.entries(patch)) {
      if (v == null || v === "") next.delete(k);
      else next.set(k, v);
    }
    startTransition(() => router.push(`?${next.toString()}`, { scroll: false }));
  };

  // The picker's listener is bound inside a mount-only effect, so it would
  // otherwise capture a stale `apply` and silently drop whichever filter changed
  // since. A ref keeps it calling the current version.
  const applyRef = useRef(apply);
  // Updated in an effect, not during render: writing to a ref while rendering is
  // a side effect and React can discard or replay that render.
  useEffect(() => {
    applyRef.current = apply;
  });

  // --- Flatpickr: range mode, committing only once both ends are picked -----
  // Created ONCE, then kept in step by the sync effect below.
  //
  // It used to be keyed on [from, to] so the input would show the current range.
  // That silently broke the preset buttons: switching to a preset re-ran this
  // effect, and flatpickr's destroy() fires onClose, which re-committed the range
  // it still held and undid the click. Creating the instance once removes that
  // teardown-commit loop entirely.
  useEffect(() => {
    let cancelled = false;
    let instance: FlatpickrInstance | null = null;

    (async () => {
      const el = dateRef.current;
      if (!el) return;
      const flatpickr = (await import("flatpickr")).default;
      // A later run may have cleaned up while the chunk was loading.
      if (cancelled || !dateRef.current) return;
      // flatpickr()'s signature allows an array return for selector input; given
      // a single element it is always one instance.
      instance = flatpickr(el, {
        mode: "range",
        dateFormat: "Y-m-d",
        maxDate: "today",
        onClose: (selected) => {
          if (cancelled) return;
          // A single click in range mode leaves one date — half a range is not a
          // range, so we wait rather than guessing the other end.
          if (selected.length === 2) {
            applyRef.current({ from: ISO(selected[0]), to: ISO(selected[1]), days: null });
          }
        },
      });
      pickerRef.current = instance;
      // Seed from the URL, without firing onChange. Read off the URL directly
      // rather than the render-scope values so this effect stays mount-only —
      // re-running it is exactly the bug described above.
      const sp = new URLSearchParams(window.location.search);
      const f = sp.get("from");
      const t = sp.get("to");
      if (f && t) instance.setDate([f, t], false);
    })();

    return () => {
      cancelled = true;
      instance?.destroy();
      pickerRef.current = null;
    };
  }, []);

  // Reflect the URL in the input — including clearing it when a preset takes
  // over. `false` suppresses onChange so this never loops back into apply().
  useEffect(() => {
    const instance = pickerRef.current;
    if (!instance) return;
    if (from && to) instance.setDate([from, to], false);
    else instance.clear(false);
  }, [from, to]);

  const rangeLabel = from && to ? `${from} → ${to}` : "";

  return (
    <div className="flex flex-wrap items-center gap-2">
      {/* Rolling presets. Selection is marked, not merely hovered. */}
      <div className="flex items-center rounded-lg border bg-card p-0.5">
        {presets.map((d) => (
          <button
            key={d}
            type="button"
            onClick={() => apply({ days: String(d), from: null, to: null })}
            aria-pressed={activeDays === d}
            className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
              activeDays === d
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:bg-muted"
            }`}
          >
            {d}d
          </button>
        ))}
      </div>

      <div className="relative">
        <CalendarRange className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
        <input
          ref={dateRef}
          readOnly
          placeholder="Custom range"
          aria-label="Custom date range"
          // Wide enough for "2026-07-03 to 2026-07-10" without truncating.
          className="h-[30px] w-[210px] cursor-pointer rounded-lg border bg-card pl-8 pr-2 text-xs outline-none focus:border-primary"
        />
      </div>

      {rangeLabel && (
        <button
          type="button"
          onClick={() => apply({ from: null, to: null, days: "14" })}
          className="flex items-center gap-1 rounded-full border px-2 py-1 text-xs text-muted-foreground hover:bg-muted"
        >
          {rangeLabel}
          <X className="h-3 w-3" />
        </button>
      )}

      {pending && (
        <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" aria-label="Updating" />
      )}
    </div>
  );
}
