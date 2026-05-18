import { notFound } from "next/navigation";
import type { Metadata } from "next";
import { CheckCircle, AlertTriangle, XCircle, RefreshCw } from "lucide-react";
import type { PublicStatusPage, UptimeBar } from "@/lib/api";
import { PublicStatusPageRefresh } from "@/components/public-status-page-refresh";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function getPage(slug: string): Promise<PublicStatusPage | null> {
  try {
    const res = await fetch(`${API_BASE}/api/v1/public/status/${slug}/`, {
      next: { revalidate: 10 },
    });
    if (res.status === 404) return null;
    const envelope = await res.json();
    return (envelope?.data ?? envelope) as PublicStatusPage;
  } catch {
    return null;
  }
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const page = await getPage(slug);
  if (!page) return { title: "Status Page Not Found" };

  return {
    title: `${page.name} — Status`,
    description: page.description || `Real-time status for ${page.name}`,
    robots: page.allow_indexing ? "index, follow" : "noindex, nofollow",
  };
}

// ── uptime bar strip ──────────────────────────────────────────────────────────

function barColor(status: UptimeBar["status"]) {
  switch (status) {
    case "up": return "bg-emerald-500";
    case "down": return "bg-red-500";
    case "degraded": return "bg-amber-400";
    default: return "bg-muted";
  }
}

function UptimeBars({ bars }: { bars: UptimeBar[] }) {
  return (
    <div className="flex items-end gap-px h-8">
      {bars.map((bar) => (
        <div
          key={bar.date}
          title={`${bar.date}: ${bar.status}`}
          className={`flex-1 rounded-sm h-full ${barColor(bar.status)} opacity-80 hover:opacity-100 transition-opacity`}
        />
      ))}
    </div>
  );
}

// ── status banner ─────────────────────────────────────────────────────────────

function StatusBanner({ status }: { status: PublicStatusPage["overall_status"] }) {
  if (status === "operational") {
    return (
      <div className="flex items-center gap-3 rounded-xl border border-emerald-200 bg-emerald-50 px-6 py-4">
        <CheckCircle className="h-6 w-6 text-emerald-600 shrink-0" />
        <div>
          <p className="font-semibold text-emerald-800">All Systems Operational</p>
          <p className="text-sm text-emerald-600">Everything is running smoothly.</p>
        </div>
      </div>
    );
  }
  if (status === "degraded") {
    return (
      <div className="flex items-center gap-3 rounded-xl border border-amber-200 bg-amber-50 px-6 py-4">
        <AlertTriangle className="h-6 w-6 text-amber-600 shrink-0" />
        <div>
          <p className="font-semibold text-amber-800">Degraded Performance</p>
          <p className="text-sm text-amber-600">Some services are experiencing issues.</p>
        </div>
      </div>
    );
  }
  return (
    <div className="flex items-center gap-3 rounded-xl border border-red-200 bg-red-50 px-6 py-4">
      <XCircle className="h-6 w-6 text-red-600 shrink-0" />
      <div>
        <p className="font-semibold text-red-800">Service Outage</p>
        <p className="text-sm text-red-600">One or more services are currently down.</p>
      </div>
    </div>
  );
}

// ── monitor row ───────────────────────────────────────────────────────────────

function MonitorStatusDot({ status }: { status: string }) {
  const cls =
    status === "up" ? "bg-emerald-500" :
    status === "down" ? "bg-red-500" :
    status === "degraded" ? "bg-amber-400" :
    "bg-slate-300";
  return <span className={`inline-block h-2.5 w-2.5 rounded-full ${cls}`} />;
}

function MonitorRow({ monitor }: { monitor: PublicStatusPage["monitors"][number] }) {
  const uptime = monitor.uptime_90d;
  const statusLabel =
    monitor.status === "up" ? "Operational" :
    monitor.status === "down" ? "Down" :
    monitor.status === "degraded" ? "Degraded" :
    monitor.status === "paused" ? "Paused" : "Pending";

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <MonitorStatusDot status={monitor.status} />
          <span className="font-medium text-sm">{monitor.name}</span>
        </div>
        <div className="flex items-center gap-4 text-xs text-muted-foreground">
          {uptime !== null && (
            <span className="font-mono">{uptime.toFixed(2)}% uptime</span>
          )}
          <span
            className={`font-semibold ${
              monitor.status === "up" ? "text-emerald-600" :
              monitor.status === "down" ? "text-red-600" :
              monitor.status === "degraded" ? "text-amber-600" :
              "text-slate-500"
            }`}
          >
            {statusLabel}
          </span>
        </div>
      </div>
      {monitor.uptime_bars.length > 0 && (
        <UptimeBars bars={monitor.uptime_bars} />
      )}
      <div className="flex justify-between text-xs text-muted-foreground">
        <span>90 days ago</span>
        <span>Today</span>
      </div>
    </div>
  );
}

// ── page ──────────────────────────────────────────────────────────────────────

export default async function PublicStatusPageRoute({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const page = await getPage(slug);
  if (!page) notFound();

  const updatedAt = new Date(page.updated_at).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });

  return (
    <div className="min-h-screen bg-background">
      {/* Auto-refresh every 10 s */}
      <PublicStatusPageRefresh intervalMs={10000} />

      <div className="max-w-3xl mx-auto px-4 py-12 space-y-8">
        {/* Header */}
        <div className="space-y-1">
          <h1 className="text-2xl font-bold tracking-tight">{page.name}</h1>
          {page.description && (
            <p className="text-muted-foreground">{page.description}</p>
          )}
        </div>

        <StatusBanner status={page.overall_status} />

        {page.monitors.length === 0 ? (
          <div className="text-center py-12 text-muted-foreground">
            <p>No monitors configured on this page yet.</p>
          </div>
        ) : (
          <div className="space-y-6">
            {page.monitors.map((m) => (
              <div key={m.id} className="border rounded-xl px-5 py-4">
                <MonitorRow monitor={m} />
              </div>
            ))}
          </div>
        )}

        {/* Footer */}
        <div className="flex items-center justify-between text-xs text-muted-foreground border-t pt-4">
          <span>Last updated: {updatedAt}</span>
          <div className="flex items-center gap-1.5">
            <RefreshCw className="h-3 w-3" />
            <span>Auto-refreshes every 10 s</span>
          </div>
        </div>
      </div>
    </div>
  );
}
