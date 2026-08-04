import Link from "next/link";
import { ChevronRight } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { AnimatedValue } from "./animated-value";

interface Props {
  label: string;
  value: number;
  caption: string;
  /** Colours the caption when it reports a problem rather than a fact. */
  captionTone?: "muted" | "critical" | "good";
  href: string;
  icon: React.ReactNode;
}

/** A one-line summary of a section that has no chart on this page.
 *
 *  Deliberately smaller and quieter than the chart cards: these exist so the
 *  dashboard reflects the whole product (clients, vault, team) rather than
 *  restating the same website metrics, and they hand off to the section that owns
 *  the detail. No sparkline — a trend here would be noise, and a second reading
 *  of a number a card below already owns is exactly what made the page feel
 *  padded.
 */
export function SummaryChunk({ label, value, caption, captionTone = "muted", href, icon }: Props) {
  return (
    <Link href={href} className="group">
      <Card className="h-full transition-all hover:border-primary/40 hover:shadow-sm">
        <CardContent className="flex items-center gap-3 p-4">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground group-hover:bg-primary/10 group-hover:text-primary">
            {icon}
          </span>
          {/* Label block takes the slack so the number can sit hard right —
              left-bunched content is what left these tiles looking half-empty. */}
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium leading-tight">{label}</p>
            <p
              className={`truncate text-[11px] ${
                captionTone === "critical"
                  ? "font-medium text-red-600"
                  : captionTone === "good"
                    ? "font-medium text-emerald-600"
                    : "text-muted-foreground"
              }`}
            >
              {caption}
            </p>
          </div>
          <span className="shrink-0 text-2xl font-semibold leading-none tabular-nums">
            <AnimatedValue value={value} />
          </span>
          <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground/30 transition-colors group-hover:text-primary" />
        </CardContent>
      </Card>
    </Link>
  );
}
