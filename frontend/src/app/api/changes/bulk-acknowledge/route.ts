import { NextRequest, NextResponse } from "next/server";
import { cookies } from "next/headers";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function POST(req: NextRequest) {
  const jar = await cookies();
  const token = jar.get("ss_access")?.value;
  if (!token) return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });

  const body = await req.json();
  const upstream = await fetch(`${API_BASE}/api/v1/changes/bulk-acknowledge/`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify(body),
  });
  const envelope = await upstream.json().catch(() => ({}));
  return NextResponse.json(envelope?.data ?? envelope, { status: upstream.status });
}
