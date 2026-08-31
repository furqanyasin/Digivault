import { NextRequest, NextResponse } from "next/server";
import { cookies } from "next/headers";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function GET(req: NextRequest) {
  const jar = await cookies();
  const token = jar.get("ss_access")?.value;
  if (!token) return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });

  const query = req.nextUrl.searchParams.toString();
  const upstream = await fetch(`${API_BASE}/api/v1/heatmap/summary/${query ? `?${query}` : ""}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const envelope = await upstream.json();
  return NextResponse.json(envelope?.data ?? envelope, { status: upstream.status });
}
