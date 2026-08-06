import { getAccessToken } from "@/lib/server-token";
import { api } from "@/lib/api";
import type { Website, Credential, User, TeamMember } from "@/lib/api";
import { CredentialsVaultClient } from "@/components/credentials-vault-client";

export default async function CredentialsPage() {
  const token = await getAccessToken();

  const [credentials, websites, me] = await Promise.all([
    // getAll on both: these lists page at 25, and the vault needs every
    // credential plus every website for the "link to website" picker.
    api.getAll<Credential>("/api/v1/credentials/", token ?? "").catch(() => [] as Credential[]),
    api.getAll<Website>("/api/v1/websites/", token ?? "").catch(() => [] as Website[]),
    api.get<User>("/api/v1/auth/me/", token ?? "").catch(() => null as User | null),
  ]);

  let myRole = "developer";
  if (me?.active_team) {
    const members = await api
      .get<TeamMember[]>(`/api/v1/auth/teams/${me.active_team}/members/`, token ?? "")
      .catch(() => [] as TeamMember[]);
    const membership = members.find((m) => m.user.id === me.id);
    if (membership) myRole = membership.role;
  }

  return (
    <CredentialsVaultClient
      initialCredentials={credentials}
      websites={websites}
      myRole={myRole}
      teamId={me?.active_team ?? null}
    />
  );
}
