"use client";

import { useState } from "react";
import { ShieldAlert, Copy, Check, ChevronDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export interface BlockedGroup {
  vendor: string;
  count: number;
  sites: {
    monitor_id: string; name: string; url: string; domain: string; since: string | null;
    /** Optional: an older backend does not send these. */
    has_heartbeat?: boolean;
    has_snippet?: boolean;
  }[];
  fix: { how: string; copy_label: string; text: string };
}

/**
 * Every blocked site, grouped by the firewall blocking it, with one fix per
 * firewall — "fix it for all websites" rather than one ticket per site. For
 * SiteGround (no customer allowlist) that is a single support ticket naming
 * every domain and our IP; for Cloudflare one WAF rule per account.
 */
export function BlockedSitesPanel({
  groups, egressIps, secondOpinionEnabled,
}: {
  groups: BlockedGroup[];
  egressIps: string[];
  /** undefined on an older backend: keep the old wording rather than guess. */
  secondOpinionEnabled?: boolean;
}) {
  if (groups.length === 0) return null;
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <ShieldAlert className="h-4 w-4 text-slate-500" />
          Blocked sites — fix them all at once
        </CardTitle>
        <p className="text-sm text-muted-foreground">
          A firewall answers our checks on these sites.{" "}
          {secondOpinionEnabled === false
            ? "Google second opinions are not configured on this server (PAGESPEED_API_KEY), so nothing else is checking them."
            : "Meanwhile Google checks them for us about every 30 minutes, so they still show up or down and still alert."}{" "}
          A WordPress site running the latest WP Connect snippet reports its own
          uptime every 5 minutes, which no firewall can block — the
          lasting fix, with no ticket and no IP to allowlist.
          {egressIps.length > 0 ? (
            <> Our monitor&rsquo;s IP: <span className="font-mono text-foreground">{egressIps.join(", ")}</span>.</>
          ) : null}{" "}
          <a href="/bot" className="underline">Allowlisting guide</a>
        </p>
      </CardHeader>
      <CardContent className="space-y-3">
        {groups.map((g) => <VendorGroup key={g.vendor} group={g} />)}
      </CardContent>
    </Card>
  );
}

function VendorGroup({ group }: { group: BlockedGroup }) {
  const [copied, setCopied] = useState(false);
  const [open, setOpen] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(group.fix.text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // clipboard refused (insecure origin / not focused): the text is shown below
      setOpen(true);
    }
  }

  return (
    <div className="rounded-lg border p-3 space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <p className="font-medium text-sm flex-1 min-w-[12rem]">
          {group.count} site{group.count !== 1 ? "s" : ""} blocked by {group.vendor}
        </p>
        <Button size="sm" onClick={copy}>
          {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
          {copied ? "Copied" : group.fix.copy_label}
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
          Details
          <ChevronDown className={`h-3.5 w-3.5 transition-transform ${open ? "rotate-180" : ""}`} />
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">{group.fix.how}</p>
      <p className="text-xs text-muted-foreground truncate">
        {group.sites.map((s) => s.domain).join(", ")}
      </p>
      {group.sites.some((s) => s.has_heartbeat === false) && (
        <p className="text-xs text-muted-foreground">
          No WP Connect heartbeat yet:{" "}
          {group.sites.filter((s) => s.has_heartbeat === false).map((s) => s.domain).join(", ")}
        </p>
      )}
      {open && (
        <pre className="whitespace-pre-wrap break-words rounded-md bg-muted p-3 text-xs">{group.fix.text}</pre>
      )}
    </div>
  );
}
