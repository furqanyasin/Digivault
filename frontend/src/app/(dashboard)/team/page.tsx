import { getAccessToken } from "@/lib/server-token";
import { api } from "@/lib/api";
import type { User, Team, TeamMember } from "@/lib/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Users, UserCircle } from "lucide-react";
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
    api.get<Team[]>("/api/v1/auth/teams/", token),
  ]);

  const user = userResult.status === "fulfilled" ? userResult.value : null;
  const teams = teamsResult.status === "fulfilled" ? teamsResult.value : [];

  let members: TeamMember[] = [];
  let resetRequests: PasswordResetReq[] = [];
  let activeTeam: Team | null = null;

  if (user && teams.length > 0) {
    activeTeam = teams.find((t) => t.id === user.active_team) ?? teams[0];
    if (activeTeam) {
      const [membersResult, resetResult] = await Promise.allSettled([
        api.get<TeamMember[]>(`/api/v1/auth/teams/${activeTeam.id}/members/`, token),
        api.get<PasswordResetReq[]>("/api/v1/auth/password-reset/", token),
      ]);
      members = membersResult.status === "fulfilled" && Array.isArray(membersResult.value)
        ? membersResult.value : [];
      resetRequests = resetResult.status === "fulfilled" && Array.isArray(resetResult.value)
        ? resetResult.value : [];
    }
  }

  return { user, teams, members, resetRequests, activeTeam };
}

export default async function TeamPage() {
  const token = await getAccessToken();
  const { user, teams, members, resetRequests, activeTeam } = await getData(token ?? "");

  const myMembership = user ? members.find((m) => m.user.id === user.id) : null;
  const myRole = myMembership?.role ?? "viewer";
  const myMembershipId = myMembership?.id ?? "";

  return (
    <div className="p-8 space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Team</h1>
        <p className="text-muted-foreground mt-1">Manage your team members and invitations</p>
      </div>

      <div className="grid md:grid-cols-2 gap-6">
        {/* Profile */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <UserCircle className="h-5 w-5" />
              Your profile
            </CardTitle>
            <CardDescription>Account details</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {user ? (
              <>
                <Row label="Name" value={`${user.first_name} ${user.last_name}`.trim() || "—"} />
                <Row label="Email" value={user.email} mono />
                <Row label="Timezone" value={user.timezone || "—"} />
                <Row label="Your role" value={myRole} />
                <div className="flex items-center justify-between pt-1">
                  <span className="text-sm text-muted-foreground">Active team</span>
                  <Badge variant="outline">{activeTeam?.name ?? "None"}</Badge>
                </div>
              </>
            ) : (
              <p className="text-muted-foreground text-sm">Could not load profile.</p>
            )}
          </CardContent>
        </Card>

        {/* Team info */}
        {activeTeam && (
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Users className="h-5 w-5" />
                {activeTeam.name}
              </CardTitle>
              <CardDescription>Team details</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <Row label="Slug" value={activeTeam.slug} mono />
              <Row label="Plan" value={activeTeam.plan} />
              <div className="flex items-center justify-between pt-1">
                <span className="text-sm text-muted-foreground">Members</span>
                <Badge variant="secondary">{members.length}</Badge>
              </div>
            </CardContent>
          </Card>
        )}
      </div>

      {activeTeam && (
        <TeamManagementClient
          teamId={activeTeam.id}
          myRole={myRole}
          myMembershipId={myMembershipId}
          initialMembers={members}
          initialResetRequests={resetRequests}
        />
      )}

      {/* Other teams */}
      {teams.length > 1 && (
        <Card>
          <CardHeader>
            <CardTitle>Your Teams ({teams.length})</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b">
                  <th className="text-left px-4 py-2 font-medium text-muted-foreground">Name</th>
                  <th className="text-left px-4 py-2 font-medium text-muted-foreground">Slug</th>
                  <th className="text-left px-4 py-2 font-medium text-muted-foreground">Plan</th>
                  <th className="text-left px-4 py-2 font-medium text-muted-foreground">Status</th>
                </tr>
              </thead>
              <tbody>
                {teams.map((team) => (
                  <tr key={team.id} className="border-b last:border-0">
                    <td className="px-4 py-2 font-medium">{team.name}</td>
                    <td className="px-4 py-2 font-mono text-xs">{team.slug}</td>
                    <td className="px-4 py-2 capitalize">{team.plan}</td>
                    <td className="px-4 py-2">
                      {team.id === user?.active_team ? (
                        <Badge variant="success">Active</Badge>
                      ) : (
                        <Badge variant="secondary">Other</Badge>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function Row({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-center justify-between border-b pb-2 last:border-0 last:pb-0">
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className={`font-medium text-sm ${mono ? "font-mono" : ""}`}>{value}</span>
    </div>
  );
}
