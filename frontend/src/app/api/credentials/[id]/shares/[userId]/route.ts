import { NextRequest, NextResponse } from "next/server";
import { cookies } from "next/headers";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function DELETE(
  _req: NextRequest,
  ctx: { params: Promise<{ id: string; userId: string }> }
) {
  const { id, userId } = await ctx.params;
  const jar = await cookies();
  const token = jar.get("ss_access")?.value;
  if (!token) return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });

  const upstream = await fetch(
    `${API_BASE}/api/v1/credentials/${id}/shares/${userId}/`,
    { method: "DELETE", headers: { Authorization: `Bearer ${token}` } }
  );
  if (!upstream.ok) {
    return NextResponse.json({ detail: "Failed to revoke" }, { status: upstream.status });
  }
  return new NextResponse(null, { status: 204 });
}
