import { getAccessToken } from "@/lib/server-token";
import { api } from "@/lib/api";
import type { User, Team, TeamMember, SubTeam } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Users } from "lucide-react";
import { TeamManagementClient } from "@/components/team-management-client";

interface PasswordResetReq {
  id: string;
  user_email: string;
  user_name: string;
  status: string;
  created_at: string;
}

async function getData(token: string) {
  const [userResult, teamsResult] = await Promise.allSettled([
    api.get<User>("/api/v1/auth/me/", token),
    api.getAll<Team>("/api/v1/auth/teams/", token),
  ]);

  const user = userResult.status === "fulfilled" ? userResult.value : null;
  const teams = teamsResult.status === "fulfilled" ? teamsResult.value : [];

  let members: TeamMember[] = [];
  let resetRequests: PasswordResetReq[] = [];
  let groups: SubTeam[] = [];
  let activeTeam: Team | null = null;

  if (user && teams.length > 0) {
    activeTeam = teams.find((t) => t.id === user.active_team) ?? teams[0];
    if (activeTeam) {
      const [membersResult, resetResult, groupsResult] = await Promise.allSettled([
        api.getAll<TeamMember>(`/api/v1/auth/teams/${activeTeam.id}/members/`, token),
        api.getAll<PasswordResetReq>("/api/v1/auth/password-reset/", token),
        api.getAll<SubTeam>(`/api/v1/auth/teams/${activeTeam.id}/sub-teams/`, token),
      ]);
      members = membersResult.status === "fulfilled" && Array.isArray(membersResult.value)
        ? membersResult.value : [];
      resetRequests = resetResult.status === "fulfilled" && Array.isArray(resetResult.value)
        ? resetResult.value : [];
      // Tolerated as empty if the backend predates groups: the frontend
      // deploys separately, so this page must still render without them.
      groups = groupsResult.status === "fulfilled" && Array.isArray(groupsResult.value)
        ? groupsResult.value : [];
    }
  }

  return { user, members, resetRequests, groups, activeTeam };
}

export default async function TeamPage() {
  const token = await getAccessToken();
  const { user, members, resetRequests, groups, activeTeam } = await getData(token ?? "");

  const myMembership = user ? members.find((m) => m.user.id === user.id) : null;
  const myRole = activeTeam?.my_role ?? myMembership?.role ?? "viewer";
  const myMembershipId = myMembership?.id ?? "";

  // Team management is owner/manager-only — developers don't see this page.
  if (myRole !== "owner" && myRole !== "manager") {
    return (
      <div className="p-8">
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16 gap-3 text-center">
            <Users className="h-10 w-10 text-muted-foreground opacity-40" />
            <p className="text-lg font-medium">Team management is restricted</p>
            <p className="text-muted-foreground text-sm max-w-sm">
              Only team owners and managers can view and manage team members.
              Contact your team manager if you need access changed.
            </p>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="p-8">
      {activeTeam && (
        <TeamManagementClient
          teamId={activeTeam.id}
          teamName={activeTeam.name}
          plan={activeTeam.plan}
          myRole={myRole}
          myMembershipId={myMembershipId}
          initialMembers={members}
          initialResetRequests={resetRequests}
          initialGroups={groups}
        />
      )}
    </div>
  );
}
