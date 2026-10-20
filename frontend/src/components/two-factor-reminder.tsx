"use client";

import { useState } from "react";
import Link from "next/link";
import { ShieldAlert, X } from "lucide-react";

// Daily nudge for accounts without 2FA. "Remind me tomorrow" hides it for
// 24 hours on the server, so it comes back on every device the next day.
export function TwoFactorReminder() {
  const [hidden, setHidden] = useState(false);
  if (hidden) return null;

  async function dismiss() {
    setHidden(true);
    await fetch("/api/auth/2fa-reminder", { method: "POST" }).catch(() => undefined);
  }

  return (
    <div className="mx-4 mt-4 flex flex-col gap-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-amber-900 sm:flex-row sm:items-center dark:border-amber-900/60 dark:bg-amber-950/40 dark:text-amber-200 md:mx-6">
      <ShieldAlert className="hidden h-5 w-5 shrink-0 sm:block" aria-hidden />
      <p className="flex-1 text-sm">
        <strong className="font-semibold">Protect your account and your client passwords.</strong>{" "}
        Turn on two-factor authentication. It takes 2 minutes.
      </p>
      <div className="flex items-center gap-2">
        <Link
          href="/2fa/setup"
          className="inline-flex h-9 items-center rounded-lg bg-amber-600 px-3 text-sm font-semibold text-white hover:bg-amber-700"
        >
          Enable now
        </Link>
        <button
          type="button"
          onClick={dismiss}
          className="inline-flex h-9 items-center gap-1 rounded-lg px-3 text-sm font-medium hover:bg-amber-100 dark:hover:bg-amber-900/40"
        >
          <X className="h-4 w-4" aria-hidden />
          Remind me tomorrow
        </button>
      </div>
    </div>
  );
}
