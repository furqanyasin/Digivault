import Link from "next/link";
import { CONTACT_EMAIL, FEATURES, TOOLS } from "@/lib/marketing/content";
import { PRODUCT_NAME } from "@/lib/brand";
import { LogoMark } from "./logo";

export function SiteFooter() {
  const year = new Date().getFullYear();
  return (
    <footer className="border-t border-[var(--ds-line)] bg-[var(--ds-surface-sunken)]">
      <div className="ds-container-wide grid gap-10 py-14 md:grid-cols-2 lg:grid-cols-[1.4fr_1fr_1fr_1fr]">
        <div className="max-w-sm">
          <Link href="/" className="flex items-center gap-2.5">
            <LogoMark />
            <span className="font-display text-lg font-bold">{PRODUCT_NAME}</span>
          </Link>
          <p className="mt-4 text-small leading-relaxed text-[var(--ds-text-muted)]">
            Uptime, SSL and domain expiry, script changes and a shared credentials vault for every client website.
            Built for web agencies.
          </p>
          <a href={`mailto:${CONTACT_EMAIL}`} className="mt-4 inline-block text-small font-medium text-[var(--ds-link)]">
            {CONTACT_EMAIL}
          </a>
        </div>
        <FooterCol title="Features" links={FEATURES.slice(0, 6).map((f) => ({ href: `/features/${f.slug}`, label: f.name }))} />
        <FooterCol title="Free tools" links={TOOLS.map((t) => ({ href: `/tools/${t.slug}`, label: t.name }))} />
        <FooterCol
          title="Company"
          links={[
            { href: "/pricing", label: "Pricing" },
            { href: "/contact", label: "Contact" },
            { href: "/security", label: "Security" },
            { href: "/privacy", label: "Privacy policy" },
            { href: "/terms", label: "Terms of service" },
          ]}
        />
      </div>
      <div className="border-t border-[var(--ds-line)]">
        <div className="ds-container-wide flex flex-col gap-2 py-6 text-caption text-[var(--ds-text-muted)] sm:flex-row sm:items-center sm:justify-between">
          <p>&copy; {year} {PRODUCT_NAME}. All rights reserved.</p>
          <p>
            Report abuse: <a className="underline" href={`mailto:${CONTACT_EMAIL}?subject=Abuse%20report`}>{CONTACT_EMAIL}</a>
          </p>
        </div>
      </div>
    </footer>
  );
}

function FooterCol({ title, links }: { title: string; links: { href: string; label: string }[] }) {
  return (
    <div>
      <h2 className="ds-h6 uppercase tracking-wider text-[var(--ds-text-muted)]">{title}</h2>
      <ul className="mt-4 space-y-2.5">
        {links.map((l) => (
          <li key={l.href}>
            <Link href={l.href} className="text-small text-[var(--ds-text)] hover:text-[var(--ds-link)]">
              {l.label}
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
