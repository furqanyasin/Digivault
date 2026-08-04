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
 *  - Light aqua (#1baf7a, 2.82:1) and amber (#f59e0b, 2.15:1) sit below 3:1, so
 *    the relief rule applies: any chart using them ships visible labels or a
 *    legend carrying the numbers. That is not dismissable.
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
  status: { good: "#10b981", warning: "#f59e0b", critical: "#ef4444", neutral: "#94a3b8" },
  surface: "#ffffff",
  grid: "#e5e7eb",
  muted: "#6b7280",
  ink: "#111827",
  tooltipBg: "#ffffff",
  tooltipInk: "#111827",
};

const DARK: ChartTokens = {
  // Same three hues, re-stepped for the dark surface — not an automatic flip.
  series: ["#3987e5", "#d95926", "#199e70"],
  status: { good: "#10b981", warning: "#f59e0b", critical: "#ef4444", neutral: "#94a3b8" },
  surface: "#121219",
  grid: "#2a2a33",
  muted: "#9ca3af",
  ink: "#f3f4f6",
  tooltipBg: "#1c1c24",
  tooltipInk: "#f3f4f6",
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

/** Health-score bands. Mirrors Website.HEALTH_* on the backend. */
export const HEALTH_BANDS = [
  { key: "healthy", label: "Healthy", min: 85, tone: "good" as const },
  { key: "warning", label: "Warning", min: 60, tone: "warning" as const },
  { key: "critical", label: "Critical", min: 0, tone: "critical" as const },
] as const;

export function healthBand(score: number): "healthy" | "warning" | "critical" {
  if (score >= 85) return "healthy";
  if (score >= 60) return "warning";
  return "critical";
}

/** Chart.js options shared by every chart here: recessive chrome, solid
 *  hairline grid (never dashed), tooltips that enhance rather than gate. */
export function baseOptions(t: ChartTokens) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: "index" as const, intersect: false },
    plugins: {
      legend: { display: false }, // legends are rendered as real HTML instead
      tooltip: {
        backgroundColor: t.tooltipBg,
        titleColor: t.tooltipInk,
        bodyColor: t.tooltipInk,
        borderColor: t.grid,
        borderWidth: 1,
        padding: 10,
        cornerRadius: 8,
        displayColors: true,
        boxWidth: 8,
        boxHeight: 8,
        usePointStyle: true,
      },
    },
  };
}
