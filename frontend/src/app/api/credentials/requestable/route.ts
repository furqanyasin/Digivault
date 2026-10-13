import { NextRequest } from "next/server";
import { proxyToApi } from "@/lib/api-proxy";

// Team credentials the caller cannot see — metadata only, for "Request access".
export async function GET(req: NextRequest) {
  const q = req.nextUrl.searchParams.get("q") ?? "";
  return proxyToApi(`/api/v1/credentials/requestable/?page_size=50&q=${encodeURIComponent(q)}`);
}
