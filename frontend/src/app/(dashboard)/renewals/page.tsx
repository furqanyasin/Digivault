import { getAccessToken } from "@/lib/server-token";
import { api } from "@/lib/api";
import type { User, Team } from "@/lib/api";
import { RenewalsClient } from "@/components/renewals-client";

export default async function RenewalsPage() {
  const token = await getAccessToken();
  const [user, teams] = await Promise.all([
    token ? api.get<User>("/api/v1/auth/me/", token).catch(() => null) : null,
    token ? api.get<Team[]>("/api/v1/auth/teams/", token).catch(() => [] as Team[]) : [] as Team[],
  ]);
  const activeTeam = teams.find((t) => t.id === user?.active_team) ?? teams[0] ?? null;
  const role = activeTeam?.my_role ?? "developer";

  // Renewal Center is owner/manager-only.
  if (role !== "owner" && role !== "manager") {
    return (
      <div className="p-8 max-w-2xl">
        <h1 className="text-3xl font-bold tracking-tight">Renewal Center</h1>
        <p className="text-muted-foreground mt-3">
          The Renewal Center is available to your team&apos;s owners and managers.
        </p>
      </div>
    );
  }

  return <RenewalsClient />;
}
