import { notFound } from "next/navigation";
import type { Metadata } from "next";
import { CheckCircle, AlertTriangle, XCircle, RefreshCw, Wrench } from "lucide-react";
import type { PublicStatusPage, PublicIncident } from "@/lib/api";
import { PublicStatusPageRefresh } from "@/components/public-status-page-refresh";
import { UptimeBarStrip } from "@/components/uptime-bar-strip";
import { fmtDateTime } from "@/lib/utils";

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

function MonitorRow({
  monitor,
  incidents,
}: {
  monitor: PublicStatusPage["monitors"][number];
  incidents: PublicIncident[];
}) {
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
        <UptimeBarStrip bars={monitor.uptime_bars} incidents={incidents} />
      )}
      <div className="flex justify-between text-xs text-muted-foreground">
        <span>90 days ago</span>
        <span>Today</span>
      </div>
    </div>
  );
}

// ── incidents ─────────────────────────────────────────────────────────────────

const INCIDENT_STATUS: Record<string, { label: string; cls: string }> = {
  investigating: { label: "Investigating", cls: "text-red-600" },
  identified:    { label: "Identified",    cls: "text-amber-600" },
  monitoring:    { label: "Monitoring",    cls: "text-blue-600" },
  resolved:      { label: "Resolved",      cls: "text-emerald-600" },
};

function IncidentEntry({ incident }: { incident: PublicIncident }) {
  const s = INCIDENT_STATUS[incident.status] ?? { label: incident.status, cls: "text-muted-foreground" };
  return (
    <div className="space-y-1">
      <p className="font-medium text-sm">{incident.title}</p>
      <p className="text-sm">
        <span className={`font-semibold ${s.cls}`}>{s.label}</span>
        {incident.body ? <span className="text-muted-foreground"> — {incident.body}</span> : null}
      </p>
      <p className="text-xs text-muted-foreground">
        Posted {fmtDateTime(incident.created_at)}
        {incident.resolved_at ? ` · Resolved ${fmtDateTime(incident.resolved_at)}` : ""}
      </p>
    </div>
  );
}

function PastIncidents({ incidents }: { incidents: PublicIncident[] }) {
  // Group by calendar day and render the last 14 days newest-first, filling
  // quiet days with "No incidents reported" — mirrors a hosted status page.
  const byDay = new Map<string, PublicIncident[]>();
  for (const inc of incidents) {
    const key = new Date(inc.created_at).toDateString();
    const list = byDay.get(key) ?? [];
    list.push(inc);
    byDay.set(key, list);
  }

  const days: Date[] = Array.from({ length: 14 }, (_, i) => {
    const d = new Date();
    d.setDate(d.getDate() - i);
    return d;
  });

  const fmtDay = (d: Date) =>
    d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });

  return (
    <div className="space-y-5">
      <h2 className="text-lg font-semibold tracking-tight">Past Incidents</h2>
      {days.map((d) => {
        const dayIncidents = byDay.get(d.toDateString()) ?? [];
        return (
          <div key={d.toDateString()} className="border-t pt-3">
            <p className="text-sm font-medium text-muted-foreground mb-2">{fmtDay(d)}</p>
            {dayIncidents.length === 0 ? (
              <p className="text-sm text-muted-foreground">No incidents reported.</p>
            ) : (
              <div className="space-y-4">
                {dayIncidents.map((inc) => (
                  <IncidentEntry key={inc.id} incident={inc} />
                ))}
              </div>
            )}
          </div>
        );
      })}
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

  const updatedAt = fmtDateTime(page.updated_at);
  const maintenance = page.maintenance ?? [];
  const incidents = page.incidents ?? [];

  return (
    <div className="min-h-screen bg-background">
      {/* Auto-refresh every 10 s */}
      <PublicStatusPageRefresh intervalMs={10000} />

      {/* Brand accent bar */}
      <div className="h-1.5 w-full" style={{ backgroundColor: page.brand_color || "#6366f1" }} />

      <div className="max-w-3xl mx-auto px-4 py-10 space-y-8">
        {/* Header */}
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-3 min-w-0">
            {page.logo_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={page.logo_url} alt={page.name} className="h-9 w-9 rounded object-contain shrink-0" />
            ) : (
              <span
                className="h-9 w-9 rounded flex items-center justify-center text-white font-bold shrink-0"
                style={{ backgroundColor: page.brand_color || "#6366f1" }}
              >
                {page.name.charAt(0).toUpperCase()}
              </span>
            )}
            <div className="min-w-0">
              <h1 className="text-2xl font-bold tracking-tight truncate">{page.name}</h1>
              {page.description && (
                <p className="text-muted-foreground text-sm truncate">{page.description}</p>
              )}
            </div>
          </div>
        </div>

        <StatusBanner status={page.overall_status} />

        {/* Scheduled maintenance */}
        {maintenance.length > 0 && (
          <div className="space-y-3">
            {maintenance.map((m) => (
              <div key={m.id} className="flex gap-3 rounded-xl border border-blue-200 bg-blue-50 px-5 py-4">
                <Wrench className="h-5 w-5 text-blue-600 shrink-0 mt-0.5" />
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <p className="font-semibold text-blue-900 text-sm">{m.title}</p>
                    {m.is_active && (
                      <span className="text-xs font-medium px-1.5 py-0.5 rounded bg-blue-600 text-white">In progress</span>
                    )}
                  </div>
                  {m.message && <p className="text-sm text-blue-800">{m.message}</p>}
                  <p className="text-xs text-blue-700">
                    {fmtDateTime(m.scheduled_start)} → {fmtDateTime(m.scheduled_end)}
                  </p>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Uptime */}
        <div className="space-y-4">
          <p className="text-sm text-muted-foreground">Uptime over the past 90 days.</p>
          {page.monitors.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              <p>No monitors configured on this page yet.</p>
            </div>
          ) : (
            <div className="space-y-6">
              {page.monitors.map((m) => (
                <div key={m.id} className="border rounded-xl px-5 py-4">
                  <MonitorRow monitor={m} incidents={incidents} />
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Past incidents */}
        <PastIncidents incidents={incidents} />

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
