import type { Metadata } from "next";
import Link from "next/link";
import { Check, Minus } from "lucide-react";
import { PricingCards } from "@/components/marketing/pricing-cards";
import { CtaBand, Faq, JsonLd, PageHero } from "@/components/marketing/sections";
import { COMPARE_ROWS, PLANS, PRICING_FAQ, SITE_URL } from "@/lib/marketing/content";

export const metadata: Metadata = {
  title: "Pricing: plans from free to agency",
  description:
    "Stacks Monitor pricing. Free for 1 website, Starter $19 for 10 sites, Agency $49 for 30 sites, Agency Pro $99 for 75 sites. Every plan includes the vault.",
  alternates: { canonical: "/pricing" },
};

function Cell({ value }: { value: string }) {
  if (value === "yes") return <Check className="mx-auto h-5 w-5 text-emerald-600 dark:text-emerald-400" aria-label="Included" />;
  if (value === "no") return <Minus className="mx-auto h-5 w-5 text-[var(--ds-text-muted)]" aria-label="Not included" />;
  return <span className="dv-num">{value}</span>;
}

export default function PricingPage() {
  return (
    <>
      <JsonLd
        data={{
          "@context": "https://schema.org",
          "@type": "SoftwareApplication",
          name: "Stacks Monitor",
          applicationCategory: "BusinessApplication",
          operatingSystem: "Web",
          url: `${SITE_URL}/pricing`,
          offers: PLANS.filter((p) => p.monthly !== null).map((p) => ({
            "@type": "Offer",
            name: p.name,
            price: p.monthly,
            priceCurrency: "USD",
          })),
        }}
      />
      <PageHero
        eyebrow="Pricing"
        title="Simple pricing per client website"
        lead="Every plan includes uptime, SSL and domain monitoring, script change alerts and the credentials vault. Pay for the number of sites you look after."
      />

      <section className="ds-section">
        <div className="ds-container-wide">
          <PricingCards plans={PLANS} />
          <p className="mt-8 text-center text-small text-[var(--ds-text-muted)]">
            Need more than 75 websites or a custom contract?{" "}
            <Link href="/contact?plan=enterprise" className="font-semibold text-[var(--ds-link)]">Talk to us about Enterprise</Link>.
          </p>
        </div>
      </section>

      <section className="ds-section ds-section-sunken">
        <div className="ds-container">
          <h2 className="ds-h2 text-center">Compare plans</h2>
          <div className="mt-10 overflow-x-auto rounded-[var(--radius-card)] border border-[var(--ds-line)] bg-[var(--ds-surface-raised)]">
            <table className="w-full min-w-[640px] text-small">
              <thead>
                <tr className="border-b border-[var(--ds-line)] text-left">
                  <th scope="col" className="px-4 py-4 font-semibold text-[var(--ds-text-muted)]">Feature</th>
                  {PLANS.map((p) => (
                    <th key={p.key} scope="col" className="px-4 py-4 text-center font-semibold text-[var(--ds-heading)]">{p.name}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {COMPARE_ROWS.map((row) => (
                  <tr key={row.label} className="border-b border-[var(--ds-line)] last:border-0">
                    <th scope="row" className="px-4 py-3.5 text-left font-medium text-[var(--ds-text)]">{row.label}</th>
                    {row.values.map((v, i) => (
                      <td key={i} className="px-4 py-3.5 text-center text-[var(--ds-text)]"><Cell value={v} /></td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-4 text-center text-caption text-[var(--ds-text-muted)]">Prices in USD. Taxes may apply.</p>
        </div>
      </section>

      <Faq items={PRICING_FAQ} title="Pricing questions" />
      <CtaBand />
    </>
  );
}
