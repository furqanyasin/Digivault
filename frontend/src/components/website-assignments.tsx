"use client";

import { useEffect, useState } from "react";
import { Users } from "lucide-react";

interface UserRow { user_id: string; email: string; name: string; role?: string }
interface AssignmentsData { assigned: UserRow[]; members: UserRow[]; can_edit: boolean }

export function WebsiteAssignments({ websiteId }: { websiteId: string }) {
  const [data, setData] = useState<AssignmentsData | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    (async () => {
      const res = await fetch(`/api/websites/${websiteId}/assignments`);
      if (res.ok) setData(await res.json());
    })();
  }, [websiteId]);

  if (!data) return null;

  const assignedIds = new Set(data.assigned.map((u) => u.user_id));

  async function toggle(userId: string) {
    if (!data || !data.can_edit || saving) return;
    const next = new Set(assignedIds);
    if (next.has(userId)) next.delete(userId);
    else next.add(userId);
    setSaving(true);
    setSaved(false);
    try {
      const res = await fetch(`/api/websites/${websiteId}/assignments`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_ids: Array.from(next) }),
      });
      if (res.ok) {
        setData(await res.json());
        setSaved(true);
      }
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-sm font-medium">
        <Users className="h-4 w-4 text-muted-foreground" />
        Assigned users
        {saved && <span className="text-xs font-normal text-emerald-600">Saved</span>}
      </div>
      {data.can_edit ? (
        <>
          <div className="space-y-1">
            {data.members.map((m) => (
              <label key={m.user_id} className="flex items-center gap-2 text-sm cursor-pointer">
                <input
                  type="checkbox"
                  checked={assignedIds.has(m.user_id)}
                  onChange={() => toggle(m.user_id)}
                  disabled={saving}
                  className="h-4 w-4 rounded border-input"
                />
                <span>{m.name}</span>
                <span className="text-xs text-muted-foreground">{m.role}</span>
              </label>
            ))}
          </div>
          <p className="text-xs text-muted-foreground">
            Assigned non-manager members see only their assigned websites. With no
            assignments a member sees every site (team default).
          </p>
        </>
      ) : data.assigned.length > 0 ? (
        <p className="text-sm text-muted-foreground">
          {data.assigned.map((u) => u.name).join(", ")}
        </p>
      ) : (
        <p className="text-sm text-muted-foreground">No specific assignments — whole team.</p>
      )}
    </div>
  );
}
