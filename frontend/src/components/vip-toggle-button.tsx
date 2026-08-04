"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Star, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";

interface Props {
  websiteId: string;
  initialIsVip: boolean;
}

/** Pin a site to the dashboard's VIP section. PATCHes is_vip through the
 *  existing /api/websites/[id] proxy, which attaches the HttpOnly token. */
export function VipToggleButton({ websiteId, initialIsVip }: Props) {
  const router = useRouter();
  const [isVip, setIsVip] = useState(initialIsVip);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function toggle() {
    const next = !isVip;
    setSaving(true);
    setError("");
    // Optimistic: the only failure mode is the request itself, and it reverts.
    setIsVip(next);
    try {
      const res = await fetch(`/api/websites/${websiteId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_vip: next }),
      });
      if (!res.ok) throw new Error();
      router.refresh();
    } catch {
      setIsVip(!next);
      setError("Could not save. Try again.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <Button
        variant={isVip ? "default" : "outline"}
        size="sm"
        onClick={toggle}
        disabled={saving}
        aria-pressed={isVip}
        title={isVip ? "Remove from the dashboard VIP section" : "Pin to the dashboard VIP section"}
      >
        {saving ? (
          <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
        ) : (
          <Star className={`h-3.5 w-3.5 mr-1.5 ${isVip ? "fill-current" : ""}`} />
        )}
        {isVip ? "VIP" : "Mark VIP"}
      </Button>
      {error && <p className="text-xs text-red-600">{error}</p>}
    </div>
  );
}
