"use client";

import { useState } from "react";
import { Mail, Server } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

interface Props {
  websiteId: string;
  hostingExpiresAt: string | null;
  hostingDaysUntilExpiry: number | null;
  smtpStatus: string | null;
  mxHosts: string[];
}

const SMTP_LABEL: Record<string, { text: string; cls: string }> = {
  ok: { text: "Mail server reachable", cls: "text-emerald-600" },
  unreachable: { text: "Mail server unreachable", cls: "text-red-600" },
  no_mx: { text: "No MX records", cls: "text-amber-600" },
  error: { text: "Check failed", cls: "text-muted-foreground" },
};

export function DomainExtras({
  websiteId,
  hostingExpiresAt,
  hostingDaysUntilExpiry,
  smtpStatus,
  mxHosts,
}: Props) {
  const [date, setDate] = useState(hostingExpiresAt ? hostingExpiresAt.slice(0, 10) : "");
  const [days, setDays] = useState<number | null>(hostingDaysUntilExpiry);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  async function save() {
    setSaving(true);
    setSaved(false);
    try {
      const res = await fetch(`/api/websites/${websiteId}/domain`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ hosting_expires_at: date || null }),
      });
      if (res.ok) {
        const data = await res.json();
        setDays(data?.hosting_days_until_expiry ?? null);
        setSaved(true);
      }
    } finally {
      setSaving(false);
    }
  }

  const smtp = smtpStatus ? SMTP_LABEL[smtpStatus] ?? SMTP_LABEL.error : null;

  return (
    <div className="space-y-4">
      <div className="space-y-1.5">
        <div className="flex items-center gap-2 text-sm font-medium">
          <Server className="h-4 w-4 text-muted-foreground" />
          Hosting expiry
          {days !== null && (
            <span className={`text-xs ${days <= 30 ? "text-amber-600 font-semibold" : "text-muted-foreground"}`}>
              ({days} days left)
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} className="h-8 w-44 text-sm" />
          <Button size="sm" variant="outline" onClick={save} disabled={saving}>
            {saving ? "Saving…" : "Save"}
          </Button>
          {saved && <span className="text-xs text-emerald-600">Saved</span>}
        </div>
        <p className="text-xs text-muted-foreground">
          Hosting renewal isn&apos;t in WHOIS — set it manually to get expiry reminders.
        </p>
      </div>

      {smtp && (
        <div className="flex items-center gap-2 text-sm">
          <Mail className="h-4 w-4 text-muted-foreground" />
          <span className={smtp.cls}>{smtp.text}</span>
          {mxHosts.length > 0 && (
            <span className="text-xs text-muted-foreground font-mono truncate max-w-[50%]" title={mxHosts.join(", ")}>
              {mxHosts[0]}
            </span>
          )}
        </div>
      )}
    </div>
  );
}
