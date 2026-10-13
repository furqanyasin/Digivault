import { NextRequest } from "next/server";
import { proxyToApi } from "@/lib/api-proxy";

// The team's vault folders (with what the caller can see in each).
export async function GET() {
  return proxyToApi("/api/v1/credentials/folders/");
}

export async function POST(req: NextRequest) {
  return proxyToApi("/api/v1/credentials/folders/", { method: "POST", body: await req.json() });
}
