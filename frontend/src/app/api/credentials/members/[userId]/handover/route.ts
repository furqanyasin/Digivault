import { NextRequest } from "next/server";
import { proxyToApi } from "@/lib/api-proxy";

export async function POST(req: NextRequest, ctx: { params: Promise<{ userId: string }> }) {
  const { userId } = await ctx.params;
  return proxyToApi(`/api/v1/credentials/members/${userId}/handover/`, {
    method: "POST",
    body: await req.json(),
  });
}
