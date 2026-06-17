import Link from "next/link";
import { HeartPulse, ChevronDown, AlertTriangle, ShieldAlert, CalendarClock, Lock, CheckCircle } from "lucide-react";
import { Card } from "@/components/ui/card";
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

// Mirrors apps/websites/models.py → Website.recalculate_health_score so the
// explanation always matches how the number is actually computed.
const RUBRIC: { label: string; detail: string }[] = [
  { label: "Pending script changes", detail: "critical −15, high −10, medium −3, low −1 each (capped per level)" },
  { label: "Domain expiry", detail: "−8 within 30 days, −20 within 7 days" },
  { label: "SSL certificate expiry", detail: "−5 within 30 days, −12 within 14 days, −20 within 7 days" },
  { label: "Open vulnerabilities", detail: "critical −8, high −4 each (capped)" },
];

export function HealthScoreInfo({ healthScore, status, pendingChanges, domainInfo, vulns, websiteId }: Props) {
  const sev = (s: string) => pendingChanges.filter((c) => c.severity === s).length;
  const highRisk = sev("critical") + sev("high");
  const medium = sev("medium");
  const low = sev("low");

  const domainDays = domainInfo?.domain_days_until_expiry ?? null;
  const sslDays = domainInfo?.ssl_days_until_expiry ?? null;
  const vulnCount = vulns.filter((v) => v.severity === "critical" || v.severity === "high").length;

  const fixes: { icon: typeof AlertTriangle; text: string; href: string }[] = [];
  if (highRisk > 0) {
    fixes.push({
      icon: AlertTriangle,
      text: `Review & acknowledge ${highRisk} high-risk pending change${highRisk > 1 ? "s" : ""} — approve or ignore the scripts on the Scripts tab, or clear them in the Change Log.`,
      href: `/websites/${websiteId}?tab=changelog`,
    });
  }
  if (medium + low > 0) {
    fixes.push({
      icon: AlertTriangle,
      text: `Clear ${medium + low} lower-severity pending change${medium + low > 1 ? "s" : ""} once you've confirmed they're expected.`,
      href: `/websites/${websiteId}?tab=changelog`,
    });
  }
  if (domainDays !== null && domainDays <= 30) {
    fixes.push({
      icon: CalendarClock,
      text: `Renew the domain — it expires in ${domainDays} day${domainDays === 1 ? "" : "s"}.`,
      href: `/websites/${websiteId}?tab=access`,
    });
  }
  if (sslDays !== null && sslDays <= 30) {
    fixes.push({
      icon: Lock,
      text: `Renew the SSL certificate — it expires in ${sslDays} day${sslDays === 1 ? "" : "s"}.`,
      href: `/websites/${websiteId}?tab=access`,
    });
  }
  if (vulnCount > 0) {
    fixes.push({
      icon: ShieldAlert,
      text: `Patch ${vulnCount} open vulnerabilit${vulnCount > 1 ? "ies" : "y"} — update the affected plugins, themes, or core.`,
      href: `/websites/${websiteId}?tab=security`,
    });
  }

  return (
    <Card className="overflow-hidden">
      <details open>
        <summary className="flex items-center justify-between gap-2 px-4 py-3 cursor-pointer list-none select-none [&::-webkit-details-marker]:hidden">
          <span className="flex items-center gap-2 text-base font-semibold">
            <HeartPulse className="h-4 w-4 text-rose-500" />
            How the health score is calculated
          </span>
          <span className="flex items-center gap-2">
            <span className={`font-bold ${scoreColor(healthScore)}`}>{healthScore}/100</span>
            <ChevronDown className="h-4 w-4 text-muted-foreground" />
          </span>
        </summary>

        <div className="px-4 pb-4 space-y-4 text-sm">
          <p className="text-muted-foreground">
            Every site starts at <span className="font-medium text-foreground">100</span>. Points are deducted for
            unresolved issues — the score is recalculated automatically whenever data changes:
          </p>

          <ul className="space-y-1.5">
            {RUBRIC.map((r) => (
              <li key={r.label} className="flex gap-2">
                <span className="text-muted-foreground">•</span>
                <span>
                  <span className="font-medium">{r.label}:</span>{" "}
                  <span className="text-muted-foreground">{r.detail}</span>
                </span>
              </li>
            ))}
          </ul>

          <p className="text-muted-foreground">
            The <span className="font-medium text-foreground">status badge</span> follows the worst open change:
            an unacknowledged <span className="font-medium">critical/high</span> change marks the site{" "}
            <span className="text-red-600 font-medium">critical</span>, a <span className="font-medium">medium</span>{" "}
            change marks it <span className="text-amber-600 font-medium">warning</span>, otherwise it's{" "}
            <span className="text-emerald-600 font-medium">active</span>.
          </p>

          <div className="rounded-md border bg-muted/40 p-3 space-y-2">
            <p className="font-medium flex items-center gap-2">
              {fixes.length === 0
                ? <><CheckCircle className="h-4 w-4 text-emerald-500" /> How to improve it</>
                : <><AlertTriangle className="h-4 w-4 text-amber-500" /> How to improve this site ({status})</>}
            </p>
            {fixes.length === 0 ? (
              <p className="text-muted-foreground">
                No outstanding issues are dragging this score down. Keep changes acknowledged and renewals current to
                stay at 100.
              </p>
            ) : (
              <ul className="space-y-2">
                {fixes.map((f, i) => (
                  <li key={i} className="flex gap-2">
                    <f.icon className="h-4 w-4 text-muted-foreground shrink-0 mt-0.5" />
                    <Link href={f.href} className="hover:underline">{f.text}</Link>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </details>
    </Card>
  );
}
