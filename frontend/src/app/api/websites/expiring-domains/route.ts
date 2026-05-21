import { NextResponse } from "next/server";
import { cookies } from "next/headers";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function GET() {
  const jar = await cookies();
  const token = jar.get("ss_access")?.value;
  if (!token) return NextResponse.json([], { status: 401 });
  const upstream = await fetch(`${API_BASE}/api/v1/websites/expiring-domains/?days=30`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const envelope = await upstream.json().catch(() => ({}));
  return NextResponse.json(envelope?.data ?? envelope, { status: upstream.status });
}
