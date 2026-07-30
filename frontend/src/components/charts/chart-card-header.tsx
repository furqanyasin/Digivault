import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { AnimatedValue } from "./animated-value";

interface Props {
  title: string;
  subtitle: string;
  /** The headline figure this card owns. */
  value: number;
  suffix?: string;
  decimals?: number;
  /** Short line under the figure — e.g. "2 critical". */
  caption?: string;
  captionTone?: "muted" | "critical" | "good";
  /** Where the detail lives. */
  href?: string;
  linkLabel?: string;
  /** Rendered at the far right of the header row (e.g. an action button). */
  action?: React.ReactNode;
}

/** Title, subtitle and the card's headline number in one row.
 *
 *  The number lives HERE rather than in a separate KPI tile above: a tile plus a
 *  chart for the same metric said everything twice, which is what made the
 *  dashboard feel padded. Each card now owns its figure and shows the shape
 *  behind it.
 */
export function ChartCardHeader({
  title, subtitle, value, suffix, decimals, caption, captionTone = "muted",
  href, linkLabel = "Open", action,
}: Props) {
  return (
    <div className="mb-4 flex items-start justify-between gap-3">
      <div className="min-w-0">
        <h2 className="text-sm font-semibold">{title}</h2>
        <p className="mt-0.5 text-xs text-muted-foreground">{subtitle}</p>
        <p className="mt-2 text-3xl font-semibold leading-none">
          <AnimatedValue value={value} suffix={suffix} decimals={decimals} />
        </p>
        {caption && (
          <p
            className={`mt-1 text-xs ${
              captionTone === "critical"
                ? "font-semibold text-red-600"
                : captionTone === "good"
                  ? "font-medium text-emerald-600"
                  : "text-muted-foreground"
            }`}
          >
            {caption}
          </p>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {action}
        {href && (
          <Link
            href={href}
            className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground hover:underline"
          >
            {linkLabel}
            <ArrowRight className="h-3 w-3" />
          </Link>
        )}
      </div>
    </div>
  );
}
