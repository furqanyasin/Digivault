"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useToast } from "@/hooks/use-toast";
import { CheckCircle2, Loader2, Shield, ShieldOff, UserCircle } from "lucide-react";

interface Props {
  name: string;
  email: string;
  role: string;
  teamName: string;
}

export function AccountClient({ name, email, role, teamName }: Props) {
  const router = useRouter();
  const { toast } = useToast();

  const [totpEnabled, setTotpEnabled] = useState<boolean | null>(null);
  const [backupCount, setBackupCount] = useState(0);
  const [disabling2fa, setDisabling2fa] = useState(false);
  const [regenLoading, setRegenLoading] = useState(false);
  const [newBackupCodes, setNewBackupCodes] = useState<string[]>([]);

  useEffect(() => {
    fetch("/api/auth/2fa/status")
      .then((r) => r.json())
      .then((d) => {
        const payload = d?.data ?? d;
        setTotpEnabled(payload?.totp_enabled ?? false);
        setBackupCount(payload?.backup_codes_count ?? 0);
      })
      .catch(() => {});
  }, []);

  async function handleDisable2fa() {
    setDisabling2fa(true);
    try {
      const res = await fetch("/api/auth/2fa/disable", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      const data = await res.json();
      if (!res.ok) {
        toast({ variant: "destructive", title: "Error", description: data?.detail || "Failed to disable 2FA." });
        return;
      }
      setTotpEnabled(false);
      toast({ title: "2FA disabled", description: "Two-factor authentication has been disabled." });
    } catch {
      toast({ variant: "destructive", title: "Network error" });
    } finally {
      setDisabling2fa(false);
    }
  }

  async function handleRegenBackup() {
    setRegenLoading(true);
    try {
      const res = await fetch("/api/auth/2fa/regenerate-backup", { method: "POST" });
      const data = await res.json();
      const payload = data?.data ?? data;
      if (!res.ok) {
        toast({ variant: "destructive", title: "Error", description: payload?.detail || "Failed." });
        return;
      }
      setNewBackupCodes(payload.backup_codes ?? []);
      setBackupCount((payload.backup_codes ?? []).length);
      toast({ title: "New backup codes generated", description: "Save them in a safe place." });
    } catch {
      toast({ variant: "destructive", title: "Network error" });
    } finally {
      setRegenLoading(false);
    }
  }

  return (
    <div className="p-8 max-w-2xl space-y-8">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">My Account</h1>
        <p className="text-muted-foreground mt-1">Your profile and account security.</p>
      </div>

      {/* Profile */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <UserCircle className="h-5 w-5" />
            Profile
          </CardTitle>
          <CardDescription className="mt-1">Your account details.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <Row label="Name" value={name || "—"} />
          <Row label="Email" value={email} mono />
          <Row label="Role" value={role} />
          <Row label="Active team" value={teamName} />
        </CardContent>
      </Card>

      {/* 2FA */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="flex items-center gap-2">
                <Shield className="h-5 w-5" />
                Two-Factor Authentication
              </CardTitle>
              <CardDescription className="mt-1">
                Protect your account with Google Authenticator or any TOTP app.
              </CardDescription>
            </div>
            {totpEnabled === true && (
              <Badge className="bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200 gap-1">
                <CheckCircle2 className="h-3 w-3" /> Enabled
              </Badge>
            )}
            {totpEnabled === false && (
              <Badge variant="secondary" className="gap-1">
                <ShieldOff className="h-3 w-3" /> Not set up
              </Badge>
            )}
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {totpEnabled === false && (
            <div className="space-y-3">
              <p className="text-sm text-muted-foreground">
                2FA is mandatory. Set it up now to secure your account.
              </p>
              <Button onClick={() => router.push("/2fa/setup")}>Set up 2FA</Button>
            </div>
          )}
          {totpEnabled === true && (
            <div className="space-y-4">
              <p className="text-sm text-muted-foreground">
                You have <strong>{backupCount}</strong> backup code{backupCount !== 1 ? "s" : ""} remaining.
              </p>

              {newBackupCodes.length > 0 && (
                <div className="bg-muted rounded-md p-4 font-mono text-sm grid grid-cols-2 gap-1">
                  {newBackupCodes.map((c) => (
                    <span key={c}>{c}</span>
                  ))}
                </div>
              )}

              <div className="flex gap-3 flex-wrap">
                <Button variant="outline" onClick={handleRegenBackup} disabled={regenLoading}>
                  {regenLoading ? <><Loader2 className="h-4 w-4 mr-2 animate-spin" />Generating…</> : "Regenerate backup codes"}
                </Button>
                <Button
                  variant="ghost"
                  className="text-destructive hover:text-destructive"
                  onClick={handleDisable2fa}
                  disabled={disabling2fa}
                >
                  {disabling2fa ? "Disabling…" : "Disable 2FA"}
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function Row({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-center justify-between border-b pb-2 last:border-0 last:pb-0">
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className={`font-medium text-sm capitalize ${mono ? "font-mono normal-case" : ""}`}>{value}</span>
    </div>
  );
}
