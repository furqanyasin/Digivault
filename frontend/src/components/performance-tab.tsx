"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine,
} from "recharts";
import { RefreshCw, Zap, Monitor, Smartphone, Users } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import type { CruxReport, PerformanceReport } from "@/lib/api";

// ── helpers ──────────────────────────────────────────────────────────────────

function scoreColor(score: number | null) {
  if (score === null) return "text-muted-foreground";
  if (score >= 90) return "text-emerald-600";
  if (score >= 50) return "text-amber-500";
  return "text-red-500";
}

function ratingBadge(rating: string) {
  if (rating === "fast") return <Badge className="bg-emerald-100 text-emerald-700 border-0 text-xs">Fast</Badge>;
  if (rating === "average") return <Badge className="bg-amber-100 text-amber-700 border-0 text-xs">Average</Badge>;
  if (rating === "slow") return <Badge className="bg-red-100 text-red-700 border-0 text-xs">Slow</Badge>;
  return null;
}

function fmtMs(ms: number | null) {
  if (ms === null) return "—";
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)} s`;
  return `${ms} ms`;
}

function ScoreRing({ score }: { score: number | null }) {
  const s = score ?? 0;
  const color = s >= 90 ? "#22c55e" : s >= 50 ? "#f59e0b" : "#ef4444";
  const r = 28;
  const circ = 2 * Math.PI * r;
  const dash = (s / 100) * circ;

  return (
    <div className="flex flex-col items-center gap-1">
      <svg width="72" height="72" viewBox="0 0 72 72">
        <circle cx="36" cy="36" r={r} fill="none" stroke="#e5e7eb" strokeWidth="6" />
        <circle
          cx="36" cy="36" r={r} fill="none" stroke={color} strokeWidth="6"
          strokeDasharray={`${dash} ${circ}`}
          strokeLinecap="round"
          transform="rotate(-90 36 36)"
        />
        <text x="36" y="40" textAnchor="middle" fontSize="16" fontWeight="bold" fill={color}>
          {score ?? "—"}
        </text>
      </svg>
    </div>
  );
}

const METRICS: Array<{ key: string; label: string; desc: string; ratingKey: string; isCls?: boolean }> = [
  { key: "fcp_ms", label: "FCP", desc: "First Contentful Paint", ratingKey: "fcp_rating" },
  { key: "lcp_ms", label: "LCP", desc: "Largest Contentful Paint", ratingKey: "lcp_rating" },
  { key: "cls_score", label: "CLS", desc: "Cumulative Layout Shift", ratingKey: "cls_rating", isCls: true },
  { key: "tbt_ms", label: "TBT", desc: "Total Blocking Time", ratingKey: "tbt_rating" },
  { key: "ttfb_ms", label: "TTFB", desc: "Time to First Byte", ratingKey: "" },
  { key: "si_ms", label: "SI", desc: "Speed Index", ratingKey: "" },
  { key: "inp_ms", label: "INP", desc: "Interaction to Next Paint", ratingKey: "" },
];

// ── chart ─────────────────────────────────────────────────────────────────────

function HistoryChart({ reports }: { reports: PerformanceReport[] }) {
  const data = [...reports].reverse().map((r) => ({
    date: new Date(r.checked_at).toLocaleDateString(undefined, { month: "short", day: "numeric" }),
    score: r.performance_score,
  }));

  if (data.length < 2) {
    return (
      <p className="text-xs text-muted-foreground text-center py-8">
        Run at least 2 checks to see the trend chart.
      </p>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={160}>
      <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -24 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
        <XAxis dataKey="date" tick={{ fontSize: 10 }} />
        <YAxis domain={[0, 100]} tick={{ fontSize: 10 }} />
        <Tooltip
          contentStyle={{ fontSize: 12, borderRadius: 6 }}
          formatter={(v) => [`${v}`, "Score"]}
        />
        <ReferenceLine y={90} stroke="#22c55e" strokeDasharray="4 2" />
        <ReferenceLine y={50} stroke="#f59e0b" strokeDasharray="4 2" />
        <Line
          type="monotone" dataKey="score" stroke="#6366f1"
          strokeWidth={2} dot={{ r: 3 }} activeDot={{ r: 5 }}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}

// ── main component ────────────────────────────────────────────────────────────

// ── CrUX section ─────────────────────────────────────────────────────────────

function pct(v: number | null) {
  if (v === null) return "—";
  return `${Math.round(v * 100)}%`;
}

function DistBar({ good, ni, poor }: { good: number | null; ni: number | null; poor: number | null }) {
  if (good === null) return <span className="text-xs text-muted-foreground">no data</span>;
  const g = Math.round((good ?? 0) * 100);
  const n = Math.round((ni ?? 0) * 100);
  const p = Math.round((poor ?? 0) * 100);
  return (
    <div className="flex rounded overflow-hidden h-2 w-full">
      {g > 0 && <div className="bg-emerald-500" style={{ width: `${g}%` }} title={`Good ${g}%`} />}
      {n > 0 && <div className="bg-amber-400" style={{ width: `${n}%` }} title={`Needs improvement ${n}%`} />}
      {p > 0 && <div className="bg-red-500" style={{ width: `${p}%` }} title={`Poor ${p}%`} />}
    </div>
  );
}

const CRUX_METRICS = [
  { label: "LCP", p75Key: "lcp_p75_ms", goodKey: "lcp_good", niKey: "lcp_ni", poorKey: "lcp_poor", unit: "ms", desc: "Largest Contentful Paint" },
  { label: "FCP", p75Key: "fcp_p75_ms", goodKey: "fcp_good", niKey: "fcp_ni", poorKey: "fcp_poor", unit: "ms", desc: "First Contentful Paint" },
  { label: "CLS", p75Key: "cls_p75", goodKey: "cls_good", niKey: "cls_ni", poorKey: "cls_poor", unit: "", desc: "Cumulative Layout Shift" },
  { label: "INP", p75Key: "inp_p75_ms", goodKey: "inp_good", niKey: "inp_ni", poorKey: "inp_poor", unit: "ms", desc: "Interaction to Next Paint" },
] as const;

function CruxSection({ websiteId, reports }: { websiteId: string; reports: CruxReport[] }) {
  const [running, setRunning] = useState(false);
  const router = useRouter();
  const [error, setError] = useState("");
  const latest = reports[0] ?? null;

  async function fetchCrux() {
    setError("");
    setRunning(true);
    try {
      const res = await fetch(`/api/websites/${websiteId}/crux/run`, { method: "POST" });
      const d = await res.json().catch(() => ({}));
      if (!res.ok && res.status !== 422) {
        setError(d?.detail ?? `Error ${res.status}`);
      } else if (d?.detail) {
        setError(d.detail);
      } else {
        router.refresh();
      }
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Users className="h-4 w-4 text-muted-foreground" />
          <h3 className="font-semibold text-sm">Real User Metrics (Chrome UX Report)</h3>
          <Badge variant="secondary" className="text-xs">p75 field data</Badge>
        </div>
        <Button size="sm" variant="outline" onClick={fetchCrux} disabled={running}>
          <RefreshCw className={`h-3.5 w-3.5 mr-1.5 ${running ? "animate-spin" : ""}`} />
          {running ? "Fetching…" : "Fetch CrUX"}
        </Button>
      </div>

      {error && <p className="text-sm text-red-600">{error}</p>}

      {!latest ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-12 gap-3 text-center">
            <Users className="h-10 w-10 text-muted-foreground" />
            <p className="font-medium">No real-user data yet</p>
            <p className="text-sm text-muted-foreground max-w-sm">
              CrUX data comes from real Chrome users visiting your site. Click &ldquo;Fetch CrUX&rdquo; to pull the latest field data from Google.
            </p>
            <Button size="sm" onClick={fetchCrux} disabled={running} className="mt-1">
              {running ? "Fetching…" : "Fetch CrUX data"}
            </Button>
          </CardContent>
        </Card>
      ) : (
        <>
          <p className="text-xs text-muted-foreground">
            Data for <span className="font-mono">{latest.origin}</span> · fetched {new Date(latest.fetched_at).toLocaleString()}
          </p>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {CRUX_METRICS.map(({ label, p75Key, goodKey, niKey, poorKey, unit, desc }) => {
              const val = latest[p75Key as keyof CruxReport] as number | null;
              const display = val !== null ? `${val}${unit}` : "—";
              return (
                <div key={label} className="border rounded-lg p-3 space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">{label}</span>
                    <span className="text-xs text-muted-foreground">p75</span>
                  </div>
                  <p className="text-xl font-bold">{display}</p>
                  <p className="text-xs text-muted-foreground">{desc}</p>
                  <DistBar
                    good={latest[goodKey as keyof CruxReport] as number | null}
                    ni={latest[niKey as keyof CruxReport] as number | null}
                    poor={latest[poorKey as keyof CruxReport] as number | null}
                  />
                  <div className="flex justify-between text-xs text-muted-foreground">
                    <span className="text-emerald-600">{pct(latest[goodKey as keyof CruxReport] as number | null)} good</span>
                    <span className="text-red-500">{pct(latest[poorKey as keyof CruxReport] as number | null)} poor</span>
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}

interface Props {
  websiteId: string;
  mobileReports: PerformanceReport[];
  desktopReports: PerformanceReport[];
  cruxReports: CruxReport[];
}

export function PerformanceTab({ websiteId, mobileReports, desktopReports, cruxReports }: Props) {
  const router = useRouter();
  const [strategy, setStrategy] = useState<"mobile" | "desktop">("mobile");
  const [running, startTransition] = useTransition();
  const [error, setError] = useState("");

  const reports = strategy === "mobile" ? mobileReports : desktopReports;
  const latest = reports[0] ?? null;

  async function runCheck() {
    setError("");
    startTransition(async () => {
      const res = await fetch(`/api/websites/${websiteId}/performance/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ strategy }),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        setError(d?.detail ?? `Error ${res.status}`);
      } else {
        router.refresh();
      }
    });
  }

  return (
    <div className="space-y-6">
      {/* Controls */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Button
            size="sm" variant={strategy === "mobile" ? "default" : "outline"}
            onClick={() => setStrategy("mobile")}
          >
            <Smartphone className="h-3.5 w-3.5 mr-1.5" />
            Mobile
          </Button>
          <Button
            size="sm" variant={strategy === "desktop" ? "default" : "outline"}
            onClick={() => setStrategy("desktop")}
          >
            <Monitor className="h-3.5 w-3.5 mr-1.5" />
            Desktop
          </Button>
        </div>
        <Button size="sm" variant="outline" onClick={runCheck} disabled={running}>
          <RefreshCw className={`h-3.5 w-3.5 mr-1.5 ${running ? "animate-spin" : ""}`} />
          {running ? "Running…" : "Run check"}
        </Button>
      </div>

      {error && <p className="text-sm text-red-600">{error}</p>}

      {!latest ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16 gap-3 text-center">
            <Zap className="h-10 w-10 text-muted-foreground" />
            <p className="text-lg font-medium">No performance data yet</p>
            <p className="text-sm text-muted-foreground">
              Click &ldquo;Run check&rdquo; to fetch Lighthouse scores via PageSpeed Insights
            </p>
            <Button size="sm" onClick={runCheck} disabled={running} className="mt-2">
              <RefreshCw className={`h-3.5 w-3.5 mr-1.5 ${running ? "animate-spin" : ""}`} />
              {running ? "Running…" : "Run first check"}
            </Button>
          </CardContent>
        </Card>
      ) : (
        <>
          {/* Score + last checked */}
          <div className="grid gap-4 md:grid-cols-2">
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium text-muted-foreground flex items-center justify-between">
                  Performance Score
                  <span className="text-xs font-normal">
                    {new Date(latest.checked_at).toLocaleString()}
                  </span>
                </CardTitle>
              </CardHeader>
              <CardContent className="flex items-center gap-6">
                <ScoreRing score={latest.performance_score} />
                <div className="space-y-1 text-sm">
                  <p className={`text-3xl font-bold ${scoreColor(latest.performance_score)}`}>
                    {latest.performance_score ?? "—"}
                    <span className="text-base font-normal text-muted-foreground">/100</span>
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {latest.performance_score !== null
                      ? latest.performance_score >= 90 ? "Good — keep it up!"
                        : latest.performance_score >= 50 ? "Needs improvement"
                        : "Poor — action required"
                      : "Check failed"}
                  </p>
                  {latest.url && (
                    <p className="text-xs font-mono text-muted-foreground truncate max-w-[200px]">{latest.url}</p>
                  )}
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium text-muted-foreground">
                  Score trend ({reports.length} checks)
                </CardTitle>
              </CardHeader>
              <CardContent className="pt-0">
                <HistoryChart reports={reports} />
              </CardContent>
            </Card>
          </div>

          {/* Core Web Vitals */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Core Web Vitals & Metrics</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                {METRICS.map(({ key, label, desc, ratingKey, isCls }) => {
                  const rawVal = latest[key as keyof PerformanceReport];
                  const rating = ratingKey ? (latest[ratingKey as keyof PerformanceReport] as string) : "";
                  const display = isCls
                    ? (rawVal !== null ? String(rawVal) : "—")
                    : fmtMs(rawVal as number | null);

                  return (
                    <div key={key} className="border rounded-lg p-3 space-y-1">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">{label}</span>
                        {ratingBadge(rating)}
                      </div>
                      <p className="text-xl font-bold">{display}</p>
                      <p className="text-xs text-muted-foreground">{desc}</p>
                    </div>
                  );
                })}
              </div>
            </CardContent>
          </Card>

          {/* Check history */}
          {reports.length > 1 && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">History</CardTitle>
              </CardHeader>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b bg-muted/30">
                      <th className="px-3 py-2 text-left text-muted-foreground font-medium">Time</th>
                      <th className="px-3 py-2 text-right text-muted-foreground font-medium">Score</th>
                      <th className="px-3 py-2 text-right text-muted-foreground font-medium">FCP</th>
                      <th className="px-3 py-2 text-right text-muted-foreground font-medium">LCP</th>
                      <th className="px-3 py-2 text-right text-muted-foreground font-medium">CLS</th>
                      <th className="px-3 py-2 text-right text-muted-foreground font-medium">TBT</th>
                      <th className="px-3 py-2 text-right text-muted-foreground font-medium">TTFB</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {reports.map((r) => (
                      <tr key={r.id} className="hover:bg-muted/20">
                        <td className="px-3 py-2 text-muted-foreground font-mono whitespace-nowrap">
                          {new Date(r.checked_at).toLocaleString()}
                        </td>
                        <td className={`px-3 py-2 text-right font-bold ${scoreColor(r.performance_score)}`}>
                          {r.performance_score ?? "—"}
                        </td>
                        <td className="px-3 py-2 text-right font-mono">{fmtMs(r.fcp_ms)}</td>
                        <td className="px-3 py-2 text-right font-mono">{fmtMs(r.lcp_ms)}</td>
                        <td className="px-3 py-2 text-right font-mono">{r.cls_score ?? "—"}</td>
                        <td className="px-3 py-2 text-right font-mono">{fmtMs(r.tbt_ms)}</td>
                        <td className="px-3 py-2 text-right font-mono">{fmtMs(r.ttfb_ms)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}
        </>
      )}

      {/* Real User Metrics (CrUX) — always shown regardless of lab data */}
      <div className="border-t pt-6">
        <CruxSection websiteId={websiteId} reports={cruxReports} />
      </div>
    </div>
  );
}
