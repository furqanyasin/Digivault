import { NextRequest, NextResponse } from "next/server";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

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

