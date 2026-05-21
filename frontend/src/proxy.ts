import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const PUBLIC_PATHS = ["/login", "/register", "/forgot-password", "/reset-password", "/2fa/", "/status/", "/api/auth", "/api/public"];

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;

  if (PUBLIC_PATHS.some((p) => pathname.startsWith(p))) return NextResponse.next();

  const access = request.cookies.get("ss_access")?.value;
  if (access) return NextResponse.next();

  // Access token missing — attempt a silent refresh before redirecting to login.
  const refresh = request.cookies.get("ss_refresh")?.value;
  if (refresh) {
    try {
      const upstream = await fetch(`${API_BASE}/api/v1/auth/token/refresh/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh }),
      });

      if (upstream.ok) {
        const body = await upstream.json();
        const newAccess: string | undefined = body?.data?.access ?? body?.access;

        if (newAccess) {
          const res = NextResponse.next();
          res.cookies.set("ss_access", newAccess, {
            httpOnly: true,
            secure: process.env.NODE_ENV === "production",
            sameSite: "lax",
            path: "/",
            maxAge: 60 * 5,
          });
          return res;
        }
      }
    } catch {
      // Network error — fall through to login redirect.
    }
  }

  // No valid token — send to login.
  // API routes: return 401 so client-side callers handle it gracefully.
  if (pathname.startsWith("/api/")) {
    return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
  }
  const loginUrl = new URL("/login", request.url);
  loginUrl.searchParams.set("next", pathname);
  return NextResponse.redirect(loginUrl);
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|api/s.js).*)"],
};
