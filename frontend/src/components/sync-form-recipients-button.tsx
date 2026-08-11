"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, MailSearch } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useToast } from "@/hooks/use-toast";

/** Ask a WordPress site where its forms deliver, on demand.
 *
 *  A form plugin keeps its "To" address in the database, so the tracking snippet
 *  never sees it and the Goes to column reads "Server-side". WP Connect can read
 *  it, but only nightly — which is a long time to wait to find out whether the
 *  snippet you just pasted works. This runs the same read now.
 */
export function SyncFormRecipientsButton({ websiteId }: { websiteId: string }) {
  const [busy, setBusy] = useState(false);
  const { toast } = useToast();
  const router = useRouter();

  async function sync() {
    setBusy(true);
    try {
      const res = await fetch(`/api/websites/${websiteId}/sync-form-recipients`, {
        method: "POST",
      });
      const data = await res.json().catch(() => ({}));

      if (!res.ok) {
        toast({
          variant: "destructive",
          title: "Could not read the form settings",
          description:
            data?.detail ??
            "The site did not answer. Check WP Connect is set up in the Setup tab.",
        });
        return;
      }

      const updated = Number(data?.updated ?? 0);
      if (updated > 0) {
        toast({
          title: `Filled in ${updated} recipient${updated !== 1 ? "s" : ""}`,
          description: "Read from this site's form plugins.",
        });
        router.refresh();
      } else {
        toast({
          title: "No recipients to fill in",
          description:
            "WordPress reported nothing that matches a detected form. Re-paste the WP Connect snippet if you set it up before this feature shipped.",
        });
      }
    } catch {
      toast({
        variant: "destructive",
        title: "Could not read the form settings",
        description: "The request failed. Try again in a moment.",
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Button variant="outline" size="sm" className="gap-1.5" onClick={sync} disabled={busy}>
      {busy ? (
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
      ) : (
        <MailSearch className="h-3.5 w-3.5" />
      )}
      Read recipients from WordPress
    </Button>
  );
}
