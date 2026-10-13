import { NextRequest, NextResponse } from "next/server";
import { cookies } from "next/headers";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Ctx = { params: Promise<{ id: string }> };

/** GET returns the current WP Connect snippet (for a re-paste); POST generates
 *  a new secret and returns the new snippet. Both are manager-only upstream. */
async function forward(method: "GET" | "POST", { params }: Ctx) {
  const jar = await cookies();
  const token = jar.get("ss_access")?.value;
  if (!token) return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
  const { id } = await params;
  const upstream = await fetch(`${API_BASE}/api/v1/websites/${id}/wp-sso-secret/`, {
    method,
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    cache: "no-store",
  });
  const envelope = await upstream.json().catch(() => ({}));
  return NextResponse.json(envelope?.data ?? envelope, { status: upstream.status });
}

export async function GET(_req: NextRequest, ctx: Ctx) {
  return forward("GET", ctx);
}

export async function POST(_req: NextRequest, ctx: Ctx) {
  return forward("POST", ctx);
}
