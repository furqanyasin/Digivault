import { NextResponse } from "next/server";
import { cookies } from "next/headers";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/**
 * Forward a route handler's request to the Django API with the session's
 * access token, and unwrap the `{data, errors, meta}` envelope the way every
 * hand-written proxy here does. An error response keeps the envelope, so the
 * caller reads `errors[0].message` (or `detail`).
 *
 * For new routes only — the older proxies inline the same few lines and are
 * left as they are.
 */
export async function proxyToApi(
  path: string,
  init: { method?: string; body?: unknown } = {},
): Promise<NextResponse> {
  const jar = await cookies();
  const token = jar.get("ss_access")?.value;
  if (!token) return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });

  const upstream = await fetch(`${API_BASE}${path}`, {
    method: init.method ?? "GET",
    headers: {
      Authorization: `Bearer ${token}`,
      ...(init.body !== undefined ? { "Content-Type": "application/json" } : {}),
    },
    body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
    cache: "no-store",
  });
  if (upstream.status === 204) return new NextResponse(null, { status: 204 });
  const envelope = await upstream.json().catch(() => ({}));
  return NextResponse.json(envelope?.data ?? envelope, { status: upstream.status });
}
