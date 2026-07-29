import Link from "next/link";
import { Globe, AlertTriangle, Clock, ExternalLink, Star } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { Website } from "@/lib/api";
import { fmtDate, fmtDateTime } from "@/lib/utils";

// Score bands, mirroring Website.HEALTH_WARNING_BELOW / HEALTH_CRITICAL_BELOW
// and health-score-info.tsx. Colour follows the SCORE, not `status` — the
// dashboard used to tint the number by status, so a site scoring 42 with an
// 'active' badge rendered emerald.
function scoreTone(score: number): string {
  if (score >= 85) return "text-emerald-600";
  if (score >= 60) return "text-amber-600";
  return "text-red-600";
}

function scoreBar(score: number): string {
  if (score >= 85) return "bg-emerald-500";
  if (score >= 60) return "bg-amber-400";
  return "bg-red-500";
}

const STATUS_DOT: Record<string, string> = {
  active: "bg-emerald-500",
  warning: "bg-amber-500",
  critical: "bg-red-500",
  inactive: "bg-slate-400",
};

const STATUS_BADGE: Record<string, "destructive" | "warning" | "success" | "secondary"> = {
  active: "success",
  warning: "warning",
  critical: "destructive",
  inactive: "secondary",
};

interface Props {
  site: Website;
  /** Show a VIP star. The VIP section sets this; the plain grid doesn't. */
  showVipMark?: boolean;
}

/** One website's health at a glance. Shared by the dashboard's VIP, Needs
 *  Attention, and Your Sites sections so the three can't drift apart. */
export function SiteHealthCard({ site, showVipMark = false }: Props) {
  const score = site.health_score ?? 100;
  const status = site.status ?? "unknown";

  return (
    <Card className="hover:border-primary/50 hover:shadow-md transition-all">
      <CardContent className="p-5 space-y-3">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-2 min-w-0">
            <span
              className={`h-2.5 w-2.5 rounded-full shrink-0 ${STATUS_DOT[status] ?? "bg-slate-400"}`}
            />
            <div className="min-w-0">
              <p className="font-semibold text-sm truncate flex items-center gap-1.5">
                {showVipMark && site.is_vip && (
                  <Star
                    className="h-3.5 w-3.5 shrink-0 fill-amber-400 text-amber-500"
                    aria-label="VIP"
                  />
                )}
                <span className="truncate">{site.name || site.domain}</span>
              </p>
              <p className="text-xs text-muted-foreground font-mono truncate">{site.domain}</p>
            </div>
          </div>
          <Link href={`/websites/${site.id}`} aria-label={`Open ${site.name || site.domain}`}>
            <Button variant="ghost" size="sm" className="shrink-0 ml-2 h-7 w-7 p-0">
              <ExternalLink className="h-3.5 w-3.5" />
            </Button>
          </Link>
        </div>

        <div className="space-y-1">
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>Health</span>
            <div className="flex items-center gap-2">
              <span className={`font-bold text-sm ${scoreTone(score)}`}>{score}</span>
              <Badge variant={STATUS_BADGE[status] ?? "secondary"} className="text-xs h-5">
                {status}
              </Badge>
            </div>
          </div>
          <div
            className="h-1.5 rounded-full bg-muted overflow-hidden"
            role="progressbar"
            aria-valuenow={score}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label={`Health score for ${site.name || site.domain}`}
          >
            <div
              className={`h-full rounded-full transition-all ${scoreBar(score)}`}
              style={{ width: `${Math.max(0, Math.min(100, score))}%` }}
            />
          </div>
        </div>

        <div className="flex items-center gap-3 text-xs text-muted-foreground">
          <span className="flex items-center gap-1">
            <Globe className="h-3 w-3" />
            {site.script_count ?? 0} scripts
          </span>
          {(site.unknown_script_count ?? 0) > 0 && (
            <span className="flex items-center gap-1 text-red-600 font-semibold">
              <AlertTriangle className="h-3 w-3" />
              {site.unknown_script_count} unknown
            </span>
          )}
          {site.last_seen_at && (
            <span className="ml-auto flex items-center gap-1" title={fmtDateTime(site.last_seen_at)}>
              <Clock className="h-3 w-3" />
              {fmtDate(site.last_seen_at)}
            </span>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
