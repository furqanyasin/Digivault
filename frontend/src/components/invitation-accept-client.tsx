"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { CheckCircle2, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";

interface Props {
  token: string;
  inviteEmail: string;
}

export function InvitationAcceptClient({ token, inviteEmail }: Props) {
  const router = useRouter();
  const [accepted, setAccepted] = useState(false);
  const [needsLogin, setNeedsLogin] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

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
        // Accepting needs a full login (with 2FA), never a password typed here.
        if (res.status === 401) setNeedsLogin(true);
        setError(data?.detail ?? `Error ${res.status}`);
        return;
      }
      setAccepted(true);
      setTimeout(() => router.push("/dashboard"), 1500);
    } finally {
      setLoading(false);
    }
  }

  if (accepted) {
    return (
      <div className="flex flex-col items-center gap-3 rounded-lg border bg-emerald-50 border-emerald-200 px-6 py-5 text-emerald-700">
        <CheckCircle2 className="h-8 w-8" />
        <p className="font-medium">Invitation accepted!</p>
        <p className="text-sm">Redirecting you to the dashboard…</p>
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
      {needsLogin ? (
        <Button asChild className="w-full" size="lg">
          <Link href={`/login?next=${encodeURIComponent(`/invite/${token}`)}`}>Log in to accept</Link>
        </Button>
      ) : (
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
      )}
      <p className="text-center text-xs text-muted-foreground">
        You must be logged in as <strong>{inviteEmail}</strong> to accept this invitation.
      </p>
    </div>
  );
}
