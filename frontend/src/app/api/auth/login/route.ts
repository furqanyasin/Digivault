import { NextRequest, NextResponse } from "next/server";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

function setTokenCookies(res: NextResponse, access: string, refresh: string) {
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
}

export async function POST(req: NextRequest) {
  const body = await req.json();

  let upstream: Response;
  try {
    upstream = await fetch(`${API_BASE}/api/v1/auth/login/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
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

  // 2FA enrolled — return session_key so the frontend can show the TOTP step
  if (data.requires_2fa || data.requires_setup) {
    return NextResponse.json(data);
  }

  // Direct token pair (should not happen with mandatory 2FA, but handle gracefully)
  const { access, refresh } = data as { access: string; refresh: string };
  const res = NextResponse.json({ ok: true, access, refresh });
  setTokenCookies(res, access, refresh);
  return res;
}
