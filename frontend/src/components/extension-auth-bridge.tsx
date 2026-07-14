"use client";

import { useEffect } from "react";

// Syncs the web session into the Digivault browser extension: on load of an
// authenticated page it fetches the current tokens and posts them to the page,
// where the extension's content script picks them up (DIGIVAULT_EXTENSION_AUTH)
// and stores them. This means logging into the portal also logs into the
// extension. No-op when the extension isn't installed — the message is simply
// unheard.
export function ExtensionAuthBridge() {
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch("/api/auth/ext-tokens");
        if (!res.ok || cancelled) return;
        const { access, refresh, email } = await res.json();
        if (!access || !refresh) return;
        window.postMessage(
          { type: "DIGIVAULT_EXTENSION_AUTH", access, refresh, email },
          window.location.origin
        );
      } catch {
        // extension sync is best-effort
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return null;
}
