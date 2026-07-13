"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Activity, Bell, ExternalLink } from "lucide-react";

interface Channel { id: string; name: string; channel_type: string }
interface StatusPageSummary { slug: string; name: string; status: string; monitor_count: number }

const STATUS_STYLE: Record<string, string> = {
  operational: "text-emerald-600",
  degraded: "text-amber-600",
  outage: "text-red-600",
};

function ChannelSelect({
  value,
  channels,
  emptyLabel,
  onChange,
  saved,
}: {
  value: string;
  channels: Channel[];
  emptyLabel: string;
  onChange: (v: string) => void;
  saved: boolean;
}) {
  return (
    <div className="flex items-center gap-2">
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="border rounded-md px-2 py-1 text-sm bg-background min-w-[14rem]"
      >
        <option value="">{emptyLabel}</option>
        {channels.map((c) => (
          <option key={c.id} value={c.id}>{c.name} ({c.channel_type})</option>
        ))}
      </select>
      {saved && <span className="text-xs text-emerald-600">Saved</span>}
    </div>
  );
}

export function WebsiteAlertsStatus({
  websiteId,
  initialChannelId,
  initialUptimeChannelId,
  statusPage,
}: {
  websiteId: string;
  initialChannelId: string | null;
  initialUptimeChannelId?: string | null;
  statusPage: StatusPageSummary | null;
}) {
  const [channels, setChannels] = useState<Channel[]>([]);
  const [channelId, setChannelId] = useState<string>(initialChannelId ?? "");
  const [uptimeChannelId, setUptimeChannelId] = useState<string>(initialUptimeChannelId ?? "");
  const [saved, setSaved] = useState(false);
  const [uptimeSaved, setUptimeSaved] = useState(false);

  useEffect(() => {
    (async () => {
      const res = await fetch("/api/notification-channels");
      if (res.ok) {
        const data = await res.json();
        setChannels(Array.isArray(data) ? data : (data?.results ?? []));
      }
    })();
  }, []);

  async function patchWebsite(body: Record<string, string | null>): Promise<boolean> {
    const res = await fetch(`/api/websites/${websiteId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    return res.ok;
  }

  async function changeChannel(value: string) {
    setChannelId(value);
    setSaved(false);
    if (await patchWebsite({ notification_channel: value || null })) setSaved(true);
  }

  async function changeUptimeChannel(value: string) {
    setUptimeChannelId(value);
    setUptimeSaved(false);
    if (await patchWebsite({ uptime_notification_channel: value || null })) setUptimeSaved(true);
  }

  return (
    <div className="space-y-4">
      {/* General alert channel */}
      <div className="space-y-1.5">
        <div className="flex items-center gap-2 text-sm font-medium">
          <Bell className="h-4 w-4 text-muted-foreground" />
          Website alert channel
        </div>
        <ChannelSelect
          value={channelId}
          channels={channels}
          emptyLabel="Team default channels"
          onChange={changeChannel}
          saved={saved}
        />
        <p className="text-xs text-muted-foreground">
          Script, domain/SSL/hosting expiry, and SEO alerts for this site go to this
          channel. Leave on &ldquo;Team default&rdquo; to use the team&apos;s active channels.
        </p>
      </div>

      {/* Uptime / downtime channel */}
      <div className="space-y-1.5 border-t pt-3">
        <div className="flex items-center gap-2 text-sm font-medium">
          <Activity className="h-4 w-4 text-muted-foreground" />
          Uptime alert channel
        </div>
        <ChannelSelect
          value={uptimeChannelId}
          channels={channels}
          emptyLabel="Same as website channel"
          onChange={changeUptimeChannel}
          saved={uptimeSaved}
        />
        <p className="text-xs text-muted-foreground">
          Downtime and recovery alerts route here, separately from other website
          notifications. Leave unset to use the website alert channel.
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
