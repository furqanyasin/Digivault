"use client";

import { useState } from "react";
import { CheckCircle2, XCircle, Loader2, ShieldCheck, ScanSearch } from "lucide-react";
import { Button } from "@/components/ui/button";

type Stage = "idle" | "verifying" | "scanning" | "done" | "fail";

export function VerifySnippetButton({ websiteId }: { websiteId: string }) {
  const [stage, setStage] = useState<Stage>("idle");
  const [message, setMessage] = useState("");

  async function run() {
    setStage("verifying");
    setMessage("");

    // Step 1: verify snippet is present
    try {
      const res = await fetch(`/api/websites/${websiteId}/verify-snippet`, { method: "POST" });
      const data = await res.json();
      if (!data?.verified) {
        setStage("fail");
        setMessage(data?.error ?? "Snippet not found.");
        return;
      }
    } catch {
      setStage("fail");
      setMessage("Could not complete verification. Try again.");
      return;
    }

    // Step 2: trigger server-side scan
    setStage("scanning");
    try {
      const res = await fetch(`/api/websites/${websiteId}/scan`, { method: "POST" });
      const data = await res.json();
      if (!res.ok) {
        setStage("fail");
        setMessage(data?.detail ?? "Scan failed.");
        return;
      }
      setStage("done");
      setMessage(data?.detail ?? "Scan queued — scripts will appear shortly.");
    } catch {
      setStage("fail");
      setMessage("Scan request failed. Try again.");
    }
  }

  const isLoading = stage === "verifying" || stage === "scanning";

  return (
    <div className="space-y-2">
      <Button
        variant={stage === "done" ? "outline" : "secondary"}
        size="sm"
        onClick={run}
        disabled={isLoading}
        className="gap-2"
      >
        {stage === "verifying" && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
        {stage === "scanning" && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
        {stage === "done" && <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />}
        {stage === "fail" && <XCircle className="h-3.5 w-3.5 text-red-500" />}
        {stage === "idle" && <ShieldCheck className="h-3.5 w-3.5" />}
        {stage === "verifying" && "Verifying…"}
        {stage === "scanning" && "Scanning scripts…"}
        {stage === "done" && "Verified & scanned"}
        {stage === "fail" && "Retry"}
        {stage === "idle" && "Verify & scan"}
      </Button>
      {message && (
        <p className={`text-xs ${stage === "done" ? "text-emerald-600" : stage === "fail" ? "text-red-600" : "text-muted-foreground"}`}>
          {message}
        </p>
      )}
      {stage === "done" && (
        <p className="text-xs text-muted-foreground">
          Check the Scripts tab — data appears within seconds.
        </p>
      )}
    </div>
  );
}
