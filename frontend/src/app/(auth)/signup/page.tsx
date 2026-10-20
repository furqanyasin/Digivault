"use client";

import { useState } from "react";
import Link from "next/link";
import { MailCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PasswordInput } from "@/components/ui/password-input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { AuthLogo } from "@/components/auth-logo";

// Sent straight to Django (nginx routes /api/v1/ there), so the signup rate
// limit counts the visitor's IP, not the Next.js server's.
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default function SignupPage() {
  const [form, setForm] = useState({ name: "", email: "", password: "", workspace_name: "", company_website: "" });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [sentTo, setSentTo] = useState("");

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (form.password.length < 8) {
      setError("Use at least 8 characters for your password.");
      return;
    }
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/v1/auth/signup/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(
          res.status === 429
            ? "Too many signups from this network. Please try again in an hour."
            : body?.data?.detail ?? body?.errors?.[0]?.message ?? "Could not create your account.",
        );
        return;
      }
      setSentTo(form.email.trim());
    } catch {
      setError("Could not reach the server. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  if (sentTo) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center gap-6 bg-muted/40 px-4 py-10">
        <AuthLogo />
        <Card className="w-full max-w-md text-center">
          <CardHeader className="space-y-3">
            <MailCheck className="mx-auto h-12 w-12 text-primary" aria-hidden />
            <CardTitle className="text-2xl font-bold">Check your inbox</CardTitle>
            <CardDescription>
              We sent a confirmation link to <strong className="text-foreground">{sentTo}</strong>. Click it to finish
              creating your account. The link works for 48 hours.
            </CardDescription>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            No email after a few minutes? Check spam, or{" "}
            <button type="button" className="font-medium text-primary underline-offset-4 hover:underline" onClick={() => setSentTo("")}>
              try again
            </button>
            .
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex flex-col items-center justify-center gap-6 bg-muted/40 px-4 py-10">
      <AuthLogo />
      <Card className="w-full max-w-md">
        <CardHeader className="space-y-1">
          <CardTitle className="text-2xl font-bold">Create your free account</CardTitle>
          <CardDescription>Monitor your first website free. No card needed.</CardDescription>
        </CardHeader>
        <form onSubmit={submit}>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="name">Your name</Label>
              <Input id="name" autoComplete="name" required value={form.name} onChange={set("name")} placeholder="Ayesha Khan" />
            </div>
            <div className="space-y-2">
              <Label htmlFor="email">Work email</Label>
              <Input id="email" type="email" autoComplete="email" required value={form.email} onChange={set("email")} placeholder="you@agency.com" />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <PasswordInput id="password" autoComplete="new-password" required minLength={8} value={form.password} onChange={set("password")} />
              <p className="text-xs text-muted-foreground">At least 8 characters. Avoid common passwords.</p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="workspace">Agency or workspace name <span className="text-muted-foreground">(optional)</span></Label>
              <Input id="workspace" autoComplete="organization" value={form.workspace_name} onChange={set("workspace_name")} placeholder="Khan Studio" />
            </div>
            {/* Honeypot: hidden from people, filled in by bots. */}
            <div aria-hidden className="absolute -left-[9999px] h-0 w-0 overflow-hidden">
              <label htmlFor="company_website">Company website</label>
              <input id="company_website" tabIndex={-1} autoComplete="off" value={form.company_website} onChange={set("company_website")} />
            </div>
            {error && (
              <p role="alert" className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
                {error}
              </p>
            )}
          </CardContent>
          <CardFooter className="flex flex-col gap-3">
            <Button type="submit" className="w-full" disabled={loading}>
              {loading ? "Creating account…" : "Create account"}
            </Button>
            <p className="text-xs text-muted-foreground text-center">
              By creating an account you agree to our{" "}
              <Link href="/terms" className="underline hover:text-foreground">Terms</Link> and{" "}
              <Link href="/privacy" className="underline hover:text-foreground">Privacy policy</Link>.
            </p>
            <p className="text-sm text-muted-foreground text-center">
              Already have an account?{" "}
              <Link href="/login" className="font-medium text-primary underline-offset-4 hover:underline">Log in</Link>
            </p>
          </CardFooter>
        </form>
      </Card>
    </div>
  );
}
