import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

// Status variants read from the paired status tokens rather than raw palette
// steps. `bg-emerald-100 text-emerald-800` was a light-mode pair hard-coded
// into a themed component: on a dark card it stayed a bright mint chip, the one
// thing on the surface still lit for a white page. The `-surface` /
// `-foreground` pairs swap with the theme and are contrast-checked in both.
const badgeVariants = cva(
  "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold tracking-tight transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2",
  {
    variants: {
      variant: {
        default: "border-transparent bg-primary text-primary-foreground hover:bg-primary/90",
        secondary: "border-transparent bg-secondary text-secondary-foreground hover:bg-secondary/80",
        /* Solid — reserved for the badge that has to outrank every other pill
           on the screen ("3 urgent"). Anything merely bad wants `danger`. */
        destructive: "border-transparent bg-destructive text-destructive-foreground",
        outline: "text-foreground",
        success: "border-transparent bg-success-surface text-success-foreground",
        warning: "border-transparent bg-warning-surface text-warning-foreground",
        danger: "border-transparent bg-danger-surface text-danger-foreground",
        info: "border-transparent bg-info-surface text-info-foreground",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { Badge, badgeVariants };
