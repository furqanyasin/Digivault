"use client";

import { useState } from "react";
import Link from "next/link";
import { Check } from "lucide-react";
import type { Plan } from "@/lib/marketing/content";

// The only client code on the pricing page: the monthly / yearly switch.
export function PricingCards({ plans }: { plans: Plan[] }) {
  const [yearly, setYearly] = useState(false);

  return (
    <div>
      <div className="flex items-center justify-center gap-3 text-small font-medium">
        <span className={yearly ? "text-[var(--ds-text-muted)]" : "text-[var(--ds-heading)]"}>Monthly</span>
        <button
          type="button"
          role="switch"
          aria-checked={yearly}
          aria-label="Bill yearly"
          onClick={() => setYearly((v) => !v)}
          className={`relative h-7 w-12 rounded-full transition-colors ${yearly ? "bg-[var(--primary)]" : "bg-[var(--input)]"}`}
        >
          <span className={`absolute top-1 h-5 w-5 rounded-full bg-white shadow transition-transform ${yearly ? "translate-x-6" : "translate-x-1"}`} />
        </button>
        <span className={yearly ? "text-[var(--ds-heading)]" : "text-[var(--ds-text-muted)]"}>
          Yearly <span className="ml-1 rounded-full bg-emerald-100 px-2 py-0.5 text-caption font-semibold text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300">2 months free</span>
        </span>
      </div>

      <div className="mt-10 grid gap-5 md:grid-cols-2 xl:grid-cols-4">
        {plans.map((p) => {
          const price = p.monthly === null ? null : yearly ? Math.round((p.monthly * 10) / 12) : p.monthly;
          return (
            <div
              key={p.key}
              className={`ds-card relative flex flex-col ${p.popular ? "border-[var(--primary)] ring-2 ring-[var(--primary)]" : ""}`}
            >
              {p.popular && (
                <span className="absolute -top-3 left-1/2 -translate-x-1/2 rounded-full bg-[var(--primary)] px-3 py-1 text-caption font-semibold text-[var(--primary-foreground)]">
                  Most popular
                </span>
              )}
              <h3 className="ds-h4">{p.name}</h3>
              <p className="mt-2 min-h-[3rem] text-small text-[var(--ds-text-muted)]">{p.blurb}</p>
              <p className="mt-5 flex items-end gap-1">
                <span className="font-display text-5xl font-bold tracking-tight text-[var(--ds-heading)] dv-num">
                  {price === null ? "Custom" : `$${price}`}
                </span>
                {price !== null && <span className="mb-1.5 text-small text-[var(--ds-text-muted)]">/month</span>}
              </p>
              <p className="mt-1 h-5 text-caption text-[var(--ds-text-muted)]">
                {yearly && p.monthly ? `$${p.monthly * 10} billed yearly` : p.monthly ? "billed monthly" : "free forever"}
              </p>
              <p className="mt-5 rounded-[var(--radius-btn)] bg-[var(--ds-surface-brand)] px-3 py-2 text-center text-small font-semibold text-[var(--accent-foreground)]">
                {p.websites}
              </p>
              <ul className="mt-5 flex-1 space-y-3">
                {p.highlights.map((h) => (
                  <li key={h} className="flex gap-2.5 text-small text-[var(--ds-text)]">
                    <Check className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600 dark:text-emerald-400" aria-hidden />
                    {h}
                  </li>
                ))}
              </ul>
              <Link
                href={p.cta.href}
                className={`ds-btn mt-7 w-full ${p.popular || p.key === "free" ? "ds-btn-primary" : "ds-btn-outline"}`}
              >
                {p.cta.label}
              </Link>
            </div>
          );
        })}
      </div>
    </div>
  );
}
