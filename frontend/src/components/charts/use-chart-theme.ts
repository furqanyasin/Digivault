"use client";

import { useEffect, useState } from "react";
import { useTheme } from "next-themes";
import { chartTokens, type ChartTokens } from "@/lib/chart-theme";

/** Resolved chart tokens for the active theme.
 *
 *  `mounted` guards the first paint: next-themes can't know the resolved theme
 *  until it runs on the client, so rendering a canvas before then would paint
 *  light-mode colours onto a dark card and then repaint. Callers render a
 *  fixed-height placeholder while it's false, which also keeps the card from
 *  jumping.
 */
export function useChartTheme(): { tokens: ChartTokens; isDark: boolean; mounted: boolean } {
  const { resolvedTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  const isDark = resolvedTheme === "dark";
  return { tokens: chartTokens(isDark), isDark, mounted };
}
