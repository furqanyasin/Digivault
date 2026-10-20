"use client";

import { ThemeProvider as NextThemes } from "next-themes";

// Light / dark / system for every page, website and dashboard alike. Kept
// apart from `Providers` so marketing pages ship without react-query.
export function ThemeProvider({ children }: { children: React.ReactNode }) {
  return (
    <NextThemes attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
      {children}
    </NextThemes>
  );
}
