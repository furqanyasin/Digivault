import Image from "next/image";
import { LogoutButton } from "@/components/logout-button";
import { NavLinks } from "@/components/nav-links";
import { ThemeToggle } from "@/components/theme-toggle";
import { TeamSwitcher } from "@/components/team-switcher";
import { ChatWidget } from "@/components/chat-widget";
import { ExtensionAuthBridge } from "@/components/extension-auth-bridge";
import { getAccessToken } from "@/lib/server-token";
import { api } from "@/lib/api";
import type { Team, User } from "@/lib/api";
import { GlobalSearch } from "@/components/global-search";
import { FeatureGuard } from "@/components/feature-guard";

// `feature` maps a nav item to a custom-access key; `always` items are shown to
// everyone (incl. custom members). Items with neither and managerOnly are
// management-only and hidden from custom members.
const navItems = [
  { href: "/dashboard", label: "Dashboard", icon: "dashboard", always: true },
  { href: "/clients", label: "Clients", icon: "clients", feature: "clients" },
  { href: "/websites", label: "Websites", icon: "websites", feature: "websites" },
  // Monitors merged into each website's Uptime tab; /monitors stays routable
  // for monitor create/edit deep links.
  { href: "/renewals", label: "Renewal Center", icon: "renewals", managerOnly: true, feature: "renewals" },
  // Status Pages removed from the sidebar; /status-pages stays routable and each
  // website's Uptime tab links to its public page.
  { href: "/alerts", label: "Alerts", icon: "alerts", feature: "alerts" },
  // Reports moved into each website's Reports tab; the standalone page is gone.
  { href: "/credentials", label: "Credentials", icon: "credentials", feature: "credentials" },
  // Team, Renewal Center and Settings are owner/manager-only. Developers manage
  // their own security in Account and see their own actions in the Activity Log
  // (the backend scopes the log per-user for non-managers).
  { href: "/team", label: "Team", icon: "team", managerOnly: true },
  { href: "/logs", label: "Activity Log", icon: "logs", feature: "activity_log" },
  { href: "/heatmap", label: "Heatmap", icon: "heatmap", always: true },
  { href: "/account", label: "My Account", icon: "account", always: true },
  { href: "/settings", label: "Settings", icon: "settings", managerOnly: true },
];

export default async function DashboardLayout({ children }: { children: React.ReactNode }) {
  const token = await getAccessToken();
  const [user, teams] = await Promise.all([
    token ? api.get<User>("/api/v1/auth/me/", token).catch(() => null) : null,
    token ? api.get<Team[]>("/api/v1/auth/teams/", token).catch(() => [] as Team[]) : [] as Team[],
  ]);

  const activeTeam = teams.find((t) => t.id === user?.active_team) ?? teams[0] ?? null;
  const isOwner = activeTeam?.my_role === "owner";
  const isManager = isOwner || activeTeam?.my_role === "manager";
  const myFeatures = activeTeam?.my_features ?? [];
  // Feature access now gates every role except owner. Owner sees everything;
  // manager-only sections stay role-gated; feature-keyed items are shown only
  // when the member's granted features include them.
  const visibleNavItems = navItems.filter((item) => {
    if (item.always) return true;
    if (item.managerOnly && !isManager) return false;
    if (isOwner) return true;
    if (item.feature) return myFeatures.includes(item.feature);
    return true;
  });

  return (
    <div className="flex min-h-screen">
      {/* Sidebar — sticks to the top while the page body scrolls */}
      <aside className="w-64 shrink-0 border-r bg-card flex flex-col sticky top-0 h-screen self-start overflow-y-auto">
        <div className="flex items-center gap-2.5 px-6 py-5 border-b">
          {/* Intrinsic 872x635 is declared so the ratio is exact and nothing
              shifts while it loads; CSS sizes it. A square box would squash it.
              Local .svg is served unoptimized automatically — no config needed. */}
          <Image
            src="/digivault-icon.svg"
            alt="Digivault"
            width={872}
            height={635}
            priority
            className="h-7 w-auto"
          />
          <span className="font-bold text-lg tracking-tight">Digivault</span>
        </div>

        {/* Team switcher */}
        {teams.length > 0 && (
          <div className="border-b px-1 py-1">
            <TeamSwitcher teams={teams} activeTeamId={user?.active_team ?? null} />
          </div>
        )}

        <div className="border-b py-1">
          <GlobalSearch />
        </div>

        <NavLinks items={visibleNavItems.map(({ href, label, icon }) => ({ href, label, icon }))} />
        <div className="border-t px-3 py-3 space-y-1">
          <ThemeToggle />
          <LogoutButton />
        </div>
      </aside>

      {/* Main content — flows in normal document flow so the body scrolls when
          content is taller than the viewport. min-w-0 lets wide children (e.g.
          tables) stay contained instead of forcing page-wide overflow. */}
      <main className="flex-1 min-w-0">
        {!isOwner && <FeatureGuard features={myFeatures} isManager={isManager} />}
        {children}
      </main>

      <ChatWidget />
      <ExtensionAuthBridge />
    </div>
  );
}
