import Link from "next/link";
import { ChevronLeft } from "lucide-react";
import { getAccessToken } from "@/lib/server-token";
import { api } from "@/lib/api";
import type { NotificationChannel } from "@/lib/api";
import { NotificationChannelsClient } from "@/components/notification-channels-client";

export default async function NotificationChannelsPage() {
  const token = await getAccessToken();
  const channels = await api
    .get<NotificationChannel[]>("/api/v1/notification-channels/", token ?? "")
    .catch(() => [] as NotificationChannel[]);

  return (
    <div className="p-8 space-y-8">
      <div className="space-y-1">
        <Link
          href="/monitors"
          className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors w-fit"
        >
          <ChevronLeft className="h-4 w-4" />
          All monitors
        </Link>
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold tracking-tight">Notification Channels</h1>
            <p className="text-muted-foreground mt-1">
              Configure where alerts are sent when a monitor goes down or recovers
            </p>
          </div>
        </div>
      </div>

      <NotificationChannelsClient initialChannels={channels} />
    </div>
  );
}
