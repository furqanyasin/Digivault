"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { useToast } from "@/hooks/use-toast";
import type { TeamMember } from "@/lib/api";

interface Summary {
  owned_count: number;
  share_count: number;
  revealed: { credential_id: string; label: string; last_at: string; times: number }[];
}

function nameOf(m: TeamMember) {
  return `${m.user.first_name ?? ""} ${m.user.last_name ?? ""}`.trim() || m.user.email;
}

/**
 * Offboarding for the vault: move a member's credentials to a colleague, drop
 * their shares, and show the passwords they actually revealed — the list to
 * rotate. "Everything they could have seen" is far longer and is not what
 * left the building; the access log knows what did.
 */
export function CredentialHandoverDialog({
  member, members, onClose,
}: {
  member: TeamMember;
  members: TeamMember[];
  onClose: () => void;
}) {
  const { toast } = useToast();
  const [summary, setSummary] = useState<Summary | null>(null);
  const [failed, setFailed] = useState(false);
  const [to, setTo] = useState("");
  const [revoke, setRevoke] = useState(true);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let active = true;
    (async () => {
      const res = await fetch(`/api/credentials/members/${member.user.id}/summary`);
      if (!active) return;
      if (!res.ok) { setFailed(true); return; }
      setSummary(await res.json());
    })();
    return () => { active = false; };
  }, [member.user.id]);

  const recipients = members.filter((m) => m.user.id !== member.user.id);

  async function submit() {
    setBusy(true);
    try {
      const res = await fetch(`/api/credentials/members/${member.user.id}/handover`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ to_user_id: to, revoke_shares: revoke }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        toast({
          variant: "destructive",
          title: "Handover failed",
          description: data?.errors?.[0]?.message ?? data?.detail ?? `Error ${res.status}`,
        });
        return;
      }
      toast({
        title: "Credentials handed over",
        description: `${data.moved} moved${revoke ? `, ${data.shares_revoked} share(s) revoked` : ""}.`,
      });
      onClose();
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Hand over {nameOf(member)}&rsquo;s credentials</DialogTitle>
          <DialogDescription>
            Use this before removing someone: their logins move to a colleague
            instead of being orphaned, and you get the list of passwords to change.
          </DialogDescription>
        </DialogHeader>

        {failed ? (
          <p className="text-sm text-destructive">Could not load their vault summary.</p>
        ) : !summary ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : (
          <div className="space-y-4">
            <p className="text-sm">
              Owns <strong>{summary.owned_count}</strong> credential{summary.owned_count !== 1 ? "s" : ""} and
              holds <strong>{summary.share_count}</strong> share{summary.share_count !== 1 ? "s" : ""}.
            </p>

            <div className="space-y-1.5">
              <Label>Give their credentials to</Label>
              <Select value={to} onValueChange={setTo}>
                <SelectTrigger><SelectValue placeholder="Pick a team member" /></SelectTrigger>
                <SelectContent>
                  {recipients.map((m) => (
                    <SelectItem key={m.user.id} value={m.user.id}>{nameOf(m)}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <label className="flex items-start gap-2 text-sm cursor-pointer">
              <input
                type="checkbox"
                className="mt-0.5 h-4 w-4 accent-primary"
                checked={revoke}
                onChange={(e) => setRevoke(e.target.checked)}
              />
              <span>
                Revoke everything shared with them
                <span className="block text-xs text-muted-foreground">
                  Group and department access ends when you remove them from their group.
                </span>
              </span>
            </label>

            <div className="space-y-1.5">
              <p className="text-sm font-medium">
                Passwords they revealed, copied or autofilled ({summary.revealed.length})
              </p>
              {summary.revealed.length === 0 ? (
                <p className="text-xs text-muted-foreground">None — nothing to rotate.</p>
              ) : (
                <ul className="max-h-48 overflow-y-auto divide-y rounded-md border text-sm">
                  {summary.revealed.map((r) => (
                    <li key={r.credential_id} className="flex justify-between gap-3 px-3 py-1.5">
                      <span className="truncate">{r.label}</span>
                      <span className="text-xs text-muted-foreground shrink-0">
                        {new Date(r.last_at).toLocaleDateString()} · {r.times}×
                      </span>
                    </li>
                  ))}
                </ul>
              )}
              {summary.revealed.length > 0 && (
                <p className="text-xs text-muted-foreground">Change these after they leave.</p>
              )}
            </div>
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button onClick={submit} disabled={!to || busy || !summary}>
            {busy ? "Handing over…" : "Hand over"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
