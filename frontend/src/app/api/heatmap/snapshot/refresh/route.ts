import { NextRequest, NextResponse } from "next/server";
import { cookies } from "next/headers";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function POST(req: NextRequest) {
  const jar = await cookies();
  const token = jar.get("ss_access")?.value;
  if (!token) return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });

  const body = await req.text();
  const upstream = await fetch(`${API_BASE}/api/v1/heatmap/snapshot/refresh/`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body,
  });
  // 202 carries no body; anything else may carry an error envelope.
  if (upstream.status === 202) return new NextResponse(null, { status: 202 });
  const envelope = await upstream.json().catch(() => null);
  return NextResponse.json(envelope?.data ?? envelope ?? {}, { status: upstream.status });
}
