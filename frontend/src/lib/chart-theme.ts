/** Shared chart tokens for the dashboard.
 *
 * Every value here was checked with the dataviz validator against this app's
 * REAL card surfaces (light #ffffff, dark #121219) — not eyeballed. Re-run it
 * before changing any hex:
 *
 *   node <dataviz>/scripts/validate_palette.js "<hex,hex,…>" \
 *        --mode light --surface "#ffffff" --pairs all
 *
 * Findings that constrain what's below:
 *  - Brand violet (#6d42e5) FAILS the dark lightness band (0.677 vs a 0.67
 *    ceiling), so series colours are stepped per mode instead of reusing it.
 *  - Categorical slots 1–3 pass all-pairs in both modes; a 4th would put yellow
 *    beside orange and fail. Three series is the cap here — fold to "Other".
 *  - Tailwind's 500/400 status steps pass every gate; the 600 steps FAIL the
 *    normal-vision floor (red-600 vs amber-600 ΔE 14.4). Keep the 500s.
 *  - Light aqua (#1baf7a, 2.82:1) and amber (#ee9e19, 2.20:1) sit below 3:1, so
 *    the relief rule applies: any chart using them ships visible labels or a
 *    legend carrying the numbers. That is not dismissable.
 *
 * `status` and the surface/grid/ink values are now the 500/400 steps of the
 * OKLCH ramps in globals.css, so a chart's "critical" is the same colour as the
 * badge beside it. Pairwise OKLab separation of the four light status colours
 * is 0.133–0.313 (floor ~0.10); every dark step clears 6.4:1 on the dark card.
 * `series` is untouched — those are categorical identity slots, not state, and
 * the brand indigo still fails the dark lightness band noted above.
 */

export interface ChartTokens {
  /** Ordered categorical slots. Identity, never magnitude. Max three. */
  series: [string, string, string];
  /** Reserved for state. Never reuse these as a series colour. */
  status: { good: string; warning: string; critical: string; neutral: string };
  surface: string;
  grid: string;
  muted: string;
  ink: string;
  tooltipBg: string;
  tooltipInk: string;
}

const LIGHT: ChartTokens = {
  series: ["#2a78d6", "#eb6834", "#1baf7a"],
  status: { good: "#28a98a", warning: "#ee9e19", critical: "#eb4244", neutral: "#9c9dac" },
  surface: "#ffffff",
  grid: "#e5e5ee",
  muted: "#6e6f7c",
  ink: "#161620",
  tooltipBg: "#ffffff",
  tooltipInk: "#161620",
};

const DARK: ChartTokens = {
  // Same three hues, re-stepped for the dark surface — not an automatic flip.
  series: ["#3987e5", "#d95926", "#199e70"],
  // Status used to be one set of hexes shared by both modes, which broke the
  // rule stated for `series` one line above. Stepped per mode now — which is
  // why `useChartTheme` has to report light until hydration finishes, for the
  // two charts that put a status colour into real SSR'd HTML.
  status: { good: "#54c3a4", warning: "#faaf44", critical: "#ff706a", neutral: "#9c9dac" },
  surface: "#181921",
  grid: "#2c2c36",
  muted: "#a7a8b6",
  ink: "#f3f3f6",
  tooltipBg: "#23242d",
  tooltipInk: "#f3f3f6",
};

export function chartTokens(isDark: boolean): ChartTokens {
  return isDark ? DARK : LIGHT;
}

/** Hex → rgba, for area washes. The spec is a ~10% wash, never a solid block. */
export function alpha(hex: string, a: number): string {
  const h = hex.replace("#", "");
  const n = parseInt(h.length === 3 ? h.split("").map((c) => c + c).join("") : h, 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
}

export function healthBand(score: number): "healthy" | "warning" | "critical" {
  if (score >= 85) return "healthy";
  if (score >= 60) return "warning";
  return "critical";
}
