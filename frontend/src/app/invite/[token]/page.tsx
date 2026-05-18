import { notFound } from "next/navigation";
import Link from "next/link";
import { Users, ArrowRight } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { InvitationAcceptClient } from "@/components/invitation-accept-client";

interface InviteData {
  id: string;
  team_name: string;
  team_slug: string;
  invited_by: string;
  email: string;
  role: string;
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default async function InvitePage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = await params;

  const res = await fetch(`${API_BASE}/api/v1/auth/invitations/${token}/`, { cache: "no-store" });
  if (!res.ok) notFound();

  const invite: InviteData = await res.json();

  return (
    <div className="min-h-screen flex items-center justify-center bg-muted/30 p-4">
      <div className="w-full max-w-md space-y-4">
        <div className="text-center space-y-2">
          <div className="inline-flex items-center justify-center w-12 h-12 rounded-full bg-primary/10 mb-2">
            <Users className="h-6 w-6 text-primary" />
          </div>
          <h1 className="text-2xl font-bold tracking-tight">You&apos;re invited!</h1>
          <p className="text-muted-foreground text-sm">
            {invite.invited_by} has invited you to join <strong>{invite.team_name}</strong>.
          </p>
        </div>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-lg">Invitation details</CardTitle>
            <CardDescription>Review before accepting</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <Row label="Team" value={invite.team_name} />
            <Row label="Your email" value={invite.email} mono />
            <Row label="Role" value={invite.role} capitalize />
            <Row label="Invited by" value={invite.invited_by} />
          </CardContent>
        </Card>

        <InvitationAcceptClient token={token} inviteEmail={invite.email} />

        <p className="text-center text-xs text-muted-foreground">
          Don&apos;t have an account?{" "}
          <Link href={`/register?email=${encodeURIComponent(invite.email)}&next=/invite/${token}`} className="underline underline-offset-2">
            Register first <ArrowRight className="inline h-3 w-3" />
          </Link>
        </p>
      </div>
    </div>
  );
}

function Row({ label, value, mono, capitalize }: { label: string; value: string; mono?: boolean; capitalize?: boolean }) {
  return (
    <div className="flex items-center justify-between border-b pb-2 last:border-0 last:pb-0">
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className={`font-medium text-sm ${mono ? "font-mono text-xs" : ""} ${capitalize ? "capitalize" : ""}`}>
        {value}
      </span>
    </div>
  );
}
