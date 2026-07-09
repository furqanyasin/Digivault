import { NextRequest, NextResponse } from "next/server";
import { cookies } from "next/headers";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function getToken() {
  const jar = await cookies();
  return jar.get("ss_access")?.value;
}

type Ctx = { params: Promise<{ id: string; memberId: string }> };

export async function PATCH(req: NextRequest, { params }: Ctx) {
  const token = await getToken();
  if (!token) return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
  const { id, memberId } = await params;
  const body = await req.json();
  const upstream = await fetch(`${API_BASE}/api/v1/auth/teams/${id}/members/${memberId}/`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify(body),
  });
  const envelope = await upstream.json().catch(() => ({}));
  return NextResponse.json(envelope?.data ?? envelope, { status: upstream.status });
}

export async function DELETE(req: NextRequest, { params }: Ctx) {
  const token = await getToken();
  if (!token) return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
  const { id, memberId } = await params;
  const permanent = req.nextUrl.searchParams.get("permanent") === "true";
  const suffix = permanent ? "?permanent=true" : "";
  const upstream = await fetch(`${API_BASE}/api/v1/auth/teams/${id}/members/${memberId}/${suffix}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (upstream.status === 204) return new NextResponse(null, { status: 204 });
  const envelope = await upstream.json().catch(() => ({}));
  return NextResponse.json(envelope?.data ?? envelope, { status: upstream.status });
}
