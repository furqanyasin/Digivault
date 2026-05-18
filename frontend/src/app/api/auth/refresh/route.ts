import { NextRequest, NextResponse } from "next/server";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function POST(req: NextRequest) {
  const refresh = req.cookies.get("ss_refresh")?.value;
  if (!refresh) {
    return NextResponse.json({ detail: "No refresh token" }, { status: 401 });
  }

  const upstream = await fetch(`${API_BASE}/api/v1/auth/token/refresh/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh }),
  });

  let envelope: { data?: { access: string }; errors?: unknown[] };
  try {
    envelope = await upstream.json();
  } catch {
    return NextResponse.json({ detail: "Backend error" }, { status: 502 });
  }
  if (!upstream.ok) {
    const res = NextResponse.json(envelope, { status: upstream.status });
    res.cookies.delete("ss_access");
    res.cookies.delete("ss_refresh");
    return res;
  }

  const { access } = envelope.data!;
  const res = NextResponse.json({ ok: true });
  res.cookies.set("ss_access", access, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: 60 * 5,
  });

  return res;
}
