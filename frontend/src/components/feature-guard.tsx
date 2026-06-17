"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";

// Maps the first path segment to a custom-access feature key. Kept in sync with
// the sidebar nav and the backend CUSTOM_FEATURE_KEYS.
const ROUTE_FEATURE: Record<string, string> = {
  clients: "clients",
  websites: "websites",
  monitors: "monitors",
  renewals: "renewals",
  "status-pages": "status_pages",
  alerts: "alerts",
  reports: "reports",
  credentials: "credentials",
  logs: "activity_log",
};

// Management-only areas a custom member can never reach.
const MANAGER_ONLY = new Set(["team", "settings"]);
// Always allowed regardless of granted features.
const ALWAYS = new Set(["", "dashboard", "account"]);

/**
 * Client-side guard for "custom" members: redirects them away from any section
 * their feature_access doesn't include. Frontend-only enforcement (the API is
 * not restricted) — render only when the active role is "custom".
 */
export function FeatureGuard({ features }: { features: string[] }) {
  const pathname = usePathname();
  const router = useRouter();

  useEffect(() => {
    const seg = (pathname.split("/")[1] ?? "").toLowerCase();
    if (ALWAYS.has(seg)) return;
    if (MANAGER_ONLY.has(seg)) {
      router.replace("/dashboard");
      return;
    }
    const feature = ROUTE_FEATURE[seg];
    if (feature && !features.includes(feature)) {
      router.replace("/dashboard");
    }
  }, [pathname, features, router]);

  return null;
}
