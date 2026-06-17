"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { ChevronDown, Check, Users, Plus, Loader2 } from "lucide-react";
import type { Team } from "@/lib/api";

interface Props {
  teams: Team[];
  activeTeamId: string | null;
}

export function TeamSwitcher({ teams, activeTeamId }: Props) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [switching, startTransition] = useTransition();
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [saving, setSaving] = useState(false);

  const activeTeam = teams.find((t) => t.id === activeTeamId) ?? teams[0];

  async function switchTeam(teamId: string) {
    if (teamId === activeTeamId) { setOpen(false); return; }
    setOpen(false);
    await fetch(`/api/teams/${teamId}/switch`, { method: "POST" });
    startTransition(() => router.refresh());
  }

  async function createDepartment() {
    const name = newName.trim();
    if (!name) return;
    setSaving(true);
    try {
      const res = await fetch("/api/teams", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      if (res.ok) {
        const team = await res.json();
        const id = team?.id;
        setNewName("");
        setCreating(false);
        setOpen(false);
        if (id) await fetch(`/api/teams/${id}/switch`, { method: "POST" });
        startTransition(() => router.refresh());
      }
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-3 py-2 text-sm font-medium rounded-md hover:bg-accent transition-colors"
        disabled={switching}
      >
        <Users className="h-4 w-4 text-muted-foreground shrink-0" />
        <span className="flex-1 text-left truncate">{activeTeam?.name ?? "Select team"}</span>
        <ChevronDown className={`h-3.5 w-3.5 opacity-50 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => { setOpen(false); setCreating(false); }} />
          <div className="absolute left-0 right-0 top-full mt-1 z-20 bg-popover border rounded-md shadow-lg py-1 max-h-[60vh] overflow-y-auto">
            {teams.map((team) => (
              <button
                key={team.id}
                onClick={() => switchTeam(team.id)}
                className="w-full flex items-center gap-2 px-3 py-2 text-sm hover:bg-accent transition-colors text-left"
              >
                <span className="flex-1 truncate">{team.name}</span>
                {team.id === activeTeamId && <Check className="h-3.5 w-3.5 text-primary shrink-0" />}
              </button>
            ))}

            <div className="border-t my-1" />
            {creating ? (
              <div className="px-2 py-1.5 flex items-center gap-1.5">
                <input
                  autoFocus
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") createDepartment(); }}
                  placeholder="Department name"
                  className="flex-1 min-w-0 border rounded px-2 py-1 text-sm bg-background"
                />
                <button
                  onClick={createDepartment}
                  disabled={saving || !newName.trim()}
                  className="p-1 rounded text-primary hover:bg-accent disabled:opacity-50"
                  aria-label="Create department"
                >
                  {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
                </button>
              </div>
            ) : (
              <button
                onClick={() => setCreating(true)}
                className="w-full flex items-center gap-2 px-3 py-2 text-sm text-muted-foreground hover:bg-accent hover:text-foreground transition-colors text-left"
              >
                <Plus className="h-3.5 w-3.5 shrink-0" />
                New department
              </button>
            )}
          </div>
        </>
      )}
    </div>
  );
}
