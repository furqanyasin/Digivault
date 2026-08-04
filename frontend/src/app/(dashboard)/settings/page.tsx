import { getAccessToken } from "@/lib/server-token";
import { api } from "@/lib/api";
import type { User, Team } from "@/lib/api";
import { AccountClient } from "@/components/account-client";
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

  const activeTeam = teams.find((t) => t.id === user?.active_team) ?? teams[0] ?? null;
  const role = activeTeam?.my_role ?? "developer";
  const isManager = role === "owner" || role === "manager";

  // Only fetched for managers — the endpoint is theirs, and asking as a
  // developer would 403 on every page load.
  let settings: TeamSettings | null = null;
  if (isManager && user?.active_team) {
    settings = await api
      .get<TeamSettings>(`/api/v1/auth/teams/${user.active_team}/settings/`, token)
      .catch(() => null);
  }

  return { user, activeTeam, role, isManager, settings };
}

/** Personal and team settings on one page.
 *
 *  These used to be two routes — My Account (everyone) and Settings (managers
 *  only). Merged, but the split still matters: everyone gets the personal half,
 *  and the team half renders only for owners and managers. Because the page is
 *  now reachable by everyone, `settings` had to come out of FeatureGuard's
 *  MANAGER_ONLY set, or a developer would be redirected away from their own
 *  profile and 2FA.
 */
export default async function SettingsPage() {
  const token = await getAccessToken();
  if (!token) return <div className="p-8 text-muted-foreground">Not authenticated.</div>;

  const { user, activeTeam, role, isManager, settings } = await getData(token);

  return (
    // Two columns for managers, who have both halves to show; a single narrow
    // column for everyone else, since one column stretched across a wide screen
    // reads worse than a contained one.
    <div className={`p-8 space-y-8 ${isManager ? "max-w-6xl" : "max-w-2xl"}`}>
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Settings</h1>
        <p className="text-muted-foreground mt-1">
          {isManager
            ? "Your profile, security, and team configuration."
            : "Your profile and account security."}
        </p>
      </div>

      <div className={isManager ? "grid items-start gap-8 lg:grid-cols-2" : undefined}>
        <section className="space-y-4">
          {isManager && (
            <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Your account
            </h2>
          )}
          <AccountClient
            name={user ? `${user.first_name} ${user.last_name}`.trim() : ""}
            email={user?.email ?? "—"}
            role={role}
            teamName={activeTeam?.name ?? "None"}
          />
        </section>

        {isManager && (
          <section className="space-y-4">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Team
            </h2>
            <SettingsClient settings={settings} activeTeamId={activeTeam?.id ?? null} />
          </section>
        )}
      </div>
    </div>
  );
}
