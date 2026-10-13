"use client";

import { useState } from "react";
import { AlertTriangle, ChevronDown, Users, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useToast } from "@/hooks/use-toast";
import type { Credential } from "@/lib/api";
import { roleLabel } from "@/lib/roles";

function errorMessage(data: unknown, fallback: string): string {
  const d = data as { errors?: { message?: string }[]; detail?: string } | null;
  return d?.errors?.[0]?.message ?? d?.detail ?? fallback;
}

function when(iso: string) {
  return new Date(iso).toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

// ─── Broken login ─────────────────────────────────────────────────────────────

/**
 * "This login does not work". Anyone who can see the credential can report it,
 * so the next person reads the warning instead of retrying a dead password
 * into a lockout; whoever can edit it marks it fixed (a password change clears
 * it on its own).
 */
export function BrokenLoginControl({
  cred, canWrite, onChanged,
}: {
  cred: Credential;
  canWrite: boolean;
  onChanged: (updated: Credential) => void;
}) {
  const { toast } = useToast();
  const [reporting, setReporting] = useState(false);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  async function post(path: "report-broken" | "mark-fixed", body?: object) {
    setBusy(true);
    try {
      const res = await fetch(`/api/credentials/${cred.id}/${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body ?? {}),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        toast({ variant: "destructive", title: "Could not update", description: errorMessage(data, `Error ${res.status}`) });
        return;
      }
      toast({ title: path === "report-broken" ? "Reported — the team has been told" : "Marked as working" });
      setReporting(false);
      setNote("");
      onChanged(data as Credential);
    } finally {
      setBusy(false);
    }
  }

  if (cred.broken === undefined) return null; // backend predates the feature

  if (cred.broken) {
    return (
      <div className="rounded-lg border border-amber-300 bg-amber-50 dark:border-amber-800 dark:bg-amber-950/40 p-3 flex gap-2.5">
        <AlertTriangle className="h-4 w-4 text-amber-600 shrink-0 mt-0.5" />
        <div className="min-w-0 flex-1 text-sm">
          <p className="font-medium">Reported as not working</p>
          <p className="text-xs text-muted-foreground mt-0.5">
            {cred.broken.by_email ?? "Someone"} · {when(cred.broken.at)}
            {cred.broken.note ? ` — “${cred.broken.note}”` : ""}
          </p>
        </div>
        {canWrite && (
          <Button size="sm" variant="outline" className="h-7 shrink-0" disabled={busy} onClick={() => post("mark-fixed")}>
            <Check className="h-3.5 w-3.5 mr-1" />Fixed
          </Button>
        )}
      </div>
    );
  }

  return reporting ? (
    <div className="flex items-center gap-2">
      <Input
        autoFocus
        value={note}
        onChange={(e) => setNote(e.target.value)}
        maxLength={300}
        placeholder="What happened? e.g. wrong password, account locked"
        className="h-8 text-sm"
      />
      <Button size="sm" className="h-8" disabled={busy} onClick={() => post("report-broken", { note })}>Report</Button>
      <Button size="sm" variant="ghost" className="h-8" onClick={() => setReporting(false)}>Cancel</Button>
    </div>
  ) : (
    <button
      type="button"
      onClick={() => setReporting(true)}
      className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-amber-700"
    >
      <AlertTriangle className="h-3.5 w-3.5" />This login doesn&rsquo;t work
    </button>
  );
}

// ─── Who has access ───────────────────────────────────────────────────────────

interface AccessRoute {
  kind: "role" | "creator" | "share" | "group" | "folder" | "department";
  label: string;
  can_view_password: boolean;
  expires_at?: string | null;
}
interface AccessRow {
  user_id: string;
  name: string;
  email: string;
  role: string;
  can_reveal: boolean;
  can_view_password: boolean;
  routes: AccessRoute[];
  last_used_at: string | null;
}

function Collapsible({
  icon: Icon, title, onOpen, children,
}: {
  icon: typeof Users;
  title: string;
  onOpen: () => void;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button
        type="button"
        onClick={() => { if (!open) onOpen(); setOpen(!open); }}
        className="flex items-center gap-1.5 text-xs text-muted-foreground uppercase tracking-wide hover:text-foreground"
        aria-expanded={open}
      >
        <Icon className="h-3.5 w-3.5" />
        {title}
        <ChevronDown className={`h-3.5 w-3.5 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && <div className="mt-1.5">{children}</div>}
    </div>
  );
}

/** Everyone who can see this credential and every route that lets them —
 *  what to check when someone leaves or a client asks who has their login. */
export function WhoHasAccessSection({ credId }: { credId: string }) {
  const [rows, setRows] = useState<AccessRow[] | null>(null);
  const [failed, setFailed] = useState(false);

  async function load() {
    const res = await fetch(`/api/credentials/${credId}/access`);
    if (!res.ok) { setFailed(true); return; }
    const data = await res.json().catch(() => []);
    setRows(Array.isArray(data) ? data : []);
  }

  return (
    <Collapsible icon={Users} title="Who has access" onOpen={() => { if (rows === null) void load(); }}>
      {failed ? (
        <p className="text-xs text-muted-foreground">Could not load access.</p>
      ) : rows === null ? (
        <p className="text-xs text-muted-foreground">Loading…</p>
      ) : (
        <ul className="space-y-1 max-h-64 overflow-y-auto pr-1">
          {rows.map((r) => (
            <li key={r.user_id} className="rounded-md border px-2.5 py-1.5">
              <div className="flex items-center gap-2">
                <p className="text-sm truncate flex-1">{r.name}</p>
                <span className="text-[11px] text-muted-foreground shrink-0">{roleLabel(r.role)}</span>
              </div>
              <div className="flex flex-wrap gap-1 mt-1">
                {r.routes.map((route, i) => (
                  <span
                    key={i}
                    className="text-[10px] px-1.5 py-0.5 rounded-full border bg-muted/50"
                    title={route.expires_at ? `Until ${when(route.expires_at)}` : undefined}
                  >
                    {route.label}{route.expires_at ? ` · until ${when(route.expires_at)}` : ""}
                  </span>
                ))}
                <span className={`text-[10px] px-1.5 py-0.5 rounded-full border ${
                  !r.can_reveal
                    ? "bg-slate-50 text-slate-500"
                    : r.can_view_password
                      ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                      : "bg-amber-50 text-amber-700 border-amber-200"
                }`}>
                  {!r.can_reveal ? "cannot reveal" : r.can_view_password ? "sees password" : "autofill only"}
                </span>
              </div>
              <p className="text-[11px] text-muted-foreground mt-0.5">
                {r.last_used_at ? `Last used ${when(r.last_used_at)}` : "Never used"}
              </p>
            </li>
          ))}
        </ul>
      )}
    </Collapsible>
  );
}
