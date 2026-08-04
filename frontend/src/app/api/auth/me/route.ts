import { NextResponse } from "next/server";
import { cookies } from "next/headers";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// GET /api/auth/me — the signed-in user, for client components that can't use
// the server-side getAccessToken() helper. Returns the envelope untouched;
// callers read `.data`.
export async function GET() {
  const jar = await cookies();
  const token = jar.get("ss_access")?.value;
  if (!token) return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });

  const upstream = await fetch(`${API_BASE}/api/v1/auth/me/`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  const body = await upstream.json().catch(() => ({}));
  return NextResponse.json(body, { status: upstream.status });
}
