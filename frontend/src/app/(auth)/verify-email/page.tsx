"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { CheckCircle2, Loader2, XCircle } from "lucide-react";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { AuthLogo } from "@/components/auth-logo";

type State = { kind: "working" } | { kind: "done"; signedIn: boolean } | { kind: "error"; message: string };

export default function VerifyEmailPage() {
  const router = useRouter();
  const [state, setState] = useState<State>({ kind: "working" });
  const ran = useRef(false);

  useEffect(() => {
    // The link is single use, so React's dev double-run must not spend it twice.
    if (ran.current) return;
    ran.current = true;
    const token = new URLSearchParams(window.location.search).get("token") ?? "";
    (async () => {
      if (!token) {
        setState({ kind: "error", message: "This link is missing its token. Open the link from your email again." });
        return;
      }
      try {
        const res = await fetch("/api/auth/verify-email", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ token }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          setState({ kind: "error", message: data?.detail ?? "This link is not valid." });
          return;
        }
        setState({ kind: "done", signedIn: Boolean(data?.signed_in) });
        if (data?.signed_in) setTimeout(() => router.push("/dashboard"), 1200);
      } catch {
        setState({ kind: "error", message: "Could not reach the server. Please try again." });
      }
    })();
  }, [router]);

  return (
    <div className="min-h-screen flex flex-col items-center justify-center gap-6 bg-muted/40 px-4 py-10">
      <AuthLogo />
      <Card className="w-full max-w-md text-center">
        <CardHeader className="space-y-3">
          {state.kind === "working" && (
            <>
              <Loader2 className="mx-auto h-10 w-10 animate-spin text-primary" aria-hidden />
              <CardTitle className="text-2xl font-bold">Confirming your email</CardTitle>
            </>
          )}
          {state.kind === "done" && (
            <>
              <CheckCircle2 className="mx-auto h-12 w-12 text-emerald-600" aria-hidden />
              <CardTitle className="text-2xl font-bold">Email confirmed</CardTitle>
              <CardDescription>
                {state.signedIn ? (
                  "Your workspace is ready. Taking you to the dashboard…"
                ) : (
                  <>Your account is ready. <Link href="/login" className="font-medium text-primary underline">Log in</Link> to continue.</>
                )}
              </CardDescription>
            </>
          )}
          {state.kind === "error" && (
            <>
              <XCircle className="mx-auto h-12 w-12 text-destructive" aria-hidden />
              <CardTitle className="text-2xl font-bold">We could not confirm this link</CardTitle>
              <CardDescription>{state.message}</CardDescription>
              <div className="flex justify-center gap-4 pt-2 text-sm">
                <Link href="/login" className="font-medium text-primary underline">Log in</Link>
                <Link href="/signup" className="font-medium text-primary underline">Sign up again</Link>
              </div>
            </>
          )}
        </CardHeader>
      </Card>
    </div>
  );
}
