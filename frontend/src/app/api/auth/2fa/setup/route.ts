import { NextRequest, NextResponse } from "next/server";
import { cookies } from "next/headers";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function GET(req: NextRequest) {
  const jar = await cookies();
  const token = jar.get("ss_access")?.value;
  const preAuthKey = req.nextUrl.searchParams.get("session_key") ?? req.headers.get("x-pre-auth-key") ?? "";

  const headers: Record<string, string> = {};
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  } else if (preAuthKey) {
    headers["X-Pre-Auth-Key"] = preAuthKey;
  } else {
    return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
  }

  const upstream = await fetch(`${API_BASE}/api/v1/auth/2fa/setup/`, { headers });
  const envelope = await upstream.json().catch(() => ({}));
  return NextResponse.json(envelope?.data ?? envelope, { status: upstream.status });
}
