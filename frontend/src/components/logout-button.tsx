"use client";

import { useRouter } from "next/navigation";
import { LogOut } from "lucide-react";
import { Button } from "@/components/ui/button";

export function LogoutButton() {
  const router = useRouter();

  async function handleLogout() {
    await fetch("/api/auth/logout", { method: "POST" });
    // Tell the browser extension to drop its stored tokens too, so signing out
    // of the portal signs out of the extension. No-op if it isn't installed.
    try {
      window.postMessage({ type: "STACKSMONITOR_EXTENSION_LOGOUT" }, window.location.origin);
    } catch {
      /* best-effort */
    }
    router.push("/login");
    router.refresh();
  }

  return (
    <Button variant="ghost" size="sm" className="w-full justify-start gap-2" onClick={handleLogout}>
      <LogOut className="h-4 w-4" />
      Sign out
    </Button>
  );
}
