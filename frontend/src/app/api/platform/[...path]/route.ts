import { NextRequest, NextResponse } from "next/server";
import { proxyToApi } from "@/lib/api-proxy";

type Ctx = { params: Promise<{ path: string[] }> };

// Platform owner endpoints. The backend refuses anyone who is not a
// superuser; this only forwards. Segments are restricted so a crafted path
// cannot walk to another API route.
async function target(req: NextRequest, { params }: Ctx) {
  const { path } = await params;
  if (!path.length || path.some((p) => !/^[a-z0-9-]+$/i.test(p))) return null;
  const q = req.nextUrl.searchParams.get("q");
  return `/api/v1/platform/${path.join("/")}/${q ? `?q=${encodeURIComponent(q)}` : ""}`;
}

export async function GET(req: NextRequest, ctx: Ctx) {
  const url = await target(req, ctx);
  if (!url) return NextResponse.json({ detail: "Not found" }, { status: 404 });
  return proxyToApi(url);
}

export async function PATCH(req: NextRequest, ctx: Ctx) {
  const url = await target(req, ctx);
  if (!url) return NextResponse.json({ detail: "Not found" }, { status: 404 });
  return proxyToApi(url, { method: "PATCH", body: await req.json().catch(() => ({})) });
}
