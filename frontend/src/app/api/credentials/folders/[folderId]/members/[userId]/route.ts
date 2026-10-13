import { NextRequest } from "next/server";
import { proxyToApi } from "@/lib/api-proxy";

export async function DELETE(
  _req: NextRequest,
  ctx: { params: Promise<{ folderId: string; userId: string }> },
) {
  const { folderId, userId } = await ctx.params;
  return proxyToApi(`/api/v1/credentials/folders/${folderId}/members/${userId}/`, { method: "DELETE" });
}
