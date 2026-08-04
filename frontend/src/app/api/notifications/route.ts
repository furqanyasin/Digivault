import { NextRequest, NextResponse } from "next/server";
import { cookies } from "next/headers";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// GET /api/notifications — the team's alert feed. `?unread=true` narrows it,
// which is what the bell polls for its count.
export async function GET(req: NextRequest) {
  const jar = await cookies();
  const token = jar.get("ss_access")?.value;
  if (!token) return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });

  const qs = req.nextUrl.searchParams.toString();
  const upstream = await fetch(
    `${API_BASE}/api/v1/notifications/${qs ? `?${qs}` : ""}`,
    { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" }
  );
  const body = await upstream.json().catch(() => ({}));
  return NextResponse.json(body, { status: upstream.status });
}
