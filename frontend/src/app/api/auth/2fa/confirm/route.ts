import { NextRequest, NextResponse } from "next/server";
import { cookies } from "next/headers";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function POST(req: NextRequest) {
  const jar = await cookies();
  const token = jar.get("ss_access")?.value;
  const body = await req.json();
  const preAuthKey = (body.session_key ?? req.headers.get("x-pre-auth-key") ?? "").trim();

  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  } else if (preAuthKey) {
    headers["X-Pre-Auth-Key"] = preAuthKey;
  } else {
    return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
  }

  const { session_key: _sk, ...forwardBody } = body;
  const upstream = await fetch(`${API_BASE}/api/v1/auth/2fa/confirm/`, {
    method: "POST",
    headers,
    body: JSON.stringify(forwardBody),
  });
  const envelope = await upstream.json().catch(() => ({}));
  const data: Record<string, unknown> = envelope?.data ?? envelope;

  if (!upstream.ok) {
    return NextResponse.json(data, { status: upstream.status });
  }

  const cookieOpts = (maxAge: number) => ({
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax" as const,
    path: "/",
    maxAge,
  });

  const res = NextResponse.json(data);

  // If the backend issued tokens (pre-auth setup flow), set cookies
  if (data.access && data.refresh) {
    res.cookies.set("ss_access", data.access as string, cookieOpts(60 * 5));
    res.cookies.set("ss_refresh", data.refresh as string, cookieOpts(60 * 60 * 24 * 7));
    if (data.device_trust_token) {
      res.cookies.set("ss_2fa_device", data.device_trust_token as string, cookieOpts(60 * 60 * 10));
    }
  }

  return res;
}
