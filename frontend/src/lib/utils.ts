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
