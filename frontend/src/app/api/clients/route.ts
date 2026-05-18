import { NextRequest, NextResponse } from "next/server";
import { cookies } from "next/headers";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function getToken() {
  const jar = await cookies();
  return jar.get("ss_access")?.value;
}

export async function GET(req: NextRequest) {
  const token = await getToken();
  if (!token) return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
  const search = req.nextUrl.searchParams.toString();
  const upstream = await fetch(`${API_BASE}/api/v1/clients/${search ? `?${search}` : ""}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const data = await upstream.json().catch(() => ([]));
  return NextResponse.json(data?.data ?? data, { status: upstream.status });
}

export async function POST(req: NextRequest) {
  const token = await getToken();
  if (!token) return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
  const body = await req.json();
  const upstream = await fetch(`${API_BASE}/api/v1/clients/`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify(body),
  });
  const data = await upstream.json().catch(() => ({}));
  return NextResponse.json(data?.data ?? data, { status: upstream.status });
}
