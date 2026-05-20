import Link from "next/link";
import { Shield, Globe, Bell, Key, Users, LayoutDashboard, Activity, MonitorCheck, Building2, Settings, ClipboardList } from "lucide-react";
import { LogoutButton } from "@/components/logout-button";
import { ThemeToggle } from "@/components/theme-toggle";
import { TeamSwitcher } from "@/components/team-switcher";
import { ChatWidget } from "@/components/chat-widget";
import { getAccessToken } from "@/lib/server-token";
import { api } from "@/lib/api";
import type { Team, User } from "@/lib/api";
import { GlobalSearch } from "@/components/global-search";

const navItems = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/clients", label: "Clients", icon: Building2 },
  { href: "/websites", label: "Websites", icon: Globe },
  { href: "/monitors", label: "Monitors", icon: Activity },
  { href: "/status-pages", label: "Status Pages", icon: MonitorCheck },
  { href: "/alerts", label: "Alerts", icon: Bell },
  { href: "/credentials", label: "Credentials", icon: Key },
  { href: "/team", label: "Team", icon: Users },
  { href: "/logs", label: "Activity Log", icon: ClipboardList },
  { href: "/settings", label: "Settings", icon: Settings },
];

export default async function DashboardLayout({ children }: { children: React.ReactNode }) {
  const token = await getAccessToken();
  const [user, teams] = await Promise.all([
    token ? api.get<User>("/api/v1/auth/me/", token).catch(() => null) : null,
    token ? api.get<Team[]>("/api/v1/auth/teams/", token).catch(() => [] as Team[]) : [] as Team[],
  ]);

  return (
    <div className="flex min-h-screen">
      {/* Sidebar */}
      <aside className="w-64 shrink-0 border-r bg-card flex flex-col">
        <div className="flex items-center gap-2 px-6 py-5 border-b">
          <Shield className="h-6 w-6 text-primary" />
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

        <nav className="flex-1 px-3 py-4 space-y-1">
          {navItems.map(({ href, label, icon: Icon }) => (
            <Link
              key={href}
              href={href}
              className="flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium text-muted-foreground hover:bg-accent hover:text-accent-foreground transition-colors"
            >
              <Icon className="h-4 w-4" />
              {label}
            </Link>
          ))}
        </nav>
        <div className="border-t px-3 py-3 space-y-1">
          <ThemeToggle />
          <LogoutButton />
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto">
        {children}
      </main>

      <ChatWidget />
    </div>
  );
}
