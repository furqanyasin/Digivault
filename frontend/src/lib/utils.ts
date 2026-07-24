import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

const DATE_FMT = new Intl.DateTimeFormat("en-GB", {
  year: "numeric", month: "short", day: "numeric",
});

const DATETIME_FMT = new Intl.DateTimeFormat("en-GB", {
  year: "numeric", month: "short", day: "numeric",
  hour: "2-digit", minute: "2-digit",
});

export function fmtDate(d: string | number | Date | null | undefined): string {
  if (!d) return "—";
  try { return DATE_FMT.format(new Date(d)); } catch { return String(d); }
}

export function fmtDateTime(d: string | number | Date | null | undefined): string {
  if (!d) return "—";
  try { return DATETIME_FMT.format(new Date(d)); } catch { return String(d); }
}

export function fmtRelative(d: string | number | Date | null | undefined): string {
  if (!d) return "—";
  const date = new Date(d);
  const diffSec = Math.round((Date.now() - date.getTime()) / 1000);
  if (diffSec < 60) return "just now";
  const diffMin = Math.round(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.round(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.round(diffHr / 24);
  if (diffDay === 1) return "Yesterday";
  if (diffDay < 7) return `${diffDay}d ago`;
  return fmtDate(d);
}
