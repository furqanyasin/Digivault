import { NextRequest } from "next/server";
import { proxyToApi } from "@/lib/api-proxy";

export async function POST(
  _req: NextRequest,
  ctx: { params: Promise<{ id: string; entryId: string }> },
) {
  const { id, entryId } = await ctx.params;
  return proxyToApi(`/api/v1/credentials/${id}/password-history/${entryId}/reveal/`, {
    method: "POST",
  });
}
