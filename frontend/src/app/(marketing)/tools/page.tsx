import type { Metadata } from "next";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { FeatureIcon } from "@/components/marketing/icons";
import { CtaBand, PageHero } from "@/components/marketing/sections";
import { TOOLS } from "@/lib/marketing/content";

export const metadata: Metadata = {
  title: "Free website tools: SSL, domain, uptime and script checks",
  description:
    "Free tools for web agencies: SSL checker, domain expiry checker, website down checker and third-party script scanner. No signup needed.",
  alternates: { canonical: "/tools" },
};

export default function ToolsPage() {
  return (
    <>
      <PageHero
        eyebrow="Free tools"
        title="Free website checks, no signup"
        lead="The same checks Stacks Monitor runs for agencies every day. Use them as often as you need."
      />
      <section className="ds-section">
        <div className="ds-container grid gap-5 md:grid-cols-2">
          {TOOLS.map((t) => (
            <Link key={t.slug} href={`/tools/${t.slug}`} className="ds-card ds-card-hover group flex gap-5">
              <span className="ds-icon-tile shrink-0"><FeatureIcon icon={t.icon} /></span>
              <div>
                <h2 className="ds-h4">{t.name}</h2>
                <p className="mt-2 text-[var(--ds-text-muted)]">{t.short}</p>
                <span className="mt-3 inline-flex items-center gap-1 text-small font-semibold text-[var(--ds-link)]">
                  Open tool <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" aria-hidden />
                </span>
              </div>
            </Link>
          ))}
        </div>
      </section>
      <CtaBand title="Want these checks every day?" lead="Add your sites to a free workspace and get alerts when anything changes." />
    </>
  );
}
