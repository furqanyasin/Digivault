import { NextRequest, NextResponse } from "next/server";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function GET(req: NextRequest) {
  const code = req.nextUrl.searchParams.get("code") ?? "";
  if (!code) {
    return NextResponse.json({ detail: "Missing code" }, { status: 400 });
  }

  let upstream: Response;
  try {
    upstream = await fetch(
      `${API_BASE}/api/extension/exchange/?code=${encodeURIComponent(code)}`
    );
  } catch {
    return NextResponse.json({ detail: "Cannot reach backend" }, { status: 502 });
  }

  if (!upstream.ok) {
    return NextResponse.json(
      { detail: "Invalid or expired link" },
      { status: 400 }
    );
  }

  let envelope: { data?: { access: string; refresh: string } };
  try {
    envelope = await upstream.json();
  } catch {
    return NextResponse.json({ detail: "Backend returned invalid response" }, { status: 502 });
  }

  const tokens = (envelope.data ?? envelope) as { access: string; refresh: string };
  const res = NextResponse.json({ ok: true });

  res.cookies.set("ss_access", tokens.access, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: 60 * 5,
  });
  res.cookies.set("ss_refresh", tokens.refresh, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: 60 * 60 * 24 * 7,
  });

  return res;
}
