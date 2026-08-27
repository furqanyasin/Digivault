"use client";

import { useMemo, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Code, CheckCircle, Ban, Loader2, AlertTriangle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ScriptDetailDialog } from "@/components/script-detail-dialog";
import type { Script } from "@/lib/api";
import { fmtDate } from "@/lib/utils";
import { scriptGroupKey, shortDomain } from "@/lib/script-domains";

interface Props {
  scripts: Script[];
  websiteId: string;
}

type ReviewFilter = "all" | "pending" | "approved" | "blocked";

function providerVariant(p: string): "default" | "secondary" | "destructive" | "outline" {
  if (!p || p === "unknown") return "outline";
  if (p === "google-analytics" || p === "google-tag-manager") return "secondary";
  return "default";
}


// One provider entry can span several files; the row shows the aggregate.
function groupReviewStatus(group: Script[]): "pending" | "approved" | "blocked" | "ignored" {
  if (group.some((s) => s.review_status === "blocked")) return "blocked";
  if (group.some((s) => s.review_status === "pending")) return "pending";
  if (group.every((s) => s.review_status === "ignored")) return "ignored";
  return "approved";
}

function StatusDot({ active }: { active: boolean }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs font-medium">
      <span className={`h-2 w-2 rounded-full ${active ? "bg-emerald-500" : "bg-red-500"}`} />
      <span className={active ? "text-emerald-600" : "text-red-600"}>
        {active ? "Active" : "Inactive"}
      </span>
    </span>
  );
}

const REVIEW_CHIP: Record<string, { label: string; cls: string }> = {
  approved: { label: "Approved", cls: "bg-emerald-100 text-emerald-800" },
  blocked: { label: "Blocked", cls: "bg-red-100 text-red-800" },
  ignored: { label: "Ignored", cls: "bg-slate-100 text-slate-600" },
  pending: { label: "Pending", cls: "bg-amber-100 text-amber-800" },
};

function GroupReviewActions({
  group,
  websiteId,
}: {
  group: Script[];
  websiteId: string;
}) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [busy, setBusy] = useState(false);
  const status = groupReviewStatus(group);

  async function setAll(next: "approved" | "blocked" | "pending") {
    setBusy(true);
    await Promise.all(
      group
        .filter((s) => s.review_status !== next)
        .map((s) =>
          fetch(`/api/websites/${websiteId}/scripts/${s.id}/review`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ review_status: next }),
          })
        )
    );
    setBusy(false);
    startTransition(() => router.refresh());
  }

  if (busy || pending) {
    return <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />;
  }

  if (status === "pending") {
    return (
      <div className="flex items-center gap-1">
        <Button
          size="sm"
          variant="ghost"
          className="h-7 px-2 text-xs text-emerald-600 hover:text-emerald-700 hover:bg-emerald-50"
          onClick={() => setAll("approved")}
        >
          <CheckCircle className="h-3.5 w-3.5 mr-1" />
          Approve
        </Button>
        <Button
          size="sm"
          variant="ghost"
          className="h-7 px-2 text-xs text-red-600 hover:text-red-700 hover:bg-red-50"
          onClick={() => setAll("blocked")}
        >
          <Ban className="h-3.5 w-3.5 mr-1" />
          Decline
        </Button>
      </div>
    );
  }

  const chip = REVIEW_CHIP[status];
  return (
    <div className="flex items-center gap-1">
      <span className={`px-2 py-0.5 rounded text-xs font-medium ${chip.cls}`}>{chip.label}</span>
      <Button
        size="sm"
        variant="ghost"
        className="h-6 px-2 text-xs text-muted-foreground"
        onClick={() => setAll("pending")}
      >
        Undo
      </Button>
    </div>
  );
}

