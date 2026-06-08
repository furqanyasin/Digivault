import { NextRequest, NextResponse } from "next/server";
import { cookies } from "next/headers";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function GET(
  _req: NextRequest,
  ctx: { params: Promise<{ id: string }> }
) {
  const { id } = await ctx.params;
  const jar = await cookies();
  const token = jar.get("ss_access")?.value;
  if (!token) return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });

  const upstream = await fetch(`${API_BASE}/api/v1/reports/${id}/download/`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!upstream.ok) {
    return NextResponse.json({ detail: "Not found" }, { status: upstream.status });
  }

  const data = await upstream.arrayBuffer();
  return new NextResponse(data, {
    status: 200,
    headers: {
      "Content-Type": upstream.headers.get("Content-Type") ?? "application/octet-stream",
      "Content-Disposition":
        upstream.headers.get("Content-Disposition") ?? 'attachment; filename="report"',
    },
  });
}
