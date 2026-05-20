import { NextRequest, NextResponse } from "next/server";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function POST(req: NextRequest) {
  const body = await req.json();

  let upstream: Response;
  try {
    upstream = await fetch(`${API_BASE}/api/v1/auth/2fa/verify/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    return NextResponse.json({ detail: "Cannot reach backend server" }, { status: 502 });
  }

  const envelope = await upstream.json().catch(() => ({}));
  const data: Record<string, unknown> = envelope?.data ?? envelope;

  if (!upstream.ok) {
    return NextResponse.json(data, { status: upstream.status });
  }

  const { access, refresh } = data as { access: string; refresh: string };
  const res = NextResponse.json({ ok: true, access, refresh });
  res.cookies.set("ss_access", access, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: 60 * 5,
  });
  res.cookies.set("ss_refresh", refresh, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: 60 * 60 * 24 * 7,
  });
  return res;
}
