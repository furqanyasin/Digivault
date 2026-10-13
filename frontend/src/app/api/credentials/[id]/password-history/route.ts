import { NextRequest } from "next/server";
import { proxyToApi } from "@/lib/api-proxy";

// Retired passwords, newest first — metadata only.
export async function GET(_req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  return proxyToApi(`/api/v1/credentials/${id}/password-history/`);
}
