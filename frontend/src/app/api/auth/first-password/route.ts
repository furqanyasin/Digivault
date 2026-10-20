import { NextRequest, NextResponse } from "next/server";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// POST — public: set the initial password using a pre-auth session key.
export async function POST(req: NextRequest) {
  const body = await req.json();
  try {
    const upstream = await fetch(`${API_BASE}/api/v1/auth/first-password/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await upstream.json().catch(() => ({}));
    const payload = data?.data ?? data;
    // 2FA is optional for this account, so the backend signed it in directly.
    if (upstream.ok && payload?.access && payload?.refresh) {
      const res = NextResponse.json({ ok: true, signed_in: true });
      const secure = process.env.NODE_ENV === "production";
      const opts = { httpOnly: true, secure, sameSite: "lax" as const, path: "/" };
      res.cookies.set("ss_access", payload.access, { ...opts, maxAge: 60 * 5 });
      res.cookies.set("ss_refresh", payload.refresh, { ...opts, maxAge: 60 * 60 * 24 * 7 });
      return res;
    }
    return NextResponse.json(payload, { status: upstream.status });
  } catch {
    return NextResponse.json(
      { detail: "Could not reach the server. Please try again shortly." },
      { status: 502 },
    );
  }
}
