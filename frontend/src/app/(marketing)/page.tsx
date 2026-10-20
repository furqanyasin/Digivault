import type { Metadata } from "next";
import Link from "next/link";
import { ArrowRight, Check, Wrench } from "lucide-react";
import { DashboardPreview } from "@/components/marketing/dashboard-preview";
import { FeatureIcon } from "@/components/marketing/icons";
import { CtaBand, Faq, JsonLd, SectionHeading } from "@/components/marketing/sections";
import { FEATURES, HOME_FAQ, PLANS, SITE_URL, TOOLS } from "@/lib/marketing/content";

export const metadata: Metadata = {
  title: { absolute: "Stacks Monitor: website monitoring for agencies" },
  description:
    "Monitor every client website in one dashboard: uptime, SSL and domain expiry, third-party script changes and a shared credentials vault. Free for one site.",
  alternates: { canonical: "/" },
};

const STEPS = [
  { title: "Add your client sites", body: "Paste a domain. Uptime, SSL and domain checks start right away, nothing to install." },
  { title: "Drop in the snippet", body: "One async script tag (or the WordPress snippet) adds script monitoring, heatmaps and Web Vitals." },
  { title: "Get told first", body: "Alerts by email, Slack or ClickUp, and a status page per client so they can check for themselves." },
];

