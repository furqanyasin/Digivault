"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Bell, ExternalLink } from "lucide-react";

interface Channel { id: string; name: string; channel_type: string }
interface StatusPageSummary { slug: string; name: string; status: string; monitor_count: number }

const STATUS_STYLE: Record<string, string> = {
  operational: "text-emerald-600",
  degraded: "text-amber-600",
  outage: "text-red-600",
};

export function WebsiteAlertsStatus({
  websiteId,
  initialChannelId,
  statusPage,
}: {
  websiteId: string;
  initialChannelId: string | null;
  statusPage: StatusPageSummary | null;
}) {
  const [channels, setChannels] = useState<Channel[]>([]);
  const [channelId, setChannelId] = useState<string>(initialChannelId ?? "");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    (async () => {
      const res = await fetch("/api/notification-channels");
      if (res.ok) {
        const data = await res.json();
        setChannels(Array.isArray(data) ? data : (data?.results ?? []));
      }
    })();
  }, []);

  async function changeChannel(value: string) {
    setChannelId(value);
    setSaved(false);
    const res = await fetch(`/api/websites/${websiteId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ notification_channel: value || null }),
    });
    if (res.ok) setSaved(true);
  }

  return (
    <div className="space-y-4">
      {/* Alert channel */}
      <div className="space-y-1.5">
        <div className="flex items-center gap-2 text-sm font-medium">
          <Bell className="h-4 w-4 text-muted-foreground" />
          Alert channel
        </div>
        <div className="flex items-center gap-2">
          <select
            value={channelId}
            onChange={(e) => changeChannel(e.target.value)}
            className="border rounded-md px-2 py-1 text-sm bg-background min-w-[14rem]"
          >
            <option value="">Team default channels</option>
            {channels.map((c) => (
              <option key={c.id} value={c.id}>{c.name} ({c.channel_type})</option>
            ))}
          </select>
          {saved && <span className="text-xs text-emerald-600">Saved</span>}
        </div>
        <p className="text-xs text-muted-foreground">
          All of this site&apos;s alerts (uptime, domain/SSL/hosting expiry, SEO) go to this
          channel. Leave on &ldquo;Team default&rdquo; to use the team&apos;s active channels.
        </p>
      </div>

      {/* Status page */}
      {statusPage && (
        <div className="space-y-1.5 border-t pt-3">
          <div className="flex items-center gap-2 text-sm font-medium">
            Status page
            <span className={`text-xs capitalize ${STATUS_STYLE[statusPage.status] ?? "text-muted-foreground"}`}>
              · {statusPage.status}
            </span>
          </div>
          <Link
            href={`/status/${statusPage.slug}`}
            target="_blank"
            className="inline-flex items-center gap-1 text-sm text-blue-600 hover:underline font-mono"
          >
            /status/{statusPage.slug} <ExternalLink className="h-3 w-3" />
          </Link>
          <p className="text-xs text-muted-foreground">
            {statusPage.monitor_count} monitor{statusPage.monitor_count !== 1 ? "s" : ""} on this public page.
          </p>
        </div>
      )}
    </div>
  );
}
