"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { CheckCircle2, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PasswordInput } from "@/components/ui/password-input";
import { Label } from "@/components/ui/label";

interface Props {
  token: string;
  inviteEmail: string;
}

export function InvitationAcceptClient({ token, inviteEmail }: Props) {
  const router = useRouter();
  const [stage, setStage] = useState<"accept" | "login" | "accepted">("accept");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function acceptWithPassword() {
    setLoading(true);
    setError("");
    try {
      const res = await fetch(`/api/invitations/${token}/accept`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data?.detail ?? `Error ${res.status}`);
        return;
      }
      setStage("accepted");
      setTimeout(() => router.push("/dashboard"), 1500);
    } finally {
      setLoading(false);
    }
  }

  async function handleAccept() {
    setLoading(true);
    setError("");
    try {
      const res = await fetch(`/api/invitations/${token}/accept`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      const data = await res.json();
      if (!res.ok) {
        if (res.status === 401 || res.status === 403) {
          // Not logged in or wrong account — show login form
          setStage("login");
        } else {
          setError(data?.detail ?? `Error ${res.status}`);
        }
        return;
      }
      setStage("accepted");
      setTimeout(() => router.push("/dashboard"), 1500);
    } finally {
      setLoading(false);
    }
  }

  if (stage === "accepted") {
    return (
      <div className="flex flex-col items-center gap-3 rounded-lg border bg-emerald-50 border-emerald-200 px-6 py-5 text-emerald-700">
        <CheckCircle2 className="h-8 w-8" />
        <p className="font-medium">Invitation accepted!</p>
        <p className="text-sm">Redirecting you to the dashboard…</p>
      </div>
    );
  }

  if (stage === "login") {
    return (
      <div className="space-y-4">
        <div className="rounded-md border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-700">
          Enter the temporary password from your invitation email to continue.
        </div>
        {error && (
          <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}
        <div className="space-y-2">
          <Label htmlFor="invite-email">Email</Label>
          <Input id="invite-email" type="email" value={inviteEmail} disabled className="bg-muted" />
        </div>
        <div className="space-y-2">
          <Label htmlFor="invite-password">Temporary password</Label>
          <PasswordInput
            id="invite-password"
            placeholder="Paste from your email"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && acceptWithPassword()}
            autoFocus
          />
        </div>
        <Button className="w-full" size="lg" onClick={acceptWithPassword} disabled={loading || !password}>
          {loading ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : null}
          Log in &amp; accept invitation
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}
      <Button className="w-full" size="lg" onClick={handleAccept} disabled={loading}>
        {loading ? (
          <>
            <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            Accepting…
          </>
        ) : (
          "Accept invitation"
        )}
      </Button>
      <p className="text-center text-xs text-muted-foreground">
        You must be logged in as <strong>{inviteEmail}</strong> to accept this invitation.
      </p>
    </div>
  );
}
