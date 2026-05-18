import { NextRequest, NextResponse } from "next/server";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function POST(req: NextRequest) {
  const body = await req.json();

  // Step 1: create the user (field is "name", not "full_name")
  const registerRes = await fetch(`${API_BASE}/api/v1/auth/register/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: body.email, password: body.password, name: body.name }),
  });

  let registerData: unknown;
  try {
    registerData = await registerRes.json();
  } catch {
    return NextResponse.json({ detail: "Backend error" }, { status: 502 });
  }

  if (!registerRes.ok) {
    return NextResponse.json(registerData, { status: registerRes.status });
  }

  // Step 2: obtain tokens
  const tokenRes = await fetch(`${API_BASE}/api/v1/auth/token/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: body.email, password: body.password }),
  });

  let tokenEnvelope: { data?: { access: string; refresh: string }; errors?: unknown[] };
  try {
    tokenEnvelope = await tokenRes.json();
  } catch {
    return NextResponse.json({ detail: "Token error" }, { status: 502 });
  }

  if (!tokenRes.ok) {
    return NextResponse.json(tokenEnvelope, { status: tokenRes.status });
  }

  const { access, refresh } = tokenEnvelope.data!;
  const res = NextResponse.json({ ok: true });
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
