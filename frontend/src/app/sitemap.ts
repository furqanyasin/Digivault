import type { MetadataRoute } from "next";
import { FEATURES, SITE_URL, TOOLS } from "@/lib/marketing/content";

// Public website pages only. The dashboard is behind a login and disallowed
// in robots.ts.
export default function sitemap(): MetadataRoute.Sitemap {
  const now = new Date();
  const page = (path: string, priority: number, changeFrequency: "weekly" | "monthly" | "yearly" = "monthly") => ({
    url: `${SITE_URL}${path}`,
    lastModified: now,
    changeFrequency,
    priority,
  });
  return [
    page("", 1, "weekly"),
    page("/pricing", 0.9),
    page("/features", 0.8),
    ...FEATURES.map((f) => page(`/features/${f.slug}`, 0.8)),
    page("/tools", 0.8),
    ...TOOLS.map((t) => page(`/tools/${t.slug}`, 0.8)),
    page("/signup", 0.6),
    page("/security", 0.5),
    page("/contact", 0.5),
    page("/privacy", 0.2, "yearly"),
    page("/terms", 0.2, "yearly"),
  ];
}