export function ScriptsTab({ scripts, websiteId }: Props) {
  const [filter, setFilter] = useState<ReviewFilter>("all");

  // One row per provider, falling back to the domain when we cannot name the
  // provider. Keying on the domain alone listed Hotjar twice, because it serves
  // from both static.hotjar.com and script.hotjar.com and the row was labelled
  // by provider — two rows, same heading, no way to tell them apart. Unknown
  // scripts stay split by domain: with no provider to group under, merging them
  // would pile unrelated third parties into one row.
  const groups = useMemo(() => {
    const map = new Map<string, Script[]>();
    for (const s of scripts) {
      // Shared with countScriptGroups() so the tab badge and this table can
      // never disagree about how many rows there are.
      const key = scriptGroupKey(s);
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(s);
    }
    // Sort: known providers first, then by domain
    return Array.from(map.entries()).sort(([, a], [, b]) => {
      const aKnown = a[0].provider !== "unknown" ? 0 : 1;
      const bKnown = b[0].provider !== "unknown" ? 0 : 1;
      return aKnown - bKnown;
    });
  }, [scripts]);

  const counts = useMemo(() => {
    const c = { all: groups.length, pending: 0, approved: 0, blocked: 0 };
    for (const [, group] of groups) {
      const st = groupReviewStatus(group);
      if (st === "pending") c.pending += 1;
      else if (st === "approved") c.approved += 1;
      else if (st === "blocked") c.blocked += 1;
    }
    return c;
  }, [groups]);

  const visibleGroups = groups.filter(
    ([, group]) => filter === "all" || groupReviewStatus(group) === filter
  );

  if (scripts.length === 0) {
    return (
      <div className="p-10 flex flex-col items-center gap-3 text-center">
        <Code className="h-10 w-10 text-muted-foreground" />
        <p className="font-medium">No scripts detected yet</p>
        <p className="text-sm text-muted-foreground">
          Install the snippet and visit a page — data appears within seconds.
        </p>
      </div>
    );
  }

  const FILTERS: { key: ReviewFilter; label: string; count: number }[] = [
    { key: "all", label: "All", count: counts.all },
    { key: "pending", label: "Pending", count: counts.pending },
    { key: "approved", label: "Approved", count: counts.approved },
    { key: "blocked", label: "Rejected", count: counts.blocked },
  ];

  return (
    <div>
      <div className="flex items-center gap-1 px-4 pt-3 pb-1">
        {FILTERS.map(({ key, label, count }) => (
          <button
            key={key}
            onClick={() => setFilter(key)}
            className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${
              filter === key
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:bg-muted"
            }`}
          >
            {label} ({count})
          </button>
        ))}
      </div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Domain</TableHead>
            <TableHead>Provider</TableHead>
            <TableHead>Category</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Review</TableHead>
            <TableHead>Last seen</TableHead>
            <TableHead></TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {visibleGroups.map(([key, group]) => {
            const rep = group[0];
            // A provider can legitimately span hosts (Hotjar), so name every
            // one rather than picking one and hiding the rest.
            const domains = Array.from(new Set(group.map((s) => shortDomain(s.src_url))));
            const domainLabel =
              domains.length === 1 ? domains[0] : `${domains[0]} +${domains.length - 1}`;
            const anyActive = group.some((s) => s.is_active);
            const lastSeen = group
              .map((s) => s.last_seen_at)
              .filter(Boolean)
              .sort()
              .at(-1);
            return (
              <TableRow key={key}>
                <TableCell
                  className="font-mono text-xs max-w-[200px] truncate"
                  title={domains.join(", ")}
                >
                  {domainLabel}
                  <div className="text-muted-foreground font-sans">
                    {group.length} {group.length === 1 ? "file" : "files"}
                  </div>
                </TableCell>
                <TableCell>
                  <div className="flex flex-col items-start gap-1">
                    <Badge variant={providerVariant(rep.provider)} className="capitalize">
                      {rep.provider === "unknown" ? "—" : rep.provider}
                    </Badge>
                    {/* Injected-code flag. Advisory, so the reason is always
                        attached rather than shown as a bare verdict. */}
                    {group.some((x) => x.is_suspicious) && (
                      <Badge
                        variant="destructive"
                        className="gap-1 whitespace-nowrap"
                        title={group.flatMap((x) => x.suspicion_reasons ?? []).join(" · ")}
                      >
                        <AlertTriangle className="h-3 w-3" aria-hidden />
                        Suspicious
                      </Badge>
                    )}
                  </div>
                </TableCell>
                <TableCell className="text-sm capitalize text-muted-foreground">
                  {rep.category === "unknown" ? "—" : rep.category}
                </TableCell>
                <TableCell>
                  <StatusDot active={anyActive} />
                </TableCell>
                <TableCell>
                  <GroupReviewActions group={group} websiteId={websiteId} />
                </TableCell>
                <TableCell className="text-sm text-muted-foreground">
                  {fmtDate(lastSeen)}
                </TableCell>
                <TableCell>
                  <ScriptDetailDialog
                    scripts={group}
                    websiteId={websiteId}
                    label={`${rep.provider !== "unknown" ? rep.provider : domainLabel} — ${group.length} file${group.length > 1 ? "s" : ""}`}
                  />
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}
