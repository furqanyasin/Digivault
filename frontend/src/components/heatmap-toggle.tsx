"use client";

import { useState } from "react";
import { Flame, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";

interface Props {
  websiteId: string;
  /** Optional: the frontend deploys separately from the backend, so a frontend
   *  that ships first sees this field missing and must still render. */
  enabled?: boolean;
}

/**
 * Per-site switch for behaviour analytics.
 *
 * The tracking snippet is one cached file every client pastes, so it cannot be
 * the thing that decides what gets collected — before this switch existed,
 * every site carrying the snippet streamed click, move and scroll data into the
 * heatmap tables whether or not anyone had asked for a heatmap of it.
 *
 * The gate is enforced server-side, which is why the copy promises the change
 * takes effect on the next pageview: the ingest starts (or stops) accepting the
 * data, and nobody has to re-paste anything.
 */
export function HeatmapToggle({ websiteId, enabled }: Props) {
  const [on, setOn] = useState(Boolean(enabled));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function toggle() {
    if (saving) return;
    const next = !on;
    setSaving(true);
    setError(null);
    try {
      const res = await fetch(`/api/websites/${websiteId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ heatmap_enabled: next }),
      });
      if (!res.ok) {
        setError("Could not save that. Try again.");
        return;
      }
      setOn(next);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="flex flex-wrap items-center justify-between gap-4 rounded-lg border p-4">
      <div className="min-w-0">
        <p className="flex items-center gap-2 text-sm font-medium">
          <Flame className="h-4 w-4 text-muted-foreground" />
          Heatmap &amp; behaviour tracking
          <span
            className={
              on
                ? "rounded-full bg-emerald-500/15 px-2 py-0.5 text-[11px] font-semibold text-emerald-600 dark:text-emerald-400"
                : "rounded-full bg-muted px-2 py-0.5 text-[11px] font-semibold text-muted-foreground"
            }
          >
            {on ? "On" : "Off"}
          </span>
        </p>
        <p className="mt-1 max-w-prose text-xs text-muted-foreground">
          {on
            ? "The snippet is recording clicks, mouse movement and scroll depth for this site. Turning it off stops collection on the next pageview — existing data stays until it ages out."
            : "Off by default, and enabled per site. Turn it on and the snippet already on this site starts recording clicks, mouse movement and scroll depth on the next pageview — no re-paste needed."}
        </p>
        {error && <p className="mt-1 text-xs text-destructive">{error}</p>}
      </div>
      <Button
        type="button"
        size="sm"
        variant={on ? "outline" : "default"}
        onClick={toggle}
        disabled={saving}
        className="gap-1.5"
      >
        {saving && <Loader2 className="h-4 w-4 animate-spin" />}
        {on ? "Turn off" : "Turn on"}
      </Button>
    </div>
  );
}
