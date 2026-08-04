import { NextResponse } from "next/server";
import { cookies } from "next/headers";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// GET /api/auth/teams — the teams the user belongs to, each carrying `my_role`
// and `my_features`. That role is what client-side pages gate on, so this route
// missing meant every caller silently fell back to "viewer".
export async function GET() {
  const jar = await cookies();
  const token = jar.get("ss_access")?.value;
  if (!token) return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });

  const upstream = await fetch(`${API_BASE}/api/v1/auth/teams/`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  const body = await upstream.json().catch(() => ({}));
  return NextResponse.json(body, { status: upstream.status });
}
