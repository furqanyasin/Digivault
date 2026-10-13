import { NextRequest } from "next/server";
import { proxyToApi } from "@/lib/api-proxy";

type Ctx = { params: Promise<{ folderId: string }> };

export async function PATCH(req: NextRequest, ctx: Ctx) {
  const { folderId } = await ctx.params;
  return proxyToApi(`/api/v1/credentials/folders/${folderId}/`, { method: "PATCH", body: await req.json() });
}

export async function DELETE(_req: NextRequest, ctx: Ctx) {
  const { folderId } = await ctx.params;
  return proxyToApi(`/api/v1/credentials/folders/${folderId}/`, { method: "DELETE" });
}
