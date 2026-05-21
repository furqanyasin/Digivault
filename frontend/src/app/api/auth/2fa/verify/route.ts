import { NextRequest, NextResponse } from "next/server";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const COOKIE_OPTS = (maxAge: number) => ({
  httpOnly: true,
  secure: process.env.NODE_ENV === "production",
  sameSite: "lax" as const,
  path: "/",
  maxAge,
});

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
  const data = (envelope?.data ?? envelope) as Record<string, unknown>;

  if (!upstream.ok) {
    return NextResponse.json(data, { status: upstream.status });
  }

  const { access, refresh, device_trust_token } = data as {
    access: string;
    refresh: string;
    device_trust_token?: string;
  };

  const res = NextResponse.json({ ok: true });
  res.cookies.set("ss_access", access, COOKIE_OPTS(60 * 5));
  res.cookies.set("ss_refresh", refresh, COOKIE_OPTS(60 * 60 * 24 * 7));
  if (device_trust_token) {
    res.cookies.set("ss_2fa_device", device_trust_token, COOKIE_OPTS(60 * 60 * 10));
  }
  return res;
}
