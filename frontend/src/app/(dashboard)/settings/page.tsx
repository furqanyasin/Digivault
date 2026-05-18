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
  const { settings, activeTeamId } = await getData(token);
  return <SettingsClient settings={settings} activeTeamId={activeTeamId} />;
}
