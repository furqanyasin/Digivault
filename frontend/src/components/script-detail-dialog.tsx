"use client";

import { useState } from "react";
import { ExternalLink, Info } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { ScriptReviewButton } from "@/components/script-review-button";
import type { Script } from "@/lib/api";
import { fmtDate } from "@/lib/utils";

interface Props {
  scripts: Script[];
  websiteId: string;
  label: string;
}

function fmt(dt: string | null | undefined) {
  return fmtDate(dt);
}

export function ScriptDetailDialog({ scripts, websiteId, label }: Props) {
  const [open, setOpen] = useState(false);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="ghost" size="sm" className="gap-1 h-7 px-2 text-xs">
          <Info className="h-3.5 w-3.5" />
          Details
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="text-base">{label}</DialogTitle>
        </DialogHeader>

        <div className="space-y-4 pt-2">
          {scripts.map((s) => (
            <div key={s.id} className="rounded-lg border p-4 space-y-3">
              {/* URL */}
              <div className="flex items-start gap-2">
                <code className="text-xs font-mono break-all flex-1 text-muted-foreground">
                  {s.canonical_url ?? s.src_url}
                </code>
                <a
                  href={(s.canonical_url ?? s.src_url).startsWith("//") ? `https:${s.canonical_url ?? s.src_url}` : (s.canonical_url ?? s.src_url)}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="shrink-0 text-muted-foreground hover:text-foreground"
                >
                  <ExternalLink className="h-3.5 w-3.5" />
                </a>
              </div>

              {/* Meta row */}
              <div className="flex flex-wrap gap-2 text-xs">
                <Badge variant="outline" className="capitalize">{s.location}</Badge>
                {s.is_async && <Badge variant="outline">async</Badge>}
                {s.is_defer && <Badge variant="outline">defer</Badge>}
                <span className="text-muted-foreground">First seen: {fmt(s.first_seen_at)}</span>
                <span className="text-muted-foreground">Last seen: {fmt(s.last_seen_at)}</span>
              </div>

              {/* Pages */}
              {s.seen_on_pages?.length > 0 && (
                <div>
                  <p className="text-xs font-medium mb-1">Seen on pages</p>
                  <ul className="space-y-0.5">
                    {s.seen_on_pages.slice(0, 5).map((p) => (
                      <li key={p} className="text-xs font-mono text-muted-foreground truncate">{p}</li>
                    ))}
                    {s.seen_on_pages.length > 5 && (
                      <li className="text-xs text-muted-foreground">+{s.seen_on_pages.length - 5} more</li>
                    )}
                  </ul>
                </div>
              )}

              {/* Review */}
              <div className="flex items-center gap-2 pt-1 border-t">
                <span className="text-xs text-muted-foreground">Review:</span>
                <ScriptReviewButton
                  scriptId={s.id}
                  websiteId={websiteId}
                  currentStatus={s.review_status ?? "pending"}
                />
              </div>
            </div>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}
