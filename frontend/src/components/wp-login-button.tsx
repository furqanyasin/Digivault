"use client";

import { useState } from "react";
import { KeyRound, LogIn, Loader2, Copy, Check } from "lucide-react";
import { Button } from "@/components/ui/button";

export function WpLoginButton({
  websiteId,
  configured,
}: {
  websiteId: string;
  configured: boolean;
}) {
  const [isConfigured, setIsConfigured] = useState(configured);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [snippet, setSnippet] = useState("");
  const [copied, setCopied] = useState(false);

  async function login() {
    setBusy(true);
    setError("");
    try {
      const res = await fetch(`/api/websites/${websiteId}/wp-login`, { method: "POST" });
      const data = await res.json();
      if (!res.ok) {
        setError(data?.detail ?? "Could not create a login link.");
        return;
      }
      // Single-use, 2-minute link — open straight into wp-admin.
      window.open(data.url, "_blank", "noopener,noreferrer");
    } finally {
      setBusy(false);
    }
  }

  async function generateSecret() {
    setBusy(true);
    setError("");
    try {
      const res = await fetch(`/api/websites/${websiteId}/wp-sso-secret`, { method: "POST" });
      const data = await res.json();
      if (!res.ok) {
        setError(data?.detail ?? "Could not generate the login snippet.");
        return;
      }
      setSnippet(data.snippet);
      setIsConfigured(true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-sm font-medium">
        <KeyRound className="h-4 w-4 text-muted-foreground" />
        WP Admin login
      </div>

      {isConfigured ? (
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" onClick={login} disabled={busy}>
            {busy ? <Loader2 className="h-4 w-4 mr-1 animate-spin" /> : <LogIn className="h-4 w-4 mr-1" />}
            Log in to wp-admin
          </Button>
          <Button size="sm" variant="outline" onClick={generateSecret} disabled={busy}>
            Rotate & re-copy snippet
          </Button>
        </div>
      ) : (
        <Button size="sm" variant="outline" onClick={generateSecret} disabled={busy}>
          {busy ? <Loader2 className="h-4 w-4 mr-1 animate-spin" /> : <KeyRound className="h-4 w-4 mr-1" />}
          Set up WP login
        </Button>
      )}

      {snippet && (
        <div className="rounded-md border bg-muted/40 p-3 space-y-2">
          <div className="flex items-start justify-between gap-2">
            <p className="text-xs text-muted-foreground">
              Add this as a <strong>PHP snippet</strong> in the same{" "}
              <strong>WPCode / Code Snippets</strong> tool you used for the tracking
              script (set it to run site-wide, then activate). No plugin to install —
              rotating replaces it.
            </p>
            <Button
              size="sm"
              variant="ghost"
              className="shrink-0"
              onClick={() => {
                navigator.clipboard.writeText(snippet);
                setCopied(true);
                setTimeout(() => setCopied(false), 1500);
              }}
            >
              {copied ? <Check className="h-4 w-4 text-emerald-600" /> : <Copy className="h-4 w-4" />}
            </Button>
          </div>
          <pre className="max-h-48 overflow-auto rounded bg-background border p-2 text-[11px] leading-snug font-mono">
            {snippet}
          </pre>
        </div>
      )}

      <p className="text-xs text-muted-foreground">
        Opens wp-admin in a new tab using a single-use, role-mapped link — no shared
        passwords. Requires the one-time PHP snippet above on the site.
      </p>
      {error && <p className="text-xs text-red-600">{error}</p>}
    </div>
  );
}
