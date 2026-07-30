"use client";

import { useSyncExternalStore } from "react";
import { useTheme } from "next-themes";
import { chartTokens, type ChartTokens } from "@/lib/chart-theme";

const noop = () => () => {};

/** True only after hydration has finished.
 *
 *  `getServerSnapshot` is also what React uses for the hydrating render, so this
 *  reads false on the server AND on the client's first pass, then true from the
 *  next render on. That ordering is the whole point: it is what keeps the two
 *  renders identical.
 *
 *  A `useState(false)` + `useEffect(() => setMounted(true))` latch does the same
 *  job but trips react-hooks/set-state-in-effect and costs an extra render;
 *  deriving it from `resolvedTheme` instead is worse still — next-themes has
 *  already resolved the theme by the time the client hydrates, so the client's
 *  first render would draw a canvas where the server sent a placeholder and
 *  React throws a hydration mismatch (#418).
 */
function useHydrated(): boolean {
  return useSyncExternalStore(
    noop,
    () => true,
    () => false
  );
}

/** Resolved chart tokens for the active theme.
 *
 *  `mounted` guards the first paint: next-themes cannot know the resolved theme
 *  server-side, so painting a canvas before hydration would use light-mode
 *  colours on a dark card and then repaint. Callers render a fixed-height
 *  placeholder while it is false, which also stops the card from jumping.
 */
export function useChartTheme(): { tokens: ChartTokens; isDark: boolean; mounted: boolean } {
  const { resolvedTheme } = useTheme();
  const hydrated = useHydrated();
  const isDark = resolvedTheme === "dark";
  return { tokens: chartTokens(isDark), isDark, mounted: hydrated };
}
