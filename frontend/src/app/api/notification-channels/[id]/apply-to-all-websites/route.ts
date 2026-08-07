import { NextRequest, NextResponse } from "next/server";
import { cookies } from "next/headers";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Ctx = { params: Promise<{ id: string }> };

export async function POST(_req: NextRequest, { params }: Ctx) {
  const jar = await cookies();
  const token = jar.get("ss_access")?.value;
  if (!token) return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
  const { id } = await params;
  const upstream = await fetch(
    `${API_BASE}/api/v1/notification-channels/${id}/apply-to-all-websites/`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    }
  );
  const envelope = await upstream.json().catch(() => ({}));
  // Errors arrive as { errors: [{ message }] }; surface the first so the button
  // can say why (a developer hitting this gets a 403, not a silent no-op).
  const body = envelope?.data ?? {
    detail: envelope?.errors?.[0]?.message ?? envelope?.detail ?? "Could not apply channel",
  };
  return NextResponse.json(body, { status: upstream.status });
}
