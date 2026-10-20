"use client";

import { useState } from "react";
import { Check, Copy, HeartPulse, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { fmtDateTime } from "@/lib/utils";
import type { Website } from "@/lib/api";

/** How long a heartbeat counts as current. Mirrors EVIDENCE_SITE_WINDOW_SECONDS
 *  in apps/monitors/evidence.py (15 min). */
const FRESH_MS = 15 * 60 * 1000;

function errorText(body: unknown, fallback: string) {
  const b = body as { detail?: string; errors?: { message?: string }[] } | null;
  return b?.errors?.[0]?.message || b?.detail || fallback;
}

/**
 * The WP Connect snippet: one-click wp-admin login, the WordPress activity log,
 * and the uptime heartbeat that keeps a site measurable when its host's
 * firewall blocks our monitor. Before this card the backend could generate the
 * snippet but nothing in the dashboard asked for it, so a re-paste campaign had
 * nothing to copy from.
 *
 * "Show snippet" returns the current one without touching the secret; only
 * "New secret" rotates it, because rotating stops the pasted copy until the new
 * one replaces it.
 */
export function WpConnectCard({ website }: { website: Website }) {
  const [snippet, setSnippet] = useState<string | null>(null);
  const [configured, setConfigured] = useState(Boolean(website.wp_sso_configured));
  const [busy, setBusy] = useState<"get" | "rotate" | null>(null);
  const [confirmRotate, setConfirmRotate] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  // Taken once, when the card mounts; the page is server-rendered with the
  // website's state at that moment anyway.
  const [now] = useState(() => Date.now());

  async function load(method: "GET" | "POST") {
    setBusy(method === "GET" ? "get" : "rotate");
    setError(null);
    try {
      const res = await fetch(`/api/websites/${website.id}/wp-sso-secret`, { method, cache: "no-store" });
      const body = await res.json().catch(() => null);
      if (!res.ok || !body?.snippet) {
        setError(errorText(body, res.status === 403
          ? "Only managers and owners can view this snippet."
          : "Could not load the snippet. Try again."));
        return;
      }
      setSnippet(body.snippet);
      setConfigured(true);
      setConfirmRotate(false);
    } finally {
      setBusy(null);
    }
  }

  async function copy() {
    if (!snippet) return;
    try {
      await navigator.clipboard.writeText(snippet);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setError("Your browser blocked the clipboard. Select the text below and copy it.");
    }
  }

  const beatAt = website.wp_connect_loopback_at ? new Date(website.wp_connect_loopback_at) : null;
  const ackAt = website.wp_connect_last_ack ? new Date(website.wp_connect_last_ack) : null;
  const beating = beatAt !== null && ackAt !== null && now - ackAt.getTime() < FRESH_MS;
  const code = website.wp_connect_loopback_status ?? null;

  let heartbeat: { label: string; tone: string; detail: string };
  if (!configured) {
    heartbeat = { label: "Not set up", tone: "text-muted-foreground", detail: "Generate the snippet and paste it into the site." };
  } else if (!beatAt) {
    heartbeat = {
      label: "No heartbeat yet",
      tone: "text-amber-600 dark:text-amber-400",
      detail: website.wp_connect_last_ack
        ? "This site runs an older copy of the snippet. Paste the current one to turn the heartbeat on."
        : "Waiting for the site to report in. It does on its next visit after the snippet is pasted.",
    };
  } else if (beating) {
    heartbeat = {
      label: code && code >= 500 ? `Homepage error (HTTP ${code})` : "Reporting",
      tone: code && code >= 500 ? "text-red-600 dark:text-red-400" : "text-emerald-600 dark:text-emerald-400",
      detail: code
        ? `Last report ${fmtDateTime(ackAt!.toISOString())}. The site loaded its own homepage: HTTP ${code}.`
        : `Last report ${fmtDateTime(ackAt!.toISOString())}. The site could not reach its own homepage, so only WordPress itself is confirmed.`,
    };
  } else {
    heartbeat = {
      label: "Quiet",
      tone: "text-amber-600 dark:text-amber-400",
      detail: `Last report ${fmtDateTime((ackAt ?? beatAt).toISOString())}. WordPress cron only runs when the site gets visits, so a quiet site goes quiet here too.`,
    };
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <HeartPulse className="h-4 w-4" />
          WP Connect
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-sm text-muted-foreground max-w-prose">
          A PHP snippet for WordPress sites. It adds one-click wp-admin login and the activity log, and
          every 5 minutes it reports the site&rsquo;s uptime to us from the site itself. That report keeps
          uptime working when the host&rsquo;s firewall (SiteGround and similar) blocks our monitor, with no
          IP to allowlist. Paste it into WPCode or Code Snippets as a PHP snippet,{" "}
          <strong className="text-foreground">replacing</strong> any older Stacks Monitor snippet.
        </p>

        <div className="flex flex-wrap items-center gap-x-6 gap-y-1 text-xs text-muted-foreground">
          <span>
            Heartbeat: <strong className={heartbeat.tone}>{heartbeat.label}</strong>
          </span>
          {website.wp_connect_version ? <span>Snippet version {website.wp_connect_version}</span> : null}
        </div>
        <p className="text-xs text-muted-foreground max-w-prose">{heartbeat.detail}</p>

        <div className="flex flex-wrap items-center gap-2">
          {configured ? (
            <Button size="sm" onClick={() => load("GET")} disabled={busy !== null}>
              {busy === "get" && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              Show snippet
            </Button>
          ) : (
            <Button size="sm" onClick={() => load("POST")} disabled={busy !== null}>
              {busy === "rotate" && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              Generate snippet
            </Button>
          )}
          {configured && !confirmRotate && (
            <Button size="sm" variant="ghost" onClick={() => setConfirmRotate(true)} disabled={busy !== null}>
              New secret
            </Button>
          )}
        </div>

        {confirmRotate && (
          <div className="flex flex-wrap items-center gap-2 rounded-md border p-3 text-sm">
            <p className="flex-1 min-w-[14rem] text-muted-foreground">
              A new secret stops the pasted snippet and every login link until you paste the new one. Nothing
              the site records in the meantime is lost.
            </p>
            <Button size="sm" variant="destructive" onClick={() => load("POST")} disabled={busy !== null}>
              {busy === "rotate" && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              Create new secret
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setConfirmRotate(false)} disabled={busy !== null}>
              Cancel
            </Button>
          </div>
        )}

        {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}

        {snippet && (
          <div className="relative rounded-md bg-muted border">
            <pre className="max-h-80 overflow-auto p-4 text-xs font-mono whitespace-pre">{snippet}</pre>
            <Button size="sm" variant="secondary" className="absolute top-2 right-2 h-7 gap-1" onClick={copy}>
              {copied ? <Check className="h-3.5 w-3.5 text-emerald-500" /> : <Copy className="h-3.5 w-3.5" />}
              {copied ? "Copied" : "Copy"}
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
