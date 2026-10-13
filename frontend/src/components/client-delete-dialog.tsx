"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useToast } from "@/hooks/use-toast";

interface Props {
  id: string;
  name: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Runs after a successful delete — refetch a list, or leave the page. */
  onDeleted: () => void | Promise<void>;
}

/** Read the reason out of whichever shape the answer came in: the API envelope's
 *  first error, a bare { detail }, or nothing at all. */
function reason(data: unknown, fallback: string): string {
  const d = data as { detail?: string; errors?: { message?: string }[] } | null;
  return d?.detail || d?.errors?.[0]?.message || fallback;
}

/**
 * Confirm and delete one client.
 *
 * Shared by the clients table and the client detail page so both describe the
 * same consequences — in particular that the monitored website survives. A
 * client is normally retired by offboarding, which is reversible; this is the
 * one-way door, and the backend refuses it unless the client is already
 * offboarded.
 */
export function ClientDeleteDialog({ id, name, open, onOpenChange, onDeleted }: Props) {
  const { toast } = useToast();
  const [busy, setBusy] = useState(false);

  async function handleDelete() {
    setBusy(true);
    try {
      const res = await fetch(`/api/clients/${id}/`, { method: "DELETE" });
      if (!res.ok) {
        const data = await res.json().catch(() => null);
        toast({
          variant: "destructive",
          title: "Could not delete client",
          description: reason(data, "Please try again."),
        });
        return;
      }
      toast({ title: "Client deleted", description: name });
      onOpenChange(false);
      await onDeleted();
    } catch {
      toast({ variant: "destructive", title: "Network error" });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Delete client</DialogTitle>
          <DialogDescription>
            Permanently delete <strong>{name}</strong> and everything recorded on the
            client record — hosting, access, renewal dates and notes. This cannot be
            undone. Any monitored website stays, with its scripts and history intact;
            it simply stops being linked to a client.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>
            Cancel
          </Button>
          <Button variant="destructive" onClick={handleDelete} disabled={busy}>
            {busy ? "Deleting…" : "Delete client"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
