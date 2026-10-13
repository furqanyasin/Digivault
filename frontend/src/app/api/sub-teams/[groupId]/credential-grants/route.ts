import { NextRequest, NextResponse } from "next/server";
import { cookies } from "next/headers";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function getToken() {
  const jar = await cookies();
  return jar.get("ss_access")?.value;
}

type Ctx = { params: Promise<{ groupId: string }> };

export async function GET(_req: NextRequest, { params }: Ctx) {
  const token = await getToken();
  if (!token) return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
  const { groupId } = await params;
  const upstream = await fetch(
    `${API_BASE}/api/v1/sub-teams/${groupId}/credential-grants/`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  const envelope = await upstream.json().catch(() => ({}));
  return NextResponse.json(envelope?.data ?? envelope, { status: upstream.status });
}

export async function POST(req: NextRequest, { params }: Ctx) {
  const token = await getToken();
  if (!token) return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
  const { groupId } = await params;
  const body = await req.json();
  const upstream = await fetch(
    `${API_BASE}/api/v1/sub-teams/${groupId}/credential-grants/`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify(body),
    },
  );
  const envelope = await upstream.json().catch(() => ({}));
  return NextResponse.json(envelope?.data ?? envelope, { status: upstream.status });
}
