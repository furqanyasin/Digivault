import { create } from "zustand";

export interface DashboardWindow {
  /** Rolling window in days. Null when an explicit range is set. */
  days: number | null;
  from: string | null;
  to: string | null;
  setDays: (days: number) => void;
  setRange: (from: string, to: string) => void;
}

export const DEFAULT_DAYS = 14;
export const MAX_DAYS = 90;

/** The date window the trend charts are scoped to.
 *
 *  This lives in a store rather than the URL because the window only affects two
 *  charts. Driving it through the router meant every preset click was a full
 *  server navigation: all ten dashboard endpoints refetched and the whole page
 *  re-rendered to change one series — about 1.2s per click. The server now sends
 *  the widest window once and the charts slice it locally, so switching is
 *  instant.
 *
 *  The URL is still kept in step (via replaceState, so no navigation) which
 *  keeps a filtered view linkable and survives a refresh.
 */
export const useDashboardWindow = create<DashboardWindow>((set) => ({
  days: DEFAULT_DAYS,
  from: null,
  to: null,
  setDays: (days) => {
    set({ days, from: null, to: null });
    syncUrl({ days: String(days), from: null, to: null });
  },
  setRange: (from, to) => {
    const [a, b] = from <= to ? [from, to] : [to, from];
    set({ days: null, from: a, to: b });
    syncUrl({ days: null, from: a, to: b });
  },
}));

function syncUrl(patch: Record<string, string | null>) {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  for (const [k, v] of Object.entries(patch)) {
    if (v == null) url.searchParams.delete(k);
    else url.searchParams.set(k, v);
  }
  // replaceState, not router.push: the point is to record the window without
  // asking the server to render the page again.
  window.history.replaceState(null, "", url.toString());
}

/** Read the window the page was opened with, so a linked URL still works. */
export function windowFromSearch(search: string): Pick<DashboardWindow, "days" | "from" | "to"> {
  const sp = new URLSearchParams(search);
  const iso = /^\d{4}-\d{2}-\d{2}$/;
  const from = sp.get("from");
  const to = sp.get("to");
  if (from && to && iso.test(from) && iso.test(to)) {
    return from <= to ? { days: null, from, to } : { days: null, from: to, to: from };
  }
  const n = Number(sp.get("days"));
  const days = Number.isFinite(n) && n > 0 ? Math.min(Math.trunc(n), MAX_DAYS) : DEFAULT_DAYS;
  return { days, from: null, to: null };
}

const pad = (n: number) => String(n).padStart(2, "0");
export const dayKey = (d: Date) =>
  `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

/** Every calendar day in the window, oldest first. */
export function windowDays(w: Pick<DashboardWindow, "days" | "from" | "to">): string[] {
  const out: string[] = [];
  if (w.from && w.to) {
    const cur = new Date(`${w.from}T00:00:00`);
    const end = new Date(`${w.to}T00:00:00`);
    while (cur <= end && out.length < MAX_DAYS) {
      out.push(dayKey(cur));
      cur.setDate(cur.getDate() + 1);
    }
    return out;
  }
  const today = new Date();
  for (let i = (w.days ?? DEFAULT_DAYS) - 1; i >= 0; i--) {
    const d = new Date(today);
    d.setDate(today.getDate() - i);
    out.push(dayKey(d));
  }
  return out;
}

export const rangeCaption = (w: Pick<DashboardWindow, "days" | "from" | "to">) =>
  w.from && w.to ? `${w.from} → ${w.to}` : `last ${w.days ?? DEFAULT_DAYS} days`;
