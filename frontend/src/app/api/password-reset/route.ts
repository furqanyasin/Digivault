import { NextRequest, NextResponse } from "next/server";
import { cookies } from "next/headers";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function getToken() {
  const jar = await cookies();
  return jar.get("ss_access")?.value;
}

// POST — public: user requests a password reset
export async function POST(req: NextRequest) {
  const body = await req.json();
  try {
    const upstream = await fetch(`${API_BASE}/api/v1/auth/password-reset/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await upstream.json().catch(() => ({}));
    const payload = data?.data ?? data;
    return NextResponse.json(payload, { status: upstream.status });
  } catch {
    // Django unreachable from the Next server (e.g. NEXT_PUBLIC_API_URL misconfig).
    // Surface a clear message instead of an opaque 500 / mislabelled error.
    return NextResponse.json(
      { detail: "Could not reach the server. Please try again shortly." },
      { status: 502 },
    );
  }
}

// GET — authenticated: manager lists pending requests
export async function GET() {
  const token = await getToken();
  if (!token) return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
  const upstream = await fetch(`${API_BASE}/api/v1/auth/password-reset/`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const data = await upstream.json().catch(() => ([]));
  return NextResponse.json(data?.data ?? data, { status: upstream.status });
}
