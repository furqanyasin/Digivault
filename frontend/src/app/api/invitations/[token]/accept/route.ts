import { NextRequest, NextResponse } from "next/server";
import { cookies } from "next/headers";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Ctx = { params: Promise<{ token: string }> };

export async function POST(req: NextRequest, { params }: Ctx) {
  const jar = await cookies();
  const accessToken = jar.get("ss_access")?.value;
  const { token } = await params;

  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (accessToken) headers["Authorization"] = `Bearer ${accessToken}`;

  const body = await req.json().catch(() => ({}));
  const upstream = await fetch(`${API_BASE}/api/v1/auth/invitations/${token}/accept/`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
  const data = await upstream.json().catch(() => ({}));
  return NextResponse.json(data, { status: upstream.status });
}
