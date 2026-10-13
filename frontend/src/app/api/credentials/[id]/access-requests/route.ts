import { NextRequest } from "next/server";
import { proxyToApi } from "@/lib/api-proxy";

export async function POST(req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  return proxyToApi(`/api/v1/credentials/${id}/access-requests/`, {
    method: "POST",
    body: await req.json(),
  });
}
