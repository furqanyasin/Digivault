import { NextRequest, NextResponse } from "next/server";
import { cookies } from "next/headers";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
type Ctx = { params: Promise<{ id: string }> };

async function getToken() {
  const jar = await cookies();
  return jar.get("ss_access")?.value;
}

export async function GET(_req: NextRequest, { params }: Ctx) {
  const token = await getToken();
  if (!token) return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
  const { id } = await params;
  const upstream = await fetch(`${API_BASE}/api/v1/clients/${id}/`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const data = await upstream.json().catch(() => ({}));
  return NextResponse.json(data?.data ?? data, { status: upstream.status });
}

export async function PATCH(req: NextRequest, { params }: Ctx) {
  const token = await getToken();
  if (!token) return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
  const { id } = await params;
  const body = await req.json();
  const upstream = await fetch(`${API_BASE}/api/v1/clients/${id}/`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify(body),
  });
  const data = await upstream.json().catch(() => ({}));
  return NextResponse.json(data?.data ?? data, { status: upstream.status });
}

export async function DELETE(_req: NextRequest, { params }: Ctx) {
  const token = await getToken();
  if (!token) return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
  const { id } = await params;
  const upstream = await fetch(`${API_BASE}/api/v1/clients/${id}/`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${token}` },
  });
  // A successful delete answers 204 with no body — NextResponse.json() would
  // write one, which is not a legal 204.
  if (upstream.status === 204) return new NextResponse(null, { status: 204 });
  // On a refusal the body is the error envelope, whose `data` is null: the ??
  // then passes the whole envelope through so the caller can read `errors`.
  const data = await upstream.json().catch(() => ({}));
  return NextResponse.json(data?.data ?? data, { status: upstream.status });
}
