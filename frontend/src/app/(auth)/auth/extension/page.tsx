"use client";

import { Suspense, useEffect, useRef } from "react";
import { useRouter, useSearchParams } from "next/navigation";

function ExtensionHandoff() {
  const router = useRouter();
  const params = useSearchParams();
  const attempted = useRef(false);

  useEffect(() => {
    if (attempted.current) return;
    attempted.current = true;

    const code = params.get("code");
    if (!code) {
      router.replace("/login?error=missing_code");
      return;
    }

    fetch(`/api/auth/ext-handoff?code=${encodeURIComponent(code)}`)
      .then((res) => {
        if (res.ok) {
          router.replace("/dashboard");
        } else {
          router.replace("/login?error=session_expired");
        }
      })
      .catch(() => {
        router.replace("/login?error=session_expired");
      });
  }, [params, router]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-muted/40">
      <p className="text-muted-foreground text-sm">Signing you in…</p>
    </div>
  );
}

export default function ExtensionHandoffPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen flex items-center justify-center bg-muted/40">
          <p className="text-muted-foreground text-sm">Signing you in…</p>
        </div>
      }
    >
      <ExtensionHandoff />
    </Suspense>
  );
}
