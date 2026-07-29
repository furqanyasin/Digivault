"use client";

import { useEffect, useRef, useTransition } from "react";
import { useRouter, useSearchParams } from "next/navigation";
// Both widgets are imported dynamically inside their effects, NOT at module
// scope: choices.js touches `document` while it evaluates, which throws
// "document is not defined" during SSR, fails this subtree's server render and
// makes React abort the Suspense boundary (#419) and re-render on the client.
// Type-only imports are erased at compile time, so they are safe up here.
import type { Instance as FlatpickrInstance } from "flatpickr/dist/types/instance";
import type ChoicesType from "choices.js";
import { CalendarRange, Loader2, X } from "lucide-react";
import "flatpickr/dist/flatpickr.min.css";
import "choices.js/public/assets/styles/choices.min.css";

export interface ClientOption {
  id: string;
  name: string;
}

interface Props {
  clients: ClientOption[];
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
 */
export function DashboardFilters({ clients, presets = [7, 14, 30, 90] }: Props) {
  const router = useRouter();
  const params = useSearchParams();
  const [pending, startTransition] = useTransition();

  const dateRef = useRef<HTMLInputElement>(null);
  const pickerRef = useRef<FlatpickrInstance | null>(null);
  const selectRef = useRef<HTMLSelectElement>(null);
  const choicesRef = useRef<ChoicesType | null>(null);

  const from = params.get("from");
  const to = params.get("to");
  const days = params.get("days");
  const client = params.get("client");
  const activeDays = !from && !to ? Number(days) || 14 : null;

  /** Writes params and lets the server re-render. Nulls delete the key. */
  const apply = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(params.toString());
    for (const [k, v] of Object.entries(patch)) {
      if (v == null || v === "") next.delete(k);
      else next.set(k, v);
    }
    startTransition(() => router.push(`?${next.toString()}`, { scroll: false }));
  };

  // The vanilla widgets' listeners are bound inside effects that must not re-run
  // on every navigation (that would tear the widget down mid-interaction), so
  // they'd otherwise capture a stale `params` and silently drop whichever filter
  // changed since. A ref keeps them calling the current version.
  const applyRef = useRef(apply);
  applyRef.current = apply;

  // --- Flatpickr: range mode, committing only once both ends are picked -----
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
        defaultDate: from && to ? [from, to] : undefined,
        onClose: (selected) => {
          // A single click in range mode leaves one date — half a range is not a
          // range, so we wait rather than guessing the other end.
          if (selected.length === 2) {
            applyRef.current({ from: ISO(selected[0]), to: ISO(selected[1]), days: null });
          }
        },
      });
      pickerRef.current = instance;
    })();

    return () => {
      cancelled = true;
      instance?.destroy();
      pickerRef.current = null;
    };
    // Re-created when the URL range changes so the input reflects the real state.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [from, to]);

  // --- Choices: searchable client filter ------------------------------------
  // Built once per option list. The <select> is uncontrolled from React's point
  // of view because Choices replaces its DOM, so the selected option is pushed
  // in by the sync effect below rather than via a React value prop.
  useEffect(() => {
    let cancelled = false;
    let instance: ChoicesType | null = null;
    let el: HTMLSelectElement | null = null;

    const onChange = (e: Event) => {
      const value = (e.target as HTMLSelectElement).value;
      applyRef.current({ client: value || null });
    };

    (async () => {
      const Choices = (await import("choices.js")).default;
      el = selectRef.current;
      if (cancelled || !el) return;
      instance = new Choices(el, {
        searchEnabled: true,
        shouldSort: false,
        itemSelectText: "",
        allowHTML: false,
        searchPlaceholderValue: "Search clients…",
        searchResultLimit: 20,
      });
      choicesRef.current = instance;
      el.addEventListener("change", onChange);
      // The chunk may land after `client` was already read, so seed the visible
      // selection here too rather than waiting for the sync effect to re-fire.
      try {
        instance.setChoiceByValue(client ?? "");
      } catch {
        /* value not in the list — leave the widget alone */
      }
    })();

    return () => {
      cancelled = true;
      el?.removeEventListener("change", onChange);
      instance?.destroy();
      choicesRef.current = null;
    };
    // Rebuilt only when the option list itself changes; re-running on every
    // param change would tear down the widget mid-interaction.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clients]);

  // Keep the widget's visible selection in step with the URL. Without this the
  // dropdown snaps back to "All clients" after the navigation it triggered —
  // the filter is applied but the control looks like it reverted, which reads as
  // a broken filter. `defaultValue` can't do this job: React only honours it on
  // first render, and Choices owns the DOM afterwards.
  useEffect(() => {
    const instance = choicesRef.current;
    if (!instance) return;
    try {
      instance.setChoiceByValue(client ?? "");
    } catch {
      // Value no longer in the list (e.g. the client was deleted) — leaving the
      // widget as-is is better than throwing inside an effect.
    }
  }, [client, clients]);

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

      <div className="dv-choices w-[196px]">
        <select ref={selectRef} aria-label="Filter by client">
          <option value="">All clients</option>
          {clients.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
      </div>

      {pending && (
        <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" aria-label="Updating" />
      )}
    </div>
  );
}
