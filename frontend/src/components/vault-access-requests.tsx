"use client";

import { useCallback, useEffect, useState } from "react";
import { KeyRound, Check, X, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { useToast } from "@/hooks/use-toast";

// ─── Types ────────────────────────────────────────────────────────────────────

export interface AccessRequest {
  id: string;
  credential_id: string;
  credential_label: string;
  credential_type: string;
  requester_id: string;
  requester_email: string;
  requester_name: string;
  reason: string;
  requested_hours: number | null;
  status: "pending" | "approved" | "denied" | "cancelled";
  decided_by_email: string | null;
  decided_at: string | null;
  decision_note: string;
  granted_until: string | null;
  can_view_password: boolean;
  created_at: string;
}

interface Requestable {
  id: string;
  label: string;
  credential_type: string;
  website_name: string | null;
  client_name: string | null;
  department: string;
}

// Mirrors CredentialAccessRequest.DURATION_CHOICES. "" is permanent: a Select
// value cannot be null.
const DURATIONS = [
  { value: "4", label: "4 hours" },
  { value: "24", label: "1 day" },
  { value: "168", label: "7 days" },
  { value: "", label: "Permanently" },
] as const;
const PERMANENT = "permanent";

function durationValue(hours: number | null) {
  return hours ? String(hours) : PERMANENT;
}
function hoursFrom(value: string): number | null {
  return value === PERMANENT ? null : Number(value);
}
function durationLabel(hours: number | null) {
  return DURATIONS.find((d) => d.value === (hours ? String(hours) : ""))?.label ?? `${hours} hours`;
}

function errorMessage(data: unknown, fallback: string): string {
  const d = data as { errors?: { message?: string }[]; detail?: string } | null;
  return d?.errors?.[0]?.message ?? d?.detail ?? fallback;
}

function asList<T>(data: unknown): T[] {
  if (Array.isArray(data)) return data as T[];
  const inner = (data as { data?: unknown } | null)?.data;
  return Array.isArray(inner) ? (inner as T[]) : [];
}

// ─── Approver panel ───────────────────────────────────────────────────────────

/**
 * Pending requests on credentials the viewer may share. Renders nothing when
 * there are none, so it costs the vault no space on an ordinary day.
 */
export function AccessRequestsPanel({ onDecided }: { onDecided?: () => void }) {
  const { toast } = useToast();
  const [requests, setRequests] = useState<AccessRequest[]>([]);
  const [busyId, setBusyId] = useState<string | null>(null);
  // Per-request overrides of what the approver grants.
  const [durations, setDurations] = useState<Record<string, string>>({});
  const [canView, setCanView] = useState<Record<string, boolean>>({});

  const load = useCallback(async () => {
    const res = await fetch("/api/credentials/access-requests?scope=to_me");
    if (!res.ok) return;
    setRequests(asList<AccessRequest>(await res.json().catch(() => [])));
  }, []);

  useEffect(() => {
    let active = true;
    (async () => {
      const res = await fetch("/api/credentials/access-requests?scope=to_me");
      if (!res.ok || !active) return;
      setRequests(asList<AccessRequest>(await res.json().catch(() => [])));
    })();
    return () => { active = false; };
  }, []);

  async function decide(req: AccessRequest, approve: boolean) {
    setBusyId(req.id);
    try {
      const res = await fetch(`/api/credentials/access-requests/${req.id}/decide`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          approve,
          hours: hoursFrom(durations[req.id] ?? durationValue(req.requested_hours)),
          can_view_password: !!canView[req.id],
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        toast({ variant: "destructive", title: "Could not decide the request", description: errorMessage(data, `Error ${res.status}`) });
        return;
      }
      toast({ title: approve ? `Access granted to ${req.requester_name}` : "Request denied" });
      await load();
      onDecided?.();
    } finally {
      setBusyId(null);
    }
  }

  if (requests.length === 0) return null;

  return (
    <section className="rounded-xl border border-amber-200 bg-amber-50/60 dark:border-amber-900 dark:bg-amber-950/30 p-4 space-y-3">
      <div className="flex items-center gap-2">
        <KeyRound className="h-4 w-4 text-amber-700 dark:text-amber-400" />
        <h2 className="text-sm font-semibold">
          {requests.length} access request{requests.length !== 1 ? "s" : ""} waiting for you
        </h2>
      </div>
      <ul className="space-y-2">
        {requests.map((r) => (
          <li key={r.id} className="rounded-lg border bg-card p-3 flex flex-wrap items-center gap-3">
            <div className="min-w-0 flex-1">
              <p className="text-sm">
                <span className="font-medium">{r.requester_name}</span> wants{" "}
                <span className="font-medium">{r.credential_label}</span>{" "}
                <span className="text-muted-foreground">for {durationLabel(r.requested_hours).toLowerCase()}</span>
              </p>
              {r.reason && <p className="text-xs text-muted-foreground mt-0.5 truncate">“{r.reason}”</p>}
            </div>
            <Select
              value={durations[r.id] ?? durationValue(r.requested_hours)}
              onValueChange={(v) => setDurations((d) => ({ ...d, [r.id]: v }))}
            >
              <SelectTrigger className="h-8 w-[130px] text-xs" aria-label="Grant for"><SelectValue /></SelectTrigger>
              <SelectContent>
                {DURATIONS.map((d) => (
                  <SelectItem key={d.label} value={d.value || PERMANENT}>{d.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <label className="flex items-center gap-1.5 text-xs text-muted-foreground cursor-pointer" title="Off: they can autofill it but never see the password">
              <input
                type="checkbox"
                className="h-3.5 w-3.5 accent-primary"
                checked={!!canView[r.id]}
                onChange={(e) => setCanView((c) => ({ ...c, [r.id]: e.target.checked }))}
              />
              Can view password
            </label>
            <div className="flex gap-1.5">
              <Button size="sm" className="h-8" disabled={busyId === r.id} onClick={() => decide(r, true)}>
                <Check className="h-3.5 w-3.5 mr-1" />Approve
              </Button>
              <Button size="sm" variant="outline" className="h-8" disabled={busyId === r.id} onClick={() => decide(r, false)}>
                <X className="h-3.5 w-3.5 mr-1" />Deny
              </Button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

// ─── Request dialog ───────────────────────────────────────────────────────────

/**
 * Ask for a credential you cannot see. Lists the team's other credentials by
 * name (never their contents), plus the requester's own recent requests so
 * "did they answer yet?" has somewhere to look.
 */
export function RequestAccessDialog({ onClose }: { onClose: () => void }) {
  const { toast } = useToast();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Requestable[]>([]);
  const [picked, setPicked] = useState<Requestable | null>(null);
  const [reason, setReason] = useState("");
  const [duration, setDuration] = useState("24");
  const [busy, setBusy] = useState(false);
  const [mine, setMine] = useState<AccessRequest[]>([]);

  useEffect(() => {
    let active = true;
    const t = setTimeout(async () => {
      const res = await fetch(`/api/credentials/requestable?q=${encodeURIComponent(query)}`);
      if (!res.ok || !active) return;
      setResults(asList<Requestable>(await res.json().catch(() => [])));
    }, 250);
    return () => { active = false; clearTimeout(t); };
  }, [query]);

  useEffect(() => {
    let active = true;
    (async () => {
      const res = await fetch("/api/credentials/access-requests?scope=mine");
      if (!res.ok || !active) return;
      setMine(asList<AccessRequest>(await res.json().catch(() => [])).slice(0, 5));
    })();
    return () => { active = false; };
  }, []);

  async function submit() {
    if (!picked) return;
    setBusy(true);
    try {
      const res = await fetch(`/api/credentials/${picked.id}/access-requests`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason, hours: hoursFrom(duration === "" ? PERMANENT : duration) }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        toast({ variant: "destructive", title: "Could not send the request", description: errorMessage(data, `Error ${res.status}`) });
        return;
      }
      toast({
        title: res.status === 201 ? "Request sent" : "Already requested",
        description: "Owners, managers and the person who saved it have been told.",
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
          <DialogTitle>Request access</DialogTitle>
          <DialogDescription>
            Ask for a login you cannot see. Whoever approves it decides for how
            long, and whether you can see the password or only autofill it.
          </DialogDescription>
        </DialogHeader>

        {!picked ? (
          <div className="space-y-2">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none" />
              <Input
                autoFocus
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search by name, client or website…"
                className="pl-9"
              />
            </div>
            <ul className="max-h-64 overflow-y-auto divide-y rounded-md border">
              {results.length === 0 ? (
                <li className="px-3 py-4 text-sm text-muted-foreground">
                  {query ? "Nothing matches." : "Nothing to request — you can already see every login."}
                </li>
              ) : (
                results.map((r) => (
                  <li key={r.id}>
                    <button
                      type="button"
                      onClick={() => setPicked(r)}
                      className="w-full text-left px-3 py-2 hover:bg-muted/60 transition-colors"
                    >
                      <p className="text-sm font-medium truncate">{r.label}</p>
                      <p className="text-xs text-muted-foreground truncate">
                        {[r.client_name, r.website_name].filter(Boolean).join(" · ") || "No client"}
                      </p>
                    </button>
                  </li>
                ))
              )}
            </ul>
          </div>
        ) : (
          <div className="space-y-3">
            <div className="rounded-md border px-3 py-2 flex items-center gap-2">
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium truncate">{picked.label}</p>
                <p className="text-xs text-muted-foreground truncate">
                  {[picked.client_name, picked.website_name].filter(Boolean).join(" · ") || "No client"}
                </p>
              </div>
              <Button size="sm" variant="ghost" onClick={() => setPicked(null)}>Change</Button>
            </div>
            <div className="space-y-1.5">
              <Label>For how long</Label>
              <Select value={duration || PERMANENT} onValueChange={setDuration}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {DURATIONS.map((d) => (
                    <SelectItem key={d.label} value={d.value || PERMANENT}>{d.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label>Why <span className="text-muted-foreground">(optional)</span></Label>
              <Input
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                maxLength={300}
                placeholder="e.g. Renewing their SSL certificate"
              />
            </div>
          </div>
        )}

        {mine.length > 0 && (
          <div className="space-y-1">
            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Your recent requests</p>
            <ul className="text-xs space-y-0.5">
              {mine.map((r) => (
                <li key={r.id} className="flex justify-between gap-2">
                  <span className="truncate">{r.credential_label}</span>
                  <span className="text-muted-foreground shrink-0">
                    {r.status === "approved" && r.granted_until
                      ? `approved until ${new Date(r.granted_until).toLocaleString()}`
                      : r.status}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button onClick={submit} disabled={!picked || busy}>{busy ? "Sending…" : "Send request"}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
