import { NextRequest } from "next/server";
import { proxyToApi } from "@/lib/api-proxy";

// Share a whole folder with people.
export async function POST(req: NextRequest, ctx: { params: Promise<{ folderId: string }> }) {
  const { folderId } = await ctx.params;
  return proxyToApi(`/api/v1/credentials/folders/${folderId}/members/`, {
    method: "POST",
    body: await req.json(),
  });
}
