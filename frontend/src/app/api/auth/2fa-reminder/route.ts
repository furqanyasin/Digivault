import { proxyToApi } from "@/lib/api-proxy";

// POST — hide the enable-2FA banner for 24 hours.
export async function POST() {
  return proxyToApi("/api/v1/auth/me/2fa-reminder/dismiss/", { method: "POST", body: {} });
}
