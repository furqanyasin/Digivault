import { NextRequest, NextResponse } from "next/server";
import { cookies } from "next/headers";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const COOKIE_OPTS = (maxAge: number) => ({
  httpOnly: true,
  secure: process.env.NODE_ENV === "production",
  sameSite: "lax" as const,
  path: "/",
  maxAge,
});

export async function POST(req: NextRequest) {
  const jar = await cookies();
  const deviceToken = jar.get("ss_2fa_device")?.value;

  const body = await req.json();

  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (deviceToken) headers["X-2FA-Device-Token"] = deviceToken;

  let upstream: Response;
  try {
    upstream = await fetch(`${API_BASE}/api/v1/auth/login/`, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
    });
  } catch {
    return NextResponse.json({ detail: "Cannot reach backend server" }, { status: 502 });
  }

  let data: Record<string, unknown>;
  try {
    const envelope = await upstream.json();
    data = envelope?.data ?? envelope;
  } catch {
    return NextResponse.json({ detail: "Backend returned invalid response" }, { status: 502 });
  }

  if (!upstream.ok) {
    return NextResponse.json(data, { status: upstream.status });
  }

  // 2FA required or setup needed — return to client so it can show the TOTP step
  if (data.requires_2fa || data.requires_setup) {
    return NextResponse.json(data);
  }

  // Tokens returned directly (trusted device skipped 2FA, or no 2FA)
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
