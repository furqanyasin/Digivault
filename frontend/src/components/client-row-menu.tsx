"use client";

import { useState } from "react";
import Link from "next/link";
import { MoreHorizontal } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ClientDeleteDialog } from "@/components/client-delete-dialog";
import { useToast } from "@/hooks/use-toast";

interface Props {
  id: string;
  name: string;
  status: "active" | "paused" | "offboarded";
  /** Refetch the list. "deleted" also steps back a page if this row was the
   *  last one on it. */
  onChanged: (what: "deleted" | "status") => void | Promise<void>;
}

/**
 * Row actions for one client.
 *
 * Delete is only offered on an offboarded client, and the backend enforces the
 * same rule. Offboarding is the reversible step and stays the normal way to
 * retire a client; deleting is for rows that should never have existed — the
 * same client filed twice under different capitalisation, which the CSV import
 * cannot tell apart because it matches the name exactly.
 */
export function ClientRowMenu({ id, name, status, onChanged }: Props) {
  const { toast } = useToast();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  async function setStatus(action: "activate" | "deactivate") {
    setBusy(true);
    try {
      const res = await fetch(`/api/clients/${id}/${action}`, { method: "POST" });
      if (!res.ok) {
        const data = await res.json().catch(() => null);
        const d = data as { detail?: string; errors?: { message?: string }[] } | null;
        toast({
          variant: "destructive",
          title: action === "activate" ? "Could not activate client" : "Could not offboard client",
          description: d?.detail || d?.errors?.[0]?.message || "Please try again.",
        });
        return;
      }
      toast({
        title: action === "activate" ? "Client activated" : "Client offboarded",
        description: name,
      });
      await onChanged("status");
    } catch {
      toast({ variant: "destructive", title: "Network error" });
    } finally {
      setBusy(false);
    }
  }

  const offboarded = status === "offboarded";

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="sm" className="h-8 w-8 p-0" disabled={busy}>
            <MoreHorizontal className="h-4 w-4" />
            <span className="sr-only">Actions for {name}</span>
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem asChild>
            <Link href={`/clients/${id}`}>Edit client</Link>
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          {offboarded ? (
            <DropdownMenuItem onSelect={() => setStatus("activate")}>
              Reactivate client
            </DropdownMenuItem>
          ) : (
            <DropdownMenuItem onSelect={() => setStatus("deactivate")}>
              Offboard client
            </DropdownMenuItem>
          )}
          {/* Only an offboarded client can be deleted. Rather than show a
              control that always fails, name the step that unlocks it. */}
          {offboarded ? (
            <DropdownMenuItem
              className="text-destructive focus:text-destructive"
              onSelect={(e) => {
                e.preventDefault();
                setConfirmOpen(true);
              }}
            >
              Delete client
            </DropdownMenuItem>
          ) : (
            <DropdownMenuItem disabled className="text-muted-foreground">
              Delete — offboard first
            </DropdownMenuItem>
          )}
        </DropdownMenuContent>
      </DropdownMenu>

      <ClientDeleteDialog
        id={id}
        name={name}
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        onDeleted={() => onChanged("deleted")}
      />
    </>
  );
}