export default function HomePage() {
  return (
    <>
      <JsonLd
        data={{
          "@context": "https://schema.org",
          "@type": "Organization",
          name: "Stacks Monitor",
          url: SITE_URL,
          logo: `${SITE_URL}/stacksmonitor-icon.svg`,
        }}
      />

      {/* Hero */}
      <section className="relative overflow-hidden">
        <div aria-hidden className="pointer-events-none absolute inset-x-0 -top-48 mx-auto h-[28rem] max-w-5xl rounded-full bg-[var(--ds-hero-glow)] blur-3xl" />
        <div className="ds-container-wide relative grid items-center gap-12 py-14 md:py-20 lg:grid-cols-[1fr_1.05fr] lg:gap-16 xl:py-24">
          <div>
            <p className="ds-eyebrow rounded-full border border-[var(--ds-line)] bg-[var(--ds-surface-raised)] px-3 py-1">
              Built for web agencies
            </p>
            <h1 className="ds-display mt-5">
              Every client website, monitored in <span className="text-[var(--primary)]">one dashboard</span>
            </h1>
            <p className="ds-lead mt-6 max-w-xl">
              Uptime, SSL and domain expiry, third-party script changes and a shared credentials vault.
              Stop juggling four tools and find problems before your clients do.
            </p>
            <div className="mt-8 flex flex-col gap-3 xs:flex-row">
              <Link href="/signup" className="ds-btn ds-btn-primary ds-btn-lg">
                Start free <ArrowRight className="h-4 w-4" aria-hidden />
              </Link>
              <Link href="/tools" className="ds-btn ds-btn-outline ds-btn-lg">
                <Wrench className="h-4 w-4" aria-hidden /> Try the free tools
              </Link>
            </div>
            <ul className="mt-6 flex flex-wrap gap-x-5 gap-y-2 text-small text-[var(--ds-text-muted)]">
              {["Free for 1 website", "No card needed", "Set up in 2 minutes"].map((t) => (
                <li key={t} className="flex items-center gap-1.5">
                  <Check className="h-4 w-4 text-emerald-600 dark:text-emerald-400" aria-hidden /> {t}
                </li>
              ))}
            </ul>
          </div>
          <DashboardPreview />
        </div>
      </section>

      {/* Replace the stack */}
      <section className="border-y border-[var(--ds-line)] bg-[var(--ds-surface-sunken)]">
        <div className="ds-container grid grid-cols-2 gap-6 py-10 text-center md:grid-cols-4">
          {[
            ["Uptime checks", "HTTP, ping, port, SSL"],
            ["Renewals", "SSL, domain, hosting"],
            ["Script changes", "Every page, every visit"],
            ["Shared vault", "Encrypted client logins"],
          ].map(([a, b]) => (
            <div key={a}>
              <p className="font-display text-lg font-bold text-[var(--ds-heading)]">{a}</p>
              <p className="mt-1 text-small text-[var(--ds-text-muted)]">{b}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Features */}
      <section className="ds-section">
        <div className="ds-container">
          <SectionHeading
            eyebrow="Features"
            title="Everything you check by hand, checked for you"
            lead="One workspace for the whole agency. Each client site gets monitoring, renewals, scripts, logins and a status page."
          />
          <div className="mt-12 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {FEATURES.map((f) => (
              <Link key={f.slug} href={`/features/${f.slug}`} className="ds-card ds-card-hover group block">
                <span className="ds-icon-tile"><FeatureIcon icon={f.icon} /></span>
                <h3 className="ds-h4 mt-5">{f.name}</h3>
                <p className="mt-2 text-[var(--ds-text-muted)]">{f.short}</p>
                <span className="mt-4 inline-flex items-center gap-1 text-small font-semibold text-[var(--ds-link)]">
                  Learn more <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" aria-hidden />
                </span>
              </Link>
            ))}
          </div>
        </div>
      </section>

      {/* How it works */}
      <section className="ds-section ds-section-sunken">
        <div className="ds-container">
          <SectionHeading eyebrow="How it works" title="Live in three steps" />
          <ol className="mt-12 grid gap-5 md:grid-cols-3">
            {STEPS.map((s, i) => (
              <li key={s.title} className="ds-card">
                <span className="inline-flex h-10 w-10 items-center justify-center rounded-full bg-[var(--primary)] font-display font-bold text-[var(--primary-foreground)]">
                  {i + 1}
                </span>
                <h3 className="ds-h4 mt-5">{s.title}</h3>
                <p className="mt-2 text-[var(--ds-text-muted)]">{s.body}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* Free tools */}
      <section className="ds-section">
        <div className="ds-container">
          <SectionHeading
            eyebrow="Free tools"
            title="Check any website right now"
            lead="No account needed. When you want it checked every day, add the site to a free workspace."
          />
          <div className="mt-12 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
            {TOOLS.map((t) => (
              <Link key={t.slug} href={`/tools/${t.slug}`} className="ds-card ds-card-hover block">
                <span className="ds-icon-tile"><FeatureIcon icon={t.icon} /></span>
                <h3 className="ds-h5 mt-4">{t.name}</h3>
                <p className="mt-2 text-small text-[var(--ds-text-muted)]">{t.short}</p>
              </Link>
            ))}
          </div>
        </div>
      </section>

      {/* Pricing teaser */}
      <section className="ds-section ds-section-sunken">
        <div className="ds-container">
          <SectionHeading
            eyebrow="Pricing"
            title="Priced per client site, not per seat"
            lead="Start free with one website. Paid plans from $19 a month for 10 sites."
          />
          <div className="mt-12 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
            {PLANS.map((p) => (
              <div key={p.key} className={`ds-card ${p.popular ? "ring-2 ring-[var(--primary)]" : ""}`}>
                <p className="font-semibold text-[var(--ds-heading)]">{p.name}</p>
                <p className="mt-2 font-display text-3xl font-bold text-[var(--ds-heading)]">
                  ${p.monthly}<span className="text-small font-medium text-[var(--ds-text-muted)]">/mo</span>
                </p>
                <p className="mt-1 text-small text-[var(--ds-text-muted)]">{p.websites}</p>
              </div>
            ))}
          </div>
          <div className="mt-8 text-center">
            <Link href="/pricing" className="ds-btn ds-btn-outline">
              Compare plans <ArrowRight className="h-4 w-4" aria-hidden />
            </Link>
          </div>
        </div>
      </section>

      <Faq items={HOME_FAQ} />
      <CtaBand />
    </>
  );
}
