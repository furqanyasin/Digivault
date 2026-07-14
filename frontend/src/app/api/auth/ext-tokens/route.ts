import { NextResponse } from "next/server";
import { cookies } from "next/headers";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// Hands the current web session's JWTs to same-origin page JS so it can sync
// them into the browser extension (see ExtensionAuthBridge). The tokens live in
// HttpOnly cookies the page can't read directly; this route reads them
// server-side and returns them only to an authenticated same-origin caller.
export async function GET() {
  const jar = await cookies();
  const access = jar.get("ss_access")?.value;
  const refresh = jar.get("ss_refresh")?.value;
  if (!access || !refresh) {
    return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  }

  let email = "";
  try {
    const res = await fetch(`${API_BASE}/api/v1/auth/me/`, {
      headers: { Authorization: `Bearer ${access}` },
    });
    if (res.ok) {
      const envelope = await res.json();
      const me = envelope?.data ?? envelope;
      email = me?.email ?? "";
    }
  } catch {
    // email is a nicety; sync still works without it
  }

  return NextResponse.json({ access, refresh, email });
}
