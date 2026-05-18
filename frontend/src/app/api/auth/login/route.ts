import { NextRequest, NextResponse } from "next/server";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function POST(req: NextRequest) {
  const body = await req.json();

  let upstream: Response;
  try {
    upstream = await fetch(`${API_BASE}/api/v1/auth/token/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    return NextResponse.json({ detail: "Cannot reach backend server" }, { status: 502 });
  }

  let envelope: { data?: { access: string; refresh: string }; errors?: unknown[] };
  try {
    envelope = await upstream.json();
  } catch {
    return NextResponse.json({ detail: "Backend returned invalid response" }, { status: 502 });
  }

  if (!upstream.ok) {
    return NextResponse.json(envelope, { status: upstream.status });
  }

  const tokens = envelope.data ?? (envelope as unknown as { access: string; refresh: string });
  const { access, refresh } = tokens;

  const res = NextResponse.json({ ok: true });
  res.cookies.set("ss_access", access, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: 60 * 5, // 5 min — matches SimpleJWT ACCESS_TOKEN_LIFETIME
  });
  res.cookies.set("ss_refresh", refresh, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: 60 * 60 * 24 * 7, // 7 days
  });

  return res;
}
