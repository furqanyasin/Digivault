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
  credentials: "credentials",
  logs: "activity_log",
  heatmap: "heatmap",
};

// Management-only areas a custom member can never reach. `logs` is here rather
// than in ROUTE_FEATURE because the Activity Log exposes other people's actions,
// so it is a role decision, not a grantable feature.
const MANAGER_ONLY = new Set(["team", "logs"]);
// Always allowed regardless of granted features.
// `settings` is always allowed: it holds every user's own profile and 2FA,
// and gates the team-configuration half internally by role.
const ALWAYS = new Set(["", "dashboard", "account", "settings"]);

/**
 * Client-side guard for non-owner members: redirects them away from any
 * section their feature_access doesn't include. Managers keep access to the
 * manager-only areas (Team, Settings). Frontend-only enforcement.
 */
export function FeatureGuard({ features, isManager = false }: { features: string[]; isManager?: boolean }) {
  const pathname = usePathname();
  const router = useRouter();

  useEffect(() => {
    const seg = (pathname.split("/")[1] ?? "").toLowerCase();
    if (ALWAYS.has(seg)) return;
    if (MANAGER_ONLY.has(seg)) {
      if (!isManager) router.replace("/dashboard");
      return;
    }
    const feature = ROUTE_FEATURE[seg];
    if (feature && !features.includes(feature)) {
      router.replace("/dashboard");
    }
  }, [pathname, features, router, isManager]);

  return null;
}
