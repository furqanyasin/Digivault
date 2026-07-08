"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { ChevronDown, Check, Users } from "lucide-react";
import type { Team } from "@/lib/api";

interface Props {
  teams: Team[];
  activeTeamId: string | null;
}

export function TeamSwitcher({ teams, activeTeamId }: Props) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [switching, startTransition] = useTransition();

  const activeTeam = teams.find((t) => t.id === activeTeamId) ?? teams[0];

  async function switchTeam(teamId: string) {
    if (teamId === activeTeamId) { setOpen(false); return; }
    setOpen(false);
    await fetch(`/api/teams/${teamId}/switch`, { method: "POST" });
    startTransition(() => router.refresh());
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
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
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
          </div>
        </>
      )}
    </div>
  );
}
