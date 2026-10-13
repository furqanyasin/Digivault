import { getAccessToken } from "@/lib/server-token";
import { api } from "@/lib/api";
import type { Website, Credential, User, TeamMember, SubTeam, VaultFolder } from "@/lib/api";
import { CredentialsVaultClient } from "@/components/credentials-vault-client";

export default async function CredentialsPage() {
  const token = await getAccessToken();

  const [credentials, websites, me, folders] = await Promise.all([
    // getAll on both: these lists page at 25, and the vault needs every
    // credential plus every website for the "link to website" picker.
    api.getAll<Credential>("/api/v1/credentials/", token ?? "").catch(() => [] as Credential[]),
    api.getAll<Website>("/api/v1/websites/", token ?? "").catch(() => [] as Website[]),
    api.get<User>("/api/v1/auth/me/", token ?? "").catch(() => null as User | null),
    // Not paginated (one small list); falls back to none on an older backend.
    api.get<VaultFolder[]>("/api/v1/credentials/folders/", token ?? "")
      .catch(() => [] as VaultFolder[]),
  ]);

  let myRole = "developer";
  let groups: SubTeam[] = [];
  if (me?.active_team) {
    const members = await api
      .getAll<TeamMember>(`/api/v1/auth/teams/${me.active_team}/members/`, token ?? "")
      .catch(() => [] as TeamMember[]);
    const membership = members.find((m) => m.user.id === me.id);
    if (membership) myRole = membership.role;
    // Only the owner can read or write group grants, so only they need the
    // list. Falls back to empty if the backend predates groups: the frontend
    // deploys separately and this page must still render.
    if (myRole === "owner") {
      groups = await api
        .getAll<SubTeam>(`/api/v1/auth/teams/${me.active_team}/sub-teams/`, token ?? "")
        .catch(() => [] as SubTeam[]);
    }
  }

  return (
    <CredentialsVaultClient
      initialCredentials={credentials}
      websites={websites}
      myRole={myRole}
      teamId={me?.active_team ?? null}
      groups={groups}
      initialFolders={Array.isArray(folders) ? folders : []}
    />
  );
}
