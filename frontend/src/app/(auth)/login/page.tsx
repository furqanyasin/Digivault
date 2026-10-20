"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PasswordInput } from "@/components/ui/password-input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { useToast } from "@/hooks/use-toast";
import { AuthLogo } from "@/components/auth-logo";

type Step = "credentials" | "totp";

export default function LoginPage() {
  const router = useRouter();
  const { toast } = useToast();
  const [loading, setLoading] = useState(false);
  const [step, setStep] = useState<Step>("credentials");
  const [form, setForm] = useState({ email: "", password: "" });
  const [sessionKey, setSessionKey] = useState("");
  const [code, setCode] = useState("");

  async function handleCredentials(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
      const data = await res.json();
      if (!res.ok) {
        toast({ variant: "destructive", title: "Login failed", description: data?.detail ?? "Invalid email or password" });
        return;
      }
      if (data.requires_password_change) {
        router.push(`/first-password?session_key=${data.session_key}`);
        return;
      }
      if (data.requires_setup) {
        setSessionKey(data.session_key);
        router.push(`/2fa/setup?session_key=${data.session_key}`);
        return;
      }
      if (data.requires_2fa) {
        setSessionKey(data.session_key);
        setStep("totp");
        return;
      }
      // Tokens already set as cookies (trusted device or no 2FA)
      _onAuthenticated();
    } catch {
      toast({ variant: "destructive", title: "Network error", description: "Could not reach the server" });
    } finally {
      setLoading(false);
    }
  }

  async function handleTotp(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    try {
      const res = await fetch("/api/auth/2fa/verify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_key: sessionKey, code }),
      });
      const data = await res.json();
      if (!res.ok) {
        toast({ variant: "destructive", title: "Invalid code", description: data?.detail ?? "Check your authenticator app" });
        setCode("");
        return;
      }
      _onAuthenticated();
    } catch {
      toast({ variant: "destructive", title: "Network error", description: "Could not reach the server" });
    } finally {
      setLoading(false);
    }
  }

  function _onAuthenticated() {
    // The proxy sends a logged-out visitor here with ?next=<path> (an
    // invitation link, say). Only a same-site path is followed: "//host" and
    // "/\host" are read by browsers as another origin.
    const next = new URLSearchParams(window.location.search).get("next") ?? "";
    const safe = next.startsWith("/") && !next.startsWith("//") && !next.startsWith("/\\");
    router.push(safe ? next : "/dashboard");
  }

  if (step === "totp") {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center gap-6 bg-muted/40 px-4 py-10">
        <AuthLogo />
        <Card className="w-full max-w-md">
          <CardHeader className="space-y-1">
            <CardTitle className="text-2xl font-bold">Two-factor authentication</CardTitle>
            <CardDescription>Enter the 6-digit code from your authenticator app</CardDescription>
          </CardHeader>
          <form onSubmit={handleTotp}>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="code">Authenticator code</Label>
                <Input
                  id="code"
                  type="text"
                  inputMode="numeric"
                  pattern="[0-9]*"
                  maxLength={8}
                  placeholder="000000"
                  autoFocus
                  required
                  value={code}
                  onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                  className="text-center text-2xl tracking-widest font-mono"
                />
                <p className="text-xs text-muted-foreground">
                  You can also enter one of your 8-digit backup codes.
                </p>
              </div>
            </CardContent>
            <CardFooter className="flex flex-col gap-3">
              <Button type="submit" className="w-full" disabled={loading}>
                {loading ? "Verifying…" : "Verify"}
              </Button>
              <button
                type="button"
                onClick={() => { setStep("credentials"); setCode(""); setSessionKey(""); }}
                className="text-sm text-muted-foreground hover:text-foreground underline"
              >
                Back to login
              </button>
            </CardFooter>
          </form>
        </Card>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex flex-col items-center justify-center gap-6 bg-muted/40 px-4 py-10">
      <AuthLogo />
      <Card className="w-full max-w-md">
        <CardHeader className="space-y-1">
          <CardTitle className="text-2xl font-bold">Sign in</CardTitle>
          <CardDescription>Enter your email and password to access Stacks Monitor</CardDescription>
        </CardHeader>
        <form onSubmit={handleCredentials}>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                placeholder="you@example.com"
                required
                value={form.email}
                onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <PasswordInput
                id="password"
                autoComplete="current-password"
                required
                value={form.password}
                onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
              />
            </div>
          </CardContent>
          <CardFooter className="flex flex-col gap-3">
            <Button type="submit" className="w-full" disabled={loading}>
              {loading ? "Signing in…" : "Sign in"}
            </Button>
            <p className="text-sm text-muted-foreground text-center">
              <Link href="/forgot-password" className="underline hover:text-foreground">
                Forgot password?
              </Link>
            </p>
            <p className="text-sm text-muted-foreground text-center">
              New to Stacks Monitor?{" "}
              <Link href="/signup" className="font-medium text-primary underline-offset-4 hover:underline">
                Create a free account
              </Link>
            </p>
          </CardFooter>
        </form>
      </Card>
    </div>
  );
}
