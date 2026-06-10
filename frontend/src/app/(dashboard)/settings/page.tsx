import { getAccessToken } from "@/lib/server-token";
import { api } from "@/lib/api";
import type { User, Team } from "@/lib/api";
import { SettingsClient } from "@/components/settings-client";

interface TeamSettings {
  id: string;
  name: string;
  clickup_api_token: string;
  clickup_api_token_masked: string;
  clickup_connected: boolean;
}

async function getData(token: string) {
  const [user, teams] = await Promise.all([
    api.get<User>("/api/v1/auth/me/", token).catch(() => null),
    api.get<Team[]>("/api/v1/auth/teams/", token).catch(() => [] as Team[]),
  ]);

  let settings: TeamSettings | null = null;
  if (user?.active_team) {
    settings = await api
      .get<TeamSettings>(`/api/v1/auth/teams/${user.active_team}/settings/`, token)
      .catch(() => null);
  }

  return { user, teams, settings, activeTeamId: user?.active_team ?? null };
}

export default async function SettingsPage() {
  const token = await getAccessToken();
  if (!token) return <div className="p-8 text-muted-foreground">Not authenticated.</div>;
  const { settings, activeTeamId, teams } = await getData(token);

  // Settings (ClickUp + team config) is owner/manager-only.
  const activeTeam = teams.find((t) => t.id === activeTeamId) ?? teams[0] ?? null;
  const role = activeTeam?.my_role ?? "developer";
  if (role !== "owner" && role !== "manager") {
    return (
      <div className="p-8 max-w-2xl">
        <h1 className="text-3xl font-bold tracking-tight">Settings</h1>
        <p className="text-muted-foreground mt-3">
          Settings are managed by your team&apos;s owners and managers. You can manage your
          own security in <a href="/account" className="text-primary hover:underline">My Account</a>.
        </p>
      </div>
    );
  }

  return <SettingsClient settings={settings} activeTeamId={activeTeamId} />;
}
