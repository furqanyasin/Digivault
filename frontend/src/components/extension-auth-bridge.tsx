"use client";

import { useEffect } from "react";

// Syncs the web session into the Stacks Monitor browser extension: on load of an
// authenticated page it fetches the current tokens and posts them to the page,
// where the extension's content script picks them up (STACKSMONITOR_EXTENSION_AUTH)
// and stores them. This means logging into the portal also logs into the
// extension. No-op when the extension isn't installed — the message is simply
// unheard.
//
// The extension only listens on the dashboard's own origin, and it decides
// that asynchronously, so the first post can arrive before it is listening.
// It announces itself with STACKSMONITOR_EXTENSION_READY; answering that with a
// second post is what makes the sync reliable rather than a race.
export function ExtensionAuthBridge() {
  useEffect(() => {
    let cancelled = false;

    const sync = async () => {
      try {
        const res = await fetch("/api/auth/ext-tokens");
        if (!res.ok || cancelled) return;
        const { access, refresh, email } = await res.json();
        if (!access || !refresh) return;
        window.postMessage(
          { type: "STACKSMONITOR_EXTENSION_AUTH", access, refresh, email },
          window.location.origin
        );
      } catch {
        // extension sync is best-effort
      }
    };

    const onMessage = (e: MessageEvent) => {
      if (e.source !== window || e.origin !== window.location.origin) return;
      if (e.data?.type === "STACKSMONITOR_EXTENSION_READY") void sync();
    };

    window.addEventListener("message", onMessage);
    void sync();
    return () => {
      cancelled = true;
      window.removeEventListener("message", onMessage);
    };
  }, []);

  return null;
}
