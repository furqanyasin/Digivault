import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowRight, Check } from "lucide-react";
import { FeatureIcon } from "@/components/marketing/icons";
import { CtaBand, Faq, JsonLd, SectionHeading } from "@/components/marketing/sections";
import { FEATURES, FEATURE_BY_SLUG, TOOL_BY_SLUG } from "@/lib/marketing/content";

type Props = { params: Promise<{ slug: string }> };

export const dynamicParams = false;

export function generateStaticParams() {
  return FEATURES.map((f) => ({ slug: f.slug }));
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const f = FEATURE_BY_SLUG[(await params).slug];
  if (!f) return {};
  return { title: f.title, description: f.description, alternates: { canonical: `/features/${f.slug}` } };
}

export default async function FeaturePage({ params }: Props) {
  const f = FEATURE_BY_SLUG[(await params).slug];
  if (!f) notFound();
  const tool = f.tool ? TOOL_BY_SLUG[f.tool] : null;
  const i = FEATURES.findIndex((x) => x.slug === f.slug);
  const siblings = [FEATURES[(i + 1) % FEATURES.length], FEATURES[(i + 2) % FEATURES.length]];

  return (
    <>
      {f.faq.length > 0 && (
        <JsonLd
          data={{
            "@context": "https://schema.org",
            "@type": "FAQPage",
            mainEntity: f.faq.map((x) => ({ "@type": "Question", name: x.q, acceptedAnswer: { "@type": "Answer", text: x.a } })),
          }}
        />
      )}
      <section className="relative overflow-hidden border-b border-[var(--ds-line)]">
        <div aria-hidden className="pointer-events-none absolute inset-x-0 -top-40 mx-auto h-80 max-w-3xl rounded-full bg-[var(--ds-hero-glow)] blur-3xl" />
        <div className="ds-container relative py-14 text-center md:py-20">
          <span className="ds-icon-tile mx-auto h-14 w-14"><FeatureIcon icon={f.icon} className="h-7 w-7" /></span>
          <h1 className="ds-h1 mx-auto mt-6 max-w-3xl">{f.h1}</h1>
          <p className="ds-lead mx-auto mt-5 max-w-2xl">{f.intro}</p>
          <div className="mt-8 flex flex-col justify-center gap-3 xs:flex-row">
            <Link href="/signup" className="ds-btn ds-btn-primary ds-btn-lg">Start free <ArrowRight className="h-4 w-4" aria-hidden /></Link>
            {tool ? (
              <Link href={`/tools/${tool.slug}`} className="ds-btn ds-btn-outline ds-btn-lg">Try the free {tool.name.toLowerCase()}</Link>
            ) : (
              <Link href="/pricing" className="ds-btn ds-btn-outline ds-btn-lg">See pricing</Link>
            )}
          </div>
        </div>
      </section>

      <section className="ds-section">
        <div className="ds-container grid gap-5 md:grid-cols-2">
          {f.points.map((p) => (
            <div key={p.title} className="ds-card">
              <span className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300">
                <Check className="h-5 w-5" aria-hidden />
              </span>
              <h2 className="ds-h4 mt-4">{p.title}</h2>
              <p className="mt-2 text-[var(--ds-text-muted)]">{p.body}</p>
            </div>
          ))}
        </div>
      </section>

      <Faq items={f.faq} />

      <section className="ds-section ds-section-sunken">
        <div className="ds-container">
          <SectionHeading title="Works even better with" />
          <div className="mx-auto mt-10 grid max-w-4xl gap-5 sm:grid-cols-2">
            {siblings.map((s) => (
              <Link key={s.slug} href={`/features/${s.slug}`} className="ds-card ds-card-hover flex gap-4">
                <span className="ds-icon-tile shrink-0"><FeatureIcon icon={s.icon} /></span>
                <div>
                  <h3 className="ds-h5">{s.name}</h3>
                  <p className="mt-1 text-small text-[var(--ds-text-muted)]">{s.short}</p>
                </div>
              </Link>
            ))}
          </div>
        </div>
      </section>

      <CtaBand />
    </>
  );
}
