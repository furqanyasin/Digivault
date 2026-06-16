import { NextRequest, NextResponse } from "next/server";
import { cookies } from "next/headers";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function token() {
  const jar = await cookies();
  return jar.get("ss_access")?.value;
}

export async function GET(_req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const t = await token();
  if (!t) return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
  const upstream = await fetch(`${API_BASE}/api/v1/websites/${id}/seo/`, {
    headers: { Authorization: `Bearer ${t}` },
  });
  const envelope = await upstream.json().catch(() => ({}));
  return NextResponse.json(envelope?.data ?? envelope, { status: upstream.status });
}

export async function POST(_req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const t = await token();
  if (!t) return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
  const upstream = await fetch(`${API_BASE}/api/v1/websites/${id}/seo/`, {
    method: "POST",
    headers: { Authorization: `Bearer ${t}`, "Content-Type": "application/json" },
  });
  const envelope = await upstream.json().catch(() => ({}));
  return NextResponse.json(envelope?.data ?? envelope, { status: upstream.status });
}

export async function PATCH(req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const t = await token();
  if (!t) return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
  const body = await req.json();
  const upstream = await fetch(`${API_BASE}/api/v1/websites/${id}/seo/`, {
    method: "PATCH",
    headers: { Authorization: `Bearer ${t}`, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const envelope = await upstream.json().catch(() => ({}));
  return NextResponse.json(envelope?.data ?? envelope, { status: upstream.status });
}
