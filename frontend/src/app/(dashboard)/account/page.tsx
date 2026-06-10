import { getAccessToken } from "@/lib/server-token";
import { api } from "@/lib/api";
import type { User, Team } from "@/lib/api";
import { AccountClient } from "@/components/account-client";

export default async function AccountPage() {
  const token = await getAccessToken();
  if (!token) return <div className="p-8 text-muted-foreground">Not authenticated.</div>;

  const [user, teams] = await Promise.all([
    api.get<User>("/api/v1/auth/me/", token).catch(() => null),
    api.get<Team[]>("/api/v1/auth/teams/", token).catch(() => [] as Team[]),
  ]);

  const activeTeam = teams.find((t) => t.id === user?.active_team) ?? teams[0] ?? null;

  return (
    <AccountClient
      name={user ? `${user.first_name} ${user.last_name}`.trim() : ""}
      email={user?.email ?? "—"}
      role={activeTeam?.my_role ?? "member"}
      teamName={activeTeam?.name ?? "None"}
    />
  );
}
