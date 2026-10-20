import Link from "next/link";
import { ArrowRight, ChevronDown } from "lucide-react";

export function SectionHeading({
  eyebrow, title, lead, center = true, as: Tag = "h2",
}: { eyebrow?: string; title: string; lead?: string; center?: boolean; as?: "h1" | "h2" }) {
  return (
    <div className={center ? "mx-auto max-w-2xl text-center" : "max-w-2xl"}>
      {eyebrow && <p className="ds-eyebrow">{eyebrow}</p>}
      <Tag className={`${Tag === "h1" ? "ds-h1" : "ds-h2"} mt-3`}>{title}</Tag>
      {lead && <p className="ds-lead mt-4">{lead}</p>}
    </div>
  );
}

// Native <details>: works with JavaScript off and ships no client code.
export function Faq({ items, title = "Frequently asked questions" }: { items: { q: string; a: string }[]; title?: string }) {
  if (!items.length) return null;
  return (
    <section className="ds-section">
      <div className="ds-container">
        <SectionHeading eyebrow="FAQ" title={title} />
        <div className="mx-auto mt-10 max-w-3xl divide-y divide-[var(--ds-line)] rounded-[var(--radius-card)] border border-[var(--ds-line)] bg-[var(--ds-surface-raised)]">
          {items.map((item) => (
            <details key={item.q} className="group px-5 py-4 md:px-6">
              <summary className="flex cursor-pointer list-none items-center justify-between gap-4 font-semibold text-[var(--ds-heading)] [&::-webkit-details-marker]:hidden">
                {item.q}
                <ChevronDown className="h-5 w-5 shrink-0 text-[var(--ds-text-muted)] transition-transform group-open:rotate-180" aria-hidden />
              </summary>
              <p className="mt-3 text-[var(--ds-text-muted)] leading-relaxed">{item.a}</p>
            </details>
          ))}
        </div>
      </div>
    </section>
  );
}

export function CtaBand({
  title = "Start monitoring your first client site today",
  lead = "Free for one website, no card needed. Upgrade when your client list grows.",
}: { title?: string; lead?: string }) {
  return (
    <section className="ds-section pt-0">
      <div className="ds-container">
        <div className="relative overflow-hidden rounded-[var(--radius-panel)] bg-[var(--color-brand-700)] px-6 py-12 text-center shadow-[var(--shadow-panel)] md:px-12 md:py-16 dark:bg-[var(--color-brand-900)]">
          <div aria-hidden className="pointer-events-none absolute -right-24 -top-24 h-72 w-72 rounded-full bg-white/10 blur-2xl" />
          <div aria-hidden className="pointer-events-none absolute -bottom-28 -left-16 h-72 w-72 rounded-full bg-[var(--color-brand-400)]/30 blur-3xl" />
          <h2 className="ds-h2 relative !text-white">{title}</h2>
          <p className="relative mx-auto mt-4 max-w-xl text-lead text-white/80">{lead}</p>
          <div className="relative mt-8 flex flex-col justify-center gap-3 sm:flex-row">
            <Link href="/signup" className="ds-btn ds-btn-lg bg-white text-[var(--color-brand-700)] hover:bg-white/90">
              Create free account <ArrowRight className="h-4 w-4" aria-hidden />
            </Link>
            <Link href="/pricing" className="ds-btn ds-btn-lg border border-white/30 text-white hover:bg-white/10">
              See pricing
            </Link>
          </div>
        </div>
      </div>
    </section>
  );
}

export function JsonLd({ data }: { data: Record<string, unknown> }) {
  return (
    <script
      type="application/ld+json"
      // JSON.stringify output with "<" escaped cannot close the script tag.
      dangerouslySetInnerHTML={{ __html: JSON.stringify(data).replace(/</g, "\u003c") }}
    />
  );
}

export function PageHero({ eyebrow, title, lead, children }: { eyebrow?: string; title: string; lead?: string; children?: React.ReactNode }) {
  return (
    <section className="relative overflow-hidden border-b border-[var(--ds-line)]">
      <div aria-hidden className="pointer-events-none absolute inset-x-0 -top-40 mx-auto h-80 max-w-3xl rounded-full bg-[var(--ds-hero-glow)] blur-3xl" />
      <div className="ds-container relative py-14 md:py-20">
        <SectionHeading eyebrow={eyebrow} title={title} lead={lead} as="h1" />
        {children}
      </div>
    </section>
  );
}
