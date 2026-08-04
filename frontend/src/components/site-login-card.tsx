"use client";

import { useState } from "react";
import { LogIn, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useToast } from "@/hooks/use-toast";

interface CredentialSummary {
  id: string;
  name: string | null;
  credential_type: string;
  login_url: string;
}

/** Opens a logged-in session on the client's own site, rather than sending you
 *  to the credentials list to copy a password by hand.
 *
 *  Two routes, best first:
 *   1. WordPress with SSO configured — mint a single-use link and land straight
 *      in wp-admin, already authenticated. No password changes hands.
 *   2. Anything else — open the login URL saved on the site's credentials, where
 *      the browser extension fills the saved details in.
 *
 *  Sits in the header beside Visit and Run check, because it is an action on the
 *  site rather than a piece of information about it.
 */
export function SiteLoginButton({
  websiteId,
  wpSsoConfigured,
}: {
  websiteId: string;
  wpSsoConfigured: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const { toast } = useToast();

  /** Opened synchronously on click, then pointed at the URL once we have it.
   *  Calling window.open after an await loses the user-gesture context and gets
   *  caught by popup blockers. */
  function openDeferred(): Window | null {
    return window.open("", "_blank", "noopener,noreferrer");
  }

  function fail(tab: Window | null, title: string, description?: string) {
    tab?.close();
    toast({ variant: "destructive", title, description });
  }

  async function openLogin() {
    setBusy(true);
    const tab = openDeferred();
    try {
      if (wpSsoConfigured) {
        const res = await fetch(`/api/websites/${websiteId}/wp-login`, { method: "POST" });
        const data = await res.json().catch(() => ({}));
        if (res.ok && data?.url) {
          if (tab) tab.location.href = data.url;
          else window.open(data.url, "_blank", "noopener,noreferrer");
          return;
        }
        fail(tab, "Could not open the login", data?.detail ?? "The site did not return a login link.");
        return;
      }

      const res = await fetch(`/api/websites/${websiteId}/credentials`);
      const json = await res.json().catch(() => ({}));
      const list: CredentialSummary[] = Array.isArray(json?.data)
        ? json.data
        : Array.isArray(json)
          ? json
          : [];
      const withUrl = list.find((c) => c.login_url);
      if (withUrl) {
        if (tab) tab.location.href = withUrl.login_url;
        else window.open(withUrl.login_url, "_blank", "noopener,noreferrer");
        return;
      }
      fail(
        tab,
        "No login saved for this site",
        list.length
          ? "The saved credentials have no login URL. Add one on the Setup tab."
          : "Add a credential with a login URL on the Setup tab."
      );
    } catch {
      fail(tab, "Could not open the login", "Check your connection and try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Button
      variant="outline"
      size="sm"
      onClick={openLogin}
      disabled={busy}
      title={wpSsoConfigured ? "One-click WP admin login" : "Open the saved login page"}
    >
      {busy ? (
        <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
      ) : (
        <LogIn className="h-3.5 w-3.5 mr-1.5" />
      )}
      Log in
    </Button>
  );
}
