import { NextRequest, NextResponse } from "next/server";
import { cookies } from "next/headers";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function getToken() {
  const jar = await cookies();
  return jar.get("ss_access")?.value;
}

type Ctx = { params: Promise<{ id: string }> };

export async function GET(req: NextRequest, { params }: Ctx) {
  const token = await getToken();
  if (!token) return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
  const { id } = await params;
  const strategy = req.nextUrl.searchParams.get("strategy") ?? "mobile";
  const limit = req.nextUrl.searchParams.get("limit") ?? "30";
  const upstream = await fetch(
    `${API_BASE}/api/v1/websites/${id}/performance/?strategy=${strategy}&limit=${limit}`,
    { headers: { Authorization: `Bearer ${token}` } }
  );
  const envelope = await upstream.json().catch(() => ({}));
  return NextResponse.json(envelope?.data ?? envelope, { status: upstream.status });
}
