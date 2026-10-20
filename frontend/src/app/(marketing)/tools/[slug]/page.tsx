import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowRight } from "lucide-react";
import { FeatureIcon } from "@/components/marketing/icons";
import { CtaBand, JsonLd } from "@/components/marketing/sections";
import { ToolRunner } from "@/components/marketing/tool-runner";
import { FEATURE_BY_SLUG, SITE_URL, TOOLS, TOOL_BY_SLUG } from "@/lib/marketing/content";

type Props = { params: Promise<{ slug: string }> };

export const dynamicParams = false;

export function generateStaticParams() {
  return TOOLS.map((t) => ({ slug: t.slug }));
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const t = TOOL_BY_SLUG[(await params).slug];
  if (!t) return {};
  return { title: t.title, description: t.description, alternates: { canonical: `/tools/${t.slug}` } };
}

export default async function ToolPage({ params }: Props) {
  const t = TOOL_BY_SLUG[(await params).slug];
  if (!t) notFound();
  const feature = FEATURE_BY_SLUG[t.feature];
  const others = TOOLS.filter((x) => x.slug !== t.slug);

  return (
    <>
      <JsonLd
        data={{
          "@context": "https://schema.org",
          "@type": "WebApplication",
          name: t.name,
          url: `${SITE_URL}/tools/${t.slug}`,
          applicationCategory: "DeveloperApplication",
          offers: { "@type": "Offer", price: 0, priceCurrency: "USD" },
        }}
      />
      <section className="relative overflow-hidden border-b border-[var(--ds-line)]">
        <div aria-hidden className="pointer-events-none absolute inset-x-0 -top-40 mx-auto h-80 max-w-3xl rounded-full bg-[var(--ds-hero-glow)] blur-3xl" />
        <div className="ds-container relative py-12 md:py-16">
          <div className="text-center">
            <p className="ds-eyebrow">Free tool</p>
            <h1 className="ds-h1 mt-3">{t.h1}</h1>
            <p className="ds-lead mx-auto mt-4 max-w-2xl">{t.intro}</p>
          </div>
          <div className="mt-10">
            <ToolRunner kind={t.kind} param={t.param} placeholder={t.placeholder} />
          </div>
        </div>
      </section>

      <section className="ds-section">
        <div className="ds-container grid gap-10 lg:grid-cols-[1.4fr_1fr]">
          <div className="ds-prose">
            {t.about.map((a) => (
              <div key={a.title}>
                <h2>{a.title}</h2>
                <p>{a.body}</p>
              </div>
            ))}
          </div>
          <aside className="ds-card h-fit">
            <span className="ds-icon-tile"><FeatureIcon icon={feature.icon} /></span>
            <h2 className="ds-h4 mt-4">{feature.name}</h2>
            <p className="mt-2 text-small text-[var(--ds-text-muted)]">{feature.short}</p>
            <Link href={`/features/${feature.slug}`} className="mt-4 inline-flex items-center gap-1 text-small font-semibold text-[var(--ds-link)]">
              How monitoring works <ArrowRight className="h-4 w-4" aria-hidden />
            </Link>
          </aside>
        </div>
      </section>

      <section className="ds-section ds-section-sunken">
        <div className="ds-container">
          <h2 className="ds-h3 text-center">More free tools</h2>
          <div className="mt-8 grid gap-5 sm:grid-cols-3">
            {others.map((o) => (
              <Link key={o.slug} href={`/tools/${o.slug}`} className="ds-card ds-card-hover block">
                <h3 className="ds-h5">{o.name}</h3>
                <p className="mt-1 text-small text-[var(--ds-text-muted)]">{o.short}</p>
              </Link>
            ))}
          </div>
        </div>
      </section>
      <CtaBand />
    </>
  );
}
