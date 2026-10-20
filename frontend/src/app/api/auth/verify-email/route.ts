import { NextRequest, NextResponse } from "next/server";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// POST — confirm a signup email. When 2FA is optional for the new account the
// backend signs it in, and the tokens become the usual session cookies.
export async function POST(req: NextRequest) {
  const { token } = await req.json().catch(() => ({ token: "" }));
  let upstream: Response;
  try {
    upstream = await fetch(`${API_BASE}/api/v1/auth/verify-email/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    });
  } catch {
    return NextResponse.json({ detail: "Could not reach the server. Please try again." }, { status: 502 });
  }
  const envelope = await upstream.json().catch(() => ({}));
  const data = envelope?.data ?? envelope;
  if (!upstream.ok) {
    return NextResponse.json(
      { detail: data?.detail ?? envelope?.errors?.[0]?.message ?? "This link is not valid." },
      { status: upstream.status },
    );
  }
  if (data?.access && data?.refresh) {
    const res = NextResponse.json({ ok: true, signed_in: true });
    const opts = { httpOnly: true, secure: process.env.NODE_ENV === "production", sameSite: "lax" as const, path: "/" };
    res.cookies.set("ss_access", data.access, { ...opts, maxAge: 60 * 5 });
    res.cookies.set("ss_refresh", data.refresh, { ...opts, maxAge: 60 * 60 * 24 * 7 });
    return res;
  }
  return NextResponse.json({ ok: true, signed_in: false, detail: data?.detail });
}
