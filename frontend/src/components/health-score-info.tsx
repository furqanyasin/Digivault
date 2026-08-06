import Link from "next/link";
import { AlertTriangle, ShieldAlert, CalendarClock, Lock, CheckCircle } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { DomainInfo, ScriptChange, VulnerabilityReport } from "@/lib/api";

interface Props {
  healthScore: number;
  status: string;
  pendingChanges: ScriptChange[];
  domainInfo: DomainInfo | null;
  vulns: VulnerabilityReport[];
  websiteId: string;
}

function scoreColor(score: number): string {
  if (score >= 85) return "text-emerald-600";
  if (score >= 60) return "text-amber-600";
  return "text-red-600";
}

function barColor(score: number): string {
  if (score >= 85) return "bg-emerald-500";
  if (score >= 60) return "bg-amber-500";
  // Red, matching the score text and the dashboard card. This was violet, which
  // read as a brand accent rather than as a failing score.
  return "bg-red-500";
}

// Mirrors apps/websites/models.py → Website.recalculate_health_score so the
// explanation always matches how the number is actually computed. Update both
// together.
const RUBRIC: { label: string; parts: string[] }[] = [
  { label: "Pending script changes", parts: ["critical −15", "high −10", "medium −3"] },
  { label: "Uptime", parts: ["down −30", "degraded −12", "under 99% −5", "under 95% −15"] },
  { label: "Domain expiry", parts: ["−8 within 30d", "−20 within 7d"] },
  { label: "SSL certificate", parts: ["−5 within 30d", "−12 within 14d", "−20 within 7d"] },
  { label: "Hosting expiry", parts: ["−8 within 30d", "−20 within 7d"] },
  { label: "Open vulnerabilities", parts: ["critical −8", "high −4"] },
  { label: "Broken forms (7d)", parts: ["−6 each", "max −18"] },
  { label: "Snippet not reporting", parts: ["−10 over 7d", "−20 over 30d"] },
  { label: "Unreviewed scripts", parts: ["−2 each", "max −10"] },
];

export function HealthScoreInfo({ healthScore, status, pendingChanges, domainInfo, vulns, websiteId }: Props) {
  const sev = (s: string) => pendingChanges.filter((c) => c.severity === s).length;
  const highRisk = sev("critical") + sev("high");
  const medium = sev("medium");
  const low = sev("low");

  const domainDays = domainInfo?.domain_days_until_expiry ?? null;
  const sslDays = domainInfo?.ssl_days_until_expiry ?? null;
  const vulnCount = vulns.filter((v) => v.severity === "critical" || v.severity === "high").length;

  // `href` is optional: not every fix has a tab to open — the Security tab is
  // withdrawn, so the vulnerability line states the problem without linking.
  const fixes: { icon: typeof AlertTriangle; tone: string; text: string; href?: string }[] = [];
  if (highRisk > 0) {
    fixes.push({
      icon: AlertTriangle,
      tone: "text-red-500",
      text: `Review ${highRisk} high-risk pending change${highRisk > 1 ? "s" : ""}`,
      href: `/websites/${websiteId}?tab=changelog`,
    });
  }
  if (medium + low > 0) {
    fixes.push({
      icon: AlertTriangle,
      tone: "text-amber-500",
      text: `Clear ${medium + low} lower-severity pending change${medium + low > 1 ? "s" : ""}`,
      href: `/websites/${websiteId}?tab=changelog`,
    });
  }
  if (domainDays !== null && domainDays <= 30) {
    fixes.push({
      icon: CalendarClock,
      tone: "text-muted-foreground",
      text: `Renew domain — expires in ${domainDays} day${domainDays === 1 ? "" : "s"}`,
      href: `/websites/${websiteId}?tab=access`,
    });
  }
  if (sslDays !== null && sslDays <= 30) {
    fixes.push({
      icon: Lock,
      tone: "text-muted-foreground",
      text: `Renew SSL certificate — expires in ${sslDays} day${sslDays === 1 ? "" : "s"}`,
      href: `/websites/${websiteId}?tab=access`,
    });
  }
  if (vulnCount > 0) {
    fixes.push({
      icon: ShieldAlert,
      tone: "text-red-500",
      text: `Patch ${vulnCount} open vulnerabilit${vulnCount > 1 ? "ies" : "y"}`,
    });
  }

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card className="lg:col-span-2">
        <CardContent className="space-y-4">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h3 className="text-base font-semibold">Health score</h3>
              <p className="text-sm text-muted-foreground">
                Recalculated automatically as issues open and close.
              </p>
            </div>
            <div className="text-right shrink-0">
              <span className={`text-3xl font-bold leading-none ${scoreColor(healthScore)}`}>
                {healthScore}
              </span>
              <p className="text-xs text-muted-foreground mt-1">/ 100</p>
            </div>
          </div>

          <div
            className="h-2 w-full overflow-hidden rounded-full bg-muted"
            role="progressbar"
            aria-valuenow={healthScore}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label="Health score"
          >
            <div
              className={`h-full rounded-full transition-all ${barColor(healthScore)}`}
              style={{ width: `${Math.max(0, Math.min(100, healthScore))}%` }}
            />
          </div>

          {/* The scoring rubric, so the number is never a black box. */}
          <div className="grid gap-3 sm:grid-cols-2">
            {RUBRIC.map((r) => (
              <div key={r.label} className="rounded-lg border px-3 py-2">
                <p className="text-sm font-medium">{r.label}</p>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  {r.parts.join(" · ")}
                </p>
              </div>
            ))}
          </div>

          <p className="text-xs text-muted-foreground">
            The status badge answers a different question — how urgent is the worst open issue, rather
            than how healthy overall. Downtime, an unacknowledged critical/high change, or anything
            expiring within 7 days marks the site{" "}
            <span className="font-medium text-red-600">critical</span>; a degraded monitor, a broken
            form, a medium change, or an expiry within 30 days marks it{" "}
            <span className="font-medium text-amber-600">warning</span>; otherwise{" "}
            <span className="font-medium text-emerald-600">active</span>. A score below 85 also forces
            at least <span className="font-medium text-amber-600">warning</span>, and below 60 at least{" "}
            <span className="font-medium text-red-600">critical</span>, so the badge can never disagree
            with the number. This site is <span className="font-medium">{status}</span>.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Recommended actions</CardTitle>
        </CardHeader>
        <CardContent>
          {fixes.length === 0 ? (
            <div className="flex gap-2 text-sm">
              <CheckCircle className="h-4 w-4 shrink-0 text-emerald-500 mt-0.5" />
              <p className="text-muted-foreground">
                Nothing is dragging this score down. Keep changes acknowledged and renewals current to stay at 100.
              </p>
            </div>
          ) : (
            <ul className="space-y-3">
              {fixes.map((f, i) => (
                <li key={i}>
                  {f.href ? (
                    <Link href={f.href} className="flex gap-2 text-sm group">
                      <f.icon className={`h-4 w-4 shrink-0 mt-0.5 ${f.tone}`} />
                      <span className="group-hover:underline">{f.text}</span>
                    </Link>
                  ) : (
                    <span className="flex gap-2 text-sm">
                      <f.icon className={`h-4 w-4 shrink-0 mt-0.5 ${f.tone}`} />
                      <span>{f.text}</span>
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
