"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Bell, AlertTriangle, Check } from "lucide-react";
import { fmtRelative } from "@/lib/utils";
import type { Notification } from "@/lib/api";

const POLL_MS = 60_000;

const isCritical = (s: string) => s === "critical" || s === "high";

/** Unread alert count and the recent feed.
 *
 *  Polls once a minute rather than using the Channels WebSocket that already
 *  exists at ws/alerts/. The consumer authenticates from a JWT passed as a
 *  subprotocol, and this app keeps the token in an httpOnly cookie that client
 *  JS cannot read — so wiring the socket needs either cookie auth in the
 *  consumer or a short-lived WS-token endpoint, plus nginx WS proxying in
 *  production. Polling delivers the same feed today with no infrastructure.
 */
export function NotificationBell() {
  const [items, setItems] = useState<Notification[]>([]);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    const res = await fetch("/api/notifications?page_size=15", { cache: "no-store" });
    if (!res.ok) return;
    const json = await res.json().catch(() => ({}));
    const payload = json?.data ?? json;
    const rows: Notification[] = Array.isArray(payload) ? payload : (payload?.results ?? []);
    setItems(rows);
  }, []);

  useEffect(() => {
    let cancelled = false;
    // The first fetch is deferred rather than called in the effect body: a
    // synchronous setState there causes a cascading render, which
    // react-hooks/set-state-in-effect rightly rejects.
    const first = setTimeout(() => { if (!cancelled) load(); }, 0);
    const poll = setInterval(load, POLL_MS);
    return () => {
      cancelled = true;
      clearTimeout(first);
      clearInterval(poll);
    };
  }, [load]);

  // Click-away close; a panel that traps you is worse than no panel.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  const unread = items.filter((n) => !n.read);

  async function markAllRead() {
    setBusy(true);
    try {
      // Empty body clears everything unread for the team — see
      // MarkNotificationsReadView.
      const res = await fetch("/api/notifications/mark-read", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      if (res.ok) await load();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div ref={boxRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label={unread.length ? `Alerts, ${unread.length} unread` : "Alerts"}
        aria-expanded={open}
        className="relative flex w-full items-center gap-2 rounded-md px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
      >
        <Bell className="h-4 w-4 shrink-0" aria-hidden />
        Alerts
        {unread.length > 0 && (
          <span className="ml-auto min-w-5 rounded-full bg-red-600 px-1.5 text-center text-[11px] font-semibold leading-5 text-white">
            {unread.length > 99 ? "99+" : unread.length}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute left-0 right-0 top-full z-50 mt-1 overflow-hidden rounded-lg border bg-popover shadow-lg">
          <div className="flex items-center justify-between gap-2 border-b px-3 py-2">
            <span className="text-xs font-semibold">
              Alerts{unread.length > 0 && ` · ${unread.length} unread`}
            </span>
            {unread.length > 0 && (
              <button
                type="button"
                onClick={markAllRead}
                disabled={busy}
                className="flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground disabled:opacity-50"
              >
                <Check className="h-3 w-3" aria-hidden />
                Mark all read
              </button>
            )}
          </div>

          {items.length === 0 ? (
            <p className="px-3 py-6 text-center text-xs text-muted-foreground">
              No alerts yet. They appear here once a rule fires.
            </p>
          ) : (
            <ul className="max-h-80 overflow-y-auto">
              {items.map((n) => (
                <li
                  key={n.id}
                  className={`border-b px-3 py-2 last:border-0 ${n.read ? "" : "bg-muted/40"}`}
                >
                  <div className="flex items-start gap-1.5">
                    {isCritical(n.change_severity) && (
                      <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0 text-red-600" aria-hidden />
                    )}
                    <div className="min-w-0">
                      <p className="truncate text-xs font-medium">
                        {n.website_name || "Unknown site"}
                      </p>
                      <p className="truncate text-[11px] text-muted-foreground">
                        {n.change_description || n.channel}
                      </p>
                      <p className="text-[10px] text-muted-foreground/70">
                        {fmtRelative(n.delivered_at ?? n.created_at)}
                      </p>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}

          <Link
            href="/alerts"
            onClick={() => setOpen(false)}
            className="block border-t px-3 py-2 text-center text-xs text-muted-foreground hover:text-foreground"
          >
            Open Alerts
          </Link>
        </div>
      )}
    </div>
  );
}
