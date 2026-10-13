import path from "node:path";
import { fileURLToPath } from "node:url";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Pin Turbopack's root to frontend/. Without it, root inference walks up to
  // the repo root, which makes `@import "tailwindcss"` resolve against a
  // directory with no node_modules and makes the dev server watch the Django
  // side of the repo (.venv, media, .git) until it runs out of memory.
  turbopack: {
    root: path.dirname(fileURLToPath(import.meta.url)),
  },
};

export default nextConfig;
