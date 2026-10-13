import { NextRequest } from "next/server";
import { proxyToApi } from "@/lib/api-proxy";

export async function POST(req: NextRequest, ctx: { params: Promise<{ requestId: string }> }) {
  const { requestId } = await ctx.params;
  return proxyToApi(`/api/v1/credentials/access-requests/${requestId}/decide/`, {
    method: "POST",
    body: await req.json(),
  });
}
