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
    return NextResponse.json(payload, { status: upstream.status });
  } catch {
    return NextResponse.json(
      { detail: "Could not reach the server. Please try again shortly." },
      { status: 502 },
    );
  }
}
