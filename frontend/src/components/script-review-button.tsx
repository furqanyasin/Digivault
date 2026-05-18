"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { CheckCircle, Ban, EyeOff, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";

type ReviewStatus = "pending" | "approved" | "blocked" | "ignored";

interface Props {
  scriptId: string;
  websiteId: string;
  currentStatus: ReviewStatus;
}

export function ScriptReviewButton({ scriptId, websiteId, currentStatus }: Props) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [optimistic, setOptimistic] = useState<ReviewStatus>(currentStatus);

  async function setStatus(next: ReviewStatus) {
    if (next === optimistic) return;
    setOptimistic(next);
    const res = await fetch(`/api/websites/${websiteId}/scripts/${scriptId}/review`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ review_status: next }),
    });
    if (!res.ok) {
      setOptimistic(currentStatus);
      return;
    }
    startTransition(() => router.refresh());
  }

  if (pending) {
    return <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />;
  }

  if (optimistic === "approved") {
    return (
      <div className="flex items-center gap-1">
        <span className="inline-flex items-center gap-1 text-xs text-emerald-600 font-medium">
          <CheckCircle className="h-3.5 w-3.5" /> Approved
        </span>
        <Button
          size="sm"
          variant="ghost"
          className="h-6 px-2 text-xs text-muted-foreground"
          onClick={() => setStatus("pending")}
        >
          Undo
        </Button>
      </div>
    );
  }

  if (optimistic === "blocked") {
    return (
      <div className="flex items-center gap-1">
        <span className="inline-flex items-center gap-1 text-xs text-red-600 font-medium">
          <Ban className="h-3.5 w-3.5" /> Blocked
        </span>
        <Button
          size="sm"
          variant="ghost"
          className="h-6 px-2 text-xs text-muted-foreground"
          onClick={() => setStatus("pending")}
        >
          Undo
        </Button>
      </div>
    );
  }

  if (optimistic === "ignored") {
    return (
      <div className="flex items-center gap-1">
        <span className="inline-flex items-center gap-1 text-xs text-muted-foreground font-medium">
          <EyeOff className="h-3.5 w-3.5" /> Ignored
        </span>
        <Button
          size="sm"
          variant="ghost"
          className="h-6 px-2 text-xs text-muted-foreground"
          onClick={() => setStatus("pending")}
        >
          Undo
        </Button>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-1">
      <Button
        size="sm"
        variant="ghost"
        className="h-7 px-2 text-xs text-emerald-600 hover:text-emerald-700 hover:bg-emerald-50"
        onClick={() => setStatus("approved")}
      >
        <CheckCircle className="h-3.5 w-3.5 mr-1" />
        Approve
      </Button>
      <Button
        size="sm"
        variant="ghost"
        className="h-7 px-2 text-xs text-red-600 hover:text-red-700 hover:bg-red-50"
        onClick={() => setStatus("blocked")}
      >
        <Ban className="h-3.5 w-3.5 mr-1" />
        Block
      </Button>
      <Button
        size="sm"
        variant="ghost"
        className="h-7 px-2 text-xs text-muted-foreground hover:bg-muted"
        onClick={() => setStatus("ignored")}
      >
        <EyeOff className="h-3.5 w-3.5 mr-1" />
        Ignore
      </Button>
    </div>
  );
}
