import { NextRequest, NextResponse } from "next/server";
import { cookies } from "next/headers";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// A 404 here is a normal state, not an error: it means no screenshot has been
// captured for this page yet, and the dashboard falls back to the live iframe.
export async function GET(req: NextRequest) {
  const jar = await cookies();
  const token = jar.get("ss_access")?.value;
  if (!token) return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });

  const query = req.nextUrl.searchParams.toString();
  const upstream = await fetch(`${API_BASE}/api/v1/heatmap/snapshot/${query ? `?${query}` : ""}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const envelope = await upstream.json();
  return NextResponse.json(envelope?.data ?? envelope, { status: upstream.status });
}
