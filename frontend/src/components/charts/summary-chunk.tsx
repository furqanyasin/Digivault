import Link from "next/link";
import { Card, CardContent } from "@/components/ui/card";
import { AnimatedValue } from "./animated-value";

interface Props {
  label: string;
  value: number;
  caption: string;
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
export function SummaryChunk({ label, value, caption, href, icon }: Props) {
  return (
    <Link href={href} className="group">
      <Card className="h-full transition-all hover:border-primary/40 hover:shadow-sm">
        <CardContent className="flex items-center gap-3 p-4">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground group-hover:bg-primary/10 group-hover:text-primary">
            {icon}
          </span>
          <div className="min-w-0">
            <p className="text-xl font-semibold leading-none">
              <AnimatedValue value={value} />
            </p>
            <p className="mt-1 truncate text-xs font-medium">{label}</p>
            <p className="truncate text-[11px] text-muted-foreground">{caption}</p>
          </div>
        </CardContent>
      </Card>
    </Link>
  );
}
