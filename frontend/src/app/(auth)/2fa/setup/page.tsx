"use client";

import { useEffect, useState, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { useToast } from "@/hooks/use-toast";
import { Shield, Copy, CheckCircle2 } from "lucide-react";

type SetupStep = "qr" | "confirm" | "backup";

interface SetupData {
  secret: string;
  otp_url: string;
  qr_code: string;
}

function SetupPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { toast } = useToast();
  const sessionKey = searchParams.get("session_key") ?? "";

  const [step, setStep] = useState<SetupStep>("qr");
  const [loading, setLoading] = useState(true);
  const [setup, setSetup] = useState<SetupData | null>(null);
  const [code, setCode] = useState("");
  const [backupCodes, setBackupCodes] = useState<string[]>([]);
  const [copied, setCopied] = useState(false);
  const [confirming, setConfirming] = useState(false);

  useEffect(() => {
    (async () => {
      const url = sessionKey
        ? `/api/auth/2fa/setup?session_key=${sessionKey}`
        : `/api/auth/2fa/setup`;
      const res = await fetch(url, {
        headers: sessionKey ? { "X-Pre-Auth-Key": sessionKey } : {},
      });
      if (!res.ok) {
        toast({ variant: "destructive", title: "Error", description: "Could not load 2FA setup." });
        return;
      }
      const data = await res.json();
      setSetup(data);
      setLoading(false);
    })();
  }, [sessionKey, toast]);

  async function handleConfirm(e: React.FormEvent) {
    e.preventDefault();
    setConfirming(true);
    try {
      const body: Record<string, string> = { code };
      if (sessionKey) body.session_key = sessionKey;

      const res = await fetch("/api/auth/2fa/confirm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) {
        toast({ variant: "destructive", title: "Invalid code", description: data?.detail ?? "Try again." });
        setCode("");
        return;
      }
      setBackupCodes(data.backup_codes ?? []);
      setStep("backup");

      // If tokens were issued (setup flow), the cookies are now set
    } catch {
      toast({ variant: "destructive", title: "Network error" });
    } finally {
      setConfirming(false);
    }
  }

  function handleCopySecret() {
    if (setup?.secret) {
      navigator.clipboard.writeText(setup.secret);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  }

  function handleCopyBackup() {
    navigator.clipboard.writeText(backupCodes.join("\n"));
    toast({ title: "Backup codes copied" });
  }

  function handleDone() {
    router.push("/dashboard");
  }

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <p className="text-muted-foreground">Loading…</p>
      </div>
    );
  }

  if (step === "backup") {
    return (
      <div className="min-h-screen flex items-center justify-center bg-muted/40 px-4">
        <Card className="w-full max-w-md">
          <CardHeader className="space-y-1">
            <div className="flex items-center gap-2 text-green-600">
              <CheckCircle2 className="h-5 w-5" />
              <CardTitle className="text-2xl font-bold">2FA enabled!</CardTitle>
            </div>
            <CardDescription>
              Save these backup codes in a safe place. Each can be used once if you lose access to your authenticator app.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="bg-muted rounded-md p-4 font-mono text-sm grid grid-cols-2 gap-1">
              {backupCodes.map((c) => (
                <span key={c}>{c}</span>
              ))}
            </div>
            <Button variant="outline" className="w-full mt-3" onClick={handleCopyBackup}>
              <Copy className="h-4 w-4 mr-2" />
              Copy all codes
            </Button>
          </CardContent>
          <CardFooter>
            <Button className="w-full" onClick={handleDone}>
              Continue to dashboard
            </Button>
          </CardFooter>
        </Card>
      </div>
    );
  }

  if (step === "confirm") {
    return (
      <div className="min-h-screen flex items-center justify-center bg-muted/40 px-4">
        <Card className="w-full max-w-md">
          <CardHeader className="space-y-1">
            <CardTitle className="text-2xl font-bold">Confirm your code</CardTitle>
            <CardDescription>
              Enter the 6-digit code from your authenticator app to verify setup.
            </CardDescription>
          </CardHeader>
          <form onSubmit={handleConfirm}>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="code">Authenticator code</Label>
                <Input
                  id="code"
                  type="text"
                  inputMode="numeric"
                  pattern="[0-9]{6}"
                  maxLength={6}
                  placeholder="000000"
                  autoFocus
                  required
                  value={code}
                  onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                  className="text-center text-2xl tracking-widest font-mono"
                />
              </div>
            </CardContent>
            <CardFooter className="flex flex-col gap-3">
              <Button type="submit" className="w-full" disabled={confirming}>
                {confirming ? "Verifying…" : "Activate 2FA"}
              </Button>
              <button
                type="button"
                onClick={() => setStep("qr")}
                className="text-sm text-muted-foreground hover:text-foreground underline"
              >
                Back to QR code
              </button>
            </CardFooter>
          </form>
        </Card>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-muted/40 px-4">
      <Card className="w-full max-w-md">
        <CardHeader className="space-y-1">
          <div className="flex items-center gap-2">
            <Shield className="h-5 w-5 text-primary" />
            <CardTitle className="text-2xl font-bold">Set up 2FA</CardTitle>
          </div>
          <CardDescription>
            Scan this QR code with Google Authenticator (or any TOTP app), then click Next.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {setup?.qr_code && (
            <div className="flex justify-center">
              <img src={setup.qr_code} alt="QR code" className="w-48 h-48 border rounded-md" />
            </div>
          )}
          <div className="space-y-1">
            <p className="text-xs text-muted-foreground">Can&apos;t scan? Enter this key manually:</p>
            <div className="flex items-center gap-2">
              <code className="flex-1 text-xs bg-muted px-2 py-1 rounded font-mono break-all">
                {setup?.secret}
              </code>
              <Button variant="ghost" size="sm" onClick={handleCopySecret}>
                {copied ? <CheckCircle2 className="h-4 w-4 text-green-500" /> : <Copy className="h-4 w-4" />}
              </Button>
            </div>
          </div>
        </CardContent>
        <CardFooter>
          <Button className="w-full" onClick={() => setStep("confirm")}>
            Next — enter code
          </Button>
        </CardFooter>
      </Card>
    </div>
  );
}

export default function SetupPage() {
  return (
    <Suspense fallback={<div className="min-h-screen flex items-center justify-center"><p className="text-muted-foreground">Loading…</p></div>}>
      <SetupPageInner />
    </Suspense>
  );
}
