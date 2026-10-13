import { NextRequest, NextResponse } from "next/server";
import { cookies } from "next/headers";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// Streams the snapshot PNG. Snapshots are pictures of clients' pages, so the
// backend serves them through a team-scoped view rather than MEDIA_URL; the
// browser cannot attach the bearer token to an <img src>, so it comes through
// here instead.
export async function GET(req: NextRequest) {
  const jar = await cookies();
  const token = jar.get("ss_access")?.value;
  if (!token) return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });

  const id = req.nextUrl.searchParams.get("id");
  if (!id) return NextResponse.json({ detail: "id is required" }, { status: 400 });

  const upstream = await fetch(`${API_BASE}/api/v1/heatmap/snapshots/${id}/image/`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!upstream.ok || !upstream.body) {
    return NextResponse.json({ detail: "Not found" }, { status: upstream.status || 404 });
  }
  return new NextResponse(upstream.body, {
    status: 200,
    headers: {
      "Content-Type": "image/png",
      // A recapture reuses the same snapshot row, so the id alone is NOT a
      // version. Callers append `?v=<captured_at>` to bust this; without that
      // param a refreshed screenshot would stay hidden for the full max-age.
      "Cache-Control": "private, max-age=3600",
    },
  });
}
