import { NextRequest } from "next/server";
import { proxyToApi } from "@/lib/api-proxy";

// scope=to_me (pending requests you can decide) or scope=mine (your own).
export async function GET(req: NextRequest) {
  const scope = req.nextUrl.searchParams.get("scope") === "mine" ? "mine" : "to_me";
  return proxyToApi(`/api/v1/credentials/access-requests/?scope=${scope}`);
}
