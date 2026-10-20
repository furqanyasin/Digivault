import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// /api/password-reset is public because the anonymous forgot-password and
// reset-password pages call it; it has no authenticated sub-routes.
// /bot is the allowlist page our User-Agent links to; the client's firewall
// admin who opens it has no login here.
const PUBLIC_PATHS = ["/login", "/register", "/signup", "/verify-email", "/forgot-password", "/reset-password", "/2fa/", "/status/", "/bot", "/api/auth", "/api/password-reset"];

// The public website. Each entry matches the path itself and anything below it
// ("/tools" covers "/tools/ssl-checker"), never a longer word that starts the
// same way. "/" is matched exactly, or every route would be public.
const MARKETING_PATHS = ["/features", "/tools", "/pricing", "/contact", "/security", "/privacy", "/terms"];
const PUBLIC_FILES = ["/robots.txt", "/sitemap.xml", "/icon.svg", "/stacksmonitor-icon.svg", "/opengraph-image"];

function isPublic(pathname: string): boolean {
  if (pathname === "/") return true;
  if (PUBLIC_FILES.some((f) => pathname === f || pathname.startsWith(`${f}?`) || pathname.startsWith(`${f}/`))) return true;
  if (MARKETING_PATHS.some((p) => pathname === p || pathname.startsWith(`${p}/`))) return true;
  return PUBLIC_PATHS.some((p) => pathname.startsWith(p));
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;

  if (isPublic(pathname)) return NextResponse.next();

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
        const newRefresh: string | undefined = body?.data?.refresh ?? body?.refresh;

        if (newAccess) {
          const secure = process.env.NODE_ENV === "production";
          // Forward the refreshed token on the CURRENT request so this render's
          // server components see it. Without this, the page that triggered the
          // refresh still reads the old (missing) cookie, so every token-backed
          // fetch 401s and the page renders empty until a manual reload.
          request.cookies.set("ss_access", newAccess);
          const res = NextResponse.next({ request });
          res.cookies.set("ss_access", newAccess, {
            httpOnly: true,
            secure,
            sameSite: "lax",
            path: "/",
            maxAge: 60 * 5,
          });
          // Refresh-token rotation returns a fresh refresh token; persist it or
          // the next refresh fails against the rotated/blacklisted old one.
          if (newRefresh) {
            res.cookies.set("ss_refresh", newRefresh, {
              httpOnly: true,
              secure,
              sameSite: "lax",
              path: "/",
              maxAge: 60 * 60 * 24 * 7,
            });
          }
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
