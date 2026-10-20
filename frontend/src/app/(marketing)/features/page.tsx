import type { Metadata } from "next";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { FeatureIcon } from "@/components/marketing/icons";
import { CtaBand, PageHero } from "@/components/marketing/sections";
import { FEATURES } from "@/lib/marketing/content";

export const metadata: Metadata = {
  title: "Features: monitoring, renewals, scripts and vault",
  description:
    "Uptime monitoring, SSL and domain expiry, third-party script monitoring, a credentials vault, status pages, Web Vitals, heatmaps and client reports.",
  alternates: { canonical: "/features" },
};

export default function FeaturesPage() {
  return (
    <>
      <PageHero
        eyebrow="Features"
        title="One workspace for every client website"
        lead="Each module works on its own and together. Add a site once and all of it switches on."
      />
      <section className="ds-section">
        <div className="ds-container grid gap-5 md:grid-cols-2">
          {FEATURES.map((f) => (
            <Link key={f.slug} href={`/features/${f.slug}`} className="ds-card ds-card-hover group flex gap-5">
              <span className="ds-icon-tile shrink-0"><FeatureIcon icon={f.icon} /></span>
              <div>
                <h2 className="ds-h4">{f.name}</h2>
                <p className="mt-2 text-[var(--ds-text-muted)]">{f.intro}</p>
                <span className="mt-3 inline-flex items-center gap-1 text-small font-semibold text-[var(--ds-link)]">
                  Learn more <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" aria-hidden />
                </span>
              </div>
            </Link>
          ))}
        </div>
      </section>
      <CtaBand />
    </>
  );
}
