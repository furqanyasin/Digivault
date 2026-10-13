"use client";

import { useState } from "react";
import { Wand2, History, Eye, Copy, RotateCcw, ChevronDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useToast } from "@/hooks/use-toast";
import { copySecret } from "@/lib/clipboard";

// ─── Generator ────────────────────────────────────────────────────────────────

// No look-alikes (0/O, 1/l/I) — these get read aloud and typed into client
// panels by hand more often than anyone admits.
const LOWER = "abcdefghijkmnopqrstuvwxyz";
const UPPER = "ABCDEFGHJKLMNPQRSTUVWXYZ";
const DIGITS = "23456789";
const SYMBOLS = "!@#$%^&*-_=+?";

/** Uniform integer in [0, n) from the CSPRNG, rejecting the biased tail. */
function randomIndex(n: number): number {
  const limit = Math.floor(0x100000000 / n) * n;
  const buf = new Uint32Array(1);
  do { crypto.getRandomValues(buf); } while (buf[0] >= limit);
  return buf[0] % n;
}

/** A strong password with at least one of each character class. */
export function generatePassword(length = 20): string {
  const sets = [LOWER, UPPER, DIGITS, SYMBOLS];
  const pool = sets.join("");
  const chars = sets.map((s) => s[randomIndex(s.length)]);
  while (chars.length < length) chars.push(pool[randomIndex(pool.length)]);
  for (let i = chars.length - 1; i > 0; i--) {
    const j = randomIndex(i + 1);
    [chars[i], chars[j]] = [chars[j], chars[i]];
  }
  return chars.join("");
}

/** One click, one strong password into the field beside it. Deliberately no
 *  options panel: for an internal tool the default is what everyone wants, and
 *  a site that refuses symbols is rare enough to type by hand. */
export function GenerateButton({ onGenerate }: { onGenerate: (password: string) => void }) {
  return (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      className="h-7 px-2 text-xs"
      title="Generate a strong 20-character password"
      onClick={() => onGenerate(generatePassword())}
    >
      <Wand2 className="h-3.5 w-3.5 mr-1" />Generate
    </Button>
  );
}

// ─── History ──────────────────────────────────────────────────────────────────

interface HistoryEntry {
  id: string;
  set_at: string | null;
  replaced_at: string;
  changed_by_email: string | null;
}

function errorMessage(data: unknown, fallback: string): string {
  const d = data as { errors?: { message?: string }[]; detail?: string } | null;
  return d?.errors?.[0]?.message ?? d?.detail ?? fallback;
}

/**
 * Previous passwords of one credential, loaded on first open. Reveal is a
 * logged read held to the same rule as the live password; restore is an edit
 * and puts the current password into the history, so it can be undone.
 */
export function PasswordHistorySection({
  credId, canWrite, onRestored,
}: {
  credId: string;
  canWrite: boolean;
  onRestored: () => void;
}) {
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [entries, setEntries] = useState<HistoryEntry[] | null>(null);
  const [shown, setShown] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);

  async function load() {
    const res = await fetch(`/api/credentials/${credId}/password-history`);
    const data = await res.json().catch(() => []);
    setEntries(Array.isArray(data) ? data : []);
  }

  async function toggle() {
    const next = !open;
    setOpen(next);
    if (next && entries === null) await load();
  }

  async function reveal(entry: HistoryEntry) {
    setBusy(entry.id);
    try {
      const res = await fetch(`/api/credentials/${credId}/password-history/${entry.id}/reveal`, { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        toast({ variant: "destructive", title: "Cannot reveal", description: errorMessage(data, `Error ${res.status}`) });
        return;
      }
      setShown((s) => ({ ...s, [entry.id]: data.password ?? "" }));
    } finally {
      setBusy(null);
    }
  }

  async function restore(entry: HistoryEntry) {
    if (!confirm("Put this old password back? The current one will be kept in the history.")) return;
    setBusy(entry.id);
    try {
      const res = await fetch(`/api/credentials/${credId}/password-history/${entry.id}/restore`, { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        toast({ variant: "destructive", title: "Restore failed", description: errorMessage(data, `Error ${res.status}`) });
        return;
      }
      toast({ title: "Old password restored" });
      setShown({});
      await load();
      onRestored();
    } finally {
      setBusy(null);
    }
  }

  return (
    <div>
      <button
        type="button"
        onClick={toggle}
        className="flex items-center gap-1.5 text-xs text-muted-foreground uppercase tracking-wide hover:text-foreground"
        aria-expanded={open}
      >
        <History className="h-3.5 w-3.5" />
        Password history
        <ChevronDown className={`h-3.5 w-3.5 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <div className="mt-1.5">
          {entries === null ? (
            <p className="text-xs text-muted-foreground">Loading…</p>
          ) : entries.length === 0 ? (
            <p className="text-xs text-muted-foreground">No earlier passwords recorded.</p>
          ) : (
            <ul className="space-y-1">
              {entries.map((e) => (
                <li key={e.id} className="flex items-center gap-2 rounded-md border px-2.5 py-1.5">
                  <div className="min-w-0 flex-1">
                    {shown[e.id] !== undefined ? (
                      <p className="text-sm font-mono truncate">{shown[e.id] || "—"}</p>
                    ) : (
                      <p className="text-sm tracking-widest text-muted-foreground">••••••••</p>
                    )}
                    <p className="text-[11px] text-muted-foreground truncate">
                      Replaced {new Date(e.replaced_at).toLocaleString()}
                      {e.changed_by_email ? ` by ${e.changed_by_email}` : ""}
                    </p>
                  </div>
                  {shown[e.id] === undefined ? (
                    <Button size="sm" variant="ghost" className="h-7 w-7 p-0" title="Reveal" disabled={busy === e.id} onClick={() => reveal(e)}>
                      <Eye className="h-3.5 w-3.5" />
                    </Button>
                  ) : (
                    <Button
                      size="sm" variant="ghost" className="h-7 w-7 p-0" title="Copy"
                      onClick={() => { void copySecret(shown[e.id]); toast({ title: "Old password copied" }); }}
                    >
                      <Copy className="h-3.5 w-3.5" />
                    </Button>
                  )}
                  {canWrite && (
                    <Button size="sm" variant="ghost" className="h-7 w-7 p-0" title="Restore this password" disabled={busy === e.id} onClick={() => restore(e)}>
                      <RotateCcw className="h-3.5 w-3.5" />
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
