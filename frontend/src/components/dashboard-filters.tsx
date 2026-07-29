"use client";

import { useEffect, useRef, useTransition } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import flatpickr from "flatpickr";
import type { Instance as FlatpickrInstance } from "flatpickr/dist/types/instance";
import Choices from "choices.js";
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
  const choicesRef = useRef<Choices | null>(null);

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

  // --- Flatpickr: range mode, committing only once both ends are picked -----
  useEffect(() => {
    const el = dateRef.current;
    if (!el) return;
    // flatpickr()'s signature allows an array return for selector input; given a
    // single element it is always one instance.
    const instance = flatpickr(el, {
      mode: "range",
      dateFormat: "Y-m-d",
      maxDate: "today",
      defaultDate: from && to ? [from, to] : undefined,
      onClose: (selected) => {
        // A single click in range mode leaves one date — half a range is not a
        // range, so we wait rather than guessing the other end.
        if (selected.length === 2) {
          apply({ from: ISO(selected[0]), to: ISO(selected[1]), days: null });
        }
      },
    });
    pickerRef.current = instance;
    return () => instance.destroy();
    // Re-created when the URL range changes so the input reflects the real state.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [from, to]);

  // --- Choices: searchable client filter ------------------------------------
  useEffect(() => {
    const el = selectRef.current;
    if (!el) return;
    const instance = new Choices(el, {
      searchEnabled: true,
      shouldSort: false,
      itemSelectText: "",
      allowHTML: false,
      searchPlaceholderValue: "Search clients…",
    });
    choicesRef.current = instance;
    const onChange = (e: Event) => {
      const value = (e.target as HTMLSelectElement).value;
      apply({ client: value || null });
    };
    el.addEventListener("change", onChange);
    return () => {
      el.removeEventListener("change", onChange);
      instance.destroy();
    };
    // Rebuilt only when the option list itself changes; re-running on every
    // param change would tear down the widget mid-interaction.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clients]);

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
          className="h-[30px] w-[172px] cursor-pointer rounded-lg border bg-card pl-8 pr-2 text-xs outline-none focus:border-primary"
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
        <select ref={selectRef} aria-label="Filter by client" defaultValue={client ?? ""}>
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
