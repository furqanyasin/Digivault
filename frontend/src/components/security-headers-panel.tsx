"use client";

import { useState } from "react";
import { Check, AlertTriangle, X, RefreshCw, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { SecurityHeaderReport } from "@/lib/api";
import { fmtDateTime } from "@/lib/utils";

interface Props {
  websiteId: string;
  report: SecurityHeaderReport | null;
}

const GRADE_COLOR: Record<string, string> = {
  "A+": "bg-emerald-500 text-white border-emerald-600",
  A: "bg-emerald-500 text-white border-emerald-600",
  B: "bg-lime-500 text-white border-lime-600",
  C: "bg-amber-400 text-amber-950 border-amber-500",
  D: "bg-orange-500 text-white border-orange-600",
  F: "bg-red-500 text-white border-red-600",
};

const STATUS_ICON = {
  pass: <Check className="h-4 w-4 text-emerald-600 shrink-0" />,
  warn: <AlertTriangle className="h-4 w-4 text-amber-500 shrink-0" />,
  fail: <X className="h-4 w-4 text-red-500 shrink-0" />,
} as const;

export function SecurityHeadersPanel({ websiteId, report }: Props) {
  const [checking, setChecking] = useState(false);
  const [data, setData] = useState<SecurityHeaderReport | null>(report);

  async function runCheck() {
    setChecking(true);
    try {
      await fetch(`/api/websites/${websiteId}/security-headers`, { method: "POST" });
      let attempts = 0;
      const poll = async () => {
        attempts++;
        const res = await fetch(`/api/websites/${websiteId}/security-headers`);
        const json = await res.json();
        const s: SecurityHeaderReport = json?.data ?? json;
        setData(s);
        if (s.check_status === "running" && attempts < 20) {
          setTimeout(poll, 1500);
        } else {
          setChecking(false);
        }
      };
      setTimeout(poll, 1200);
    } catch {
      setChecking(false);
    }
  }

  const hasResult = data && data.check_status === "done" && data.headers?.length > 0;
  const running = checking || data?.check_status === "running";

  return (
    <div className="border rounded-lg p-4 space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="font-medium text-sm">Security Headers</h3>
          <p className="text-xs text-muted-foreground mt-0.5">
            HTTP response headers that protect against XSS, clickjacking & protocol downgrade.
            {data?.last_checked_at && ` · Checked ${fmtDateTime(data.last_checked_at)}`}
            {data?.check_status === "failed" && data.error && (
              <span className="text-red-600"> · {data.error}</span>
            )}
          </p>
        </div>
        <Button size="sm" variant="outline" onClick={runCheck} disabled={running}>
          {running ? (
            <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
          ) : (
            <RefreshCw className="h-3.5 w-3.5 mr-1.5" />
          )}
          Check Headers
        </Button>
      </div>

      {!hasResult ? (
        <p className="text-sm text-muted-foreground py-6 text-center">
          {data?.check_status === "running"
            ? "Checking headers…"
            : "No header check run yet. Click Check Headers to grade this site."}
        </p>
      ) : (
        <div className="flex flex-col sm:flex-row gap-5">
          {/* Grade badge */}
          <div className="flex sm:flex-col items-center gap-3 sm:gap-1.5 shrink-0">
            <div
              className={`flex items-center justify-center h-20 w-20 rounded-xl border text-3xl font-bold ${
                GRADE_COLOR[data.grade] ?? "bg-muted text-foreground border-border"
              }`}
            >
              {data.grade}
            </div>
            <div className="text-center">
              <div className="text-lg font-semibold leading-none">{data.score}<span className="text-xs text-muted-foreground">/100</span></div>
              <div className="text-xs text-muted-foreground mt-1">
                {data.pass_count} pass · {data.warn_count} warn · {data.fail_count} fail
              </div>
            </div>
          </div>

          {/* Header checklist */}
          <div className="flex-1 space-y-2 min-w-0">
            {data.headers.map((h) => (
              <div key={h.key} className="flex items-start gap-2.5">
                {STATUS_ICON[h.status]}
                <div className="min-w-0 flex-1">
                  <div className="flex items-baseline gap-2 flex-wrap">
                    <span className="text-sm font-medium">{h.name}</span>
                    {!h.present && (
                      <span className="text-xs text-red-600 font-medium">missing</span>
                    )}
                  </div>
                  {h.present && h.value && (
                    <p className="font-mono text-xs text-muted-foreground break-all">{h.value}</p>
                  )}
                  {h.recommendation && (
                    <p className="text-xs text-muted-foreground mt-0.5">{h.recommendation}</p>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
