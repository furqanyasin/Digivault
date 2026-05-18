import { NextRequest, NextResponse } from "next/server";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function GET(_req: NextRequest, { params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;

  const upstream = await fetch(`${API_BASE}/api/v1/public/status/${slug}/`, {
    next: { revalidate: 10 },
  });

  if (upstream.status === 404) {
    return NextResponse.json({ detail: "Not found" }, { status: 404 });
  }

  const envelope = await upstream.json().catch(() => ({}));
  const data = envelope?.data ?? envelope;

  const response = NextResponse.json(data, { status: upstream.status });

  // Honour allow_indexing from the page data
  if (!data?.allow_indexing) {
    response.headers.set("X-Robots-Tag", "noindex, nofollow");
  }

  return response;
}
