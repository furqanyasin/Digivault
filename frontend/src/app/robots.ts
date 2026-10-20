import type { MetadataRoute } from "next";
import { SITE_URL } from "@/lib/marketing/content";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      allow: "/",
      disallow: [
        "/api/", "/admin/", "/dashboard", "/clients", "/websites", "/monitors", "/renewals",
        "/alerts", "/credentials", "/team", "/logs", "/heatmap", "/settings", "/account",
        "/status-pages", "/platform", "/invite/", "/2fa/", "/first-password", "/reset-password",
        "/verify-email", "/auth/",
      ],
    },
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}
