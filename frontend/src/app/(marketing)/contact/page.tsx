import type { Metadata } from "next";
import Link from "next/link";
import { LifeBuoy, Mail, Rocket } from "lucide-react";
import { PageHero } from "@/components/marketing/sections";
import { CONTACT_EMAIL, PLANS } from "@/lib/marketing/content";

export const metadata: Metadata = {
  title: "Contact us",
  description: "Questions, upgrades or a custom plan? Email the Stacks Monitor team and we reply within one working day.",
  alternates: { canonical: "/contact" },
};

type Props = { searchParams: Promise<{ plan?: string }> };

export default async function ContactPage({ searchParams }: Props) {
  const planKey = (await searchParams).plan;
  const plan = PLANS.find((p) => p.key === planKey);
  const upgradeSubject = encodeURIComponent(plan ? `Upgrade to ${plan.name}` : planKey === "enterprise" ? "Enterprise plan" : "Upgrade my plan");
  const upgradeBody = encodeURIComponent("Workspace name:\nAccount email:\nPlan wanted:\nMonthly or yearly:\n");

  const cards = [
    {
      icon: Rocket,
      title: plan ? `Upgrade to ${plan.name}` : "Upgrade or Enterprise",
      body: "Tell us your workspace name and the plan you want. We switch it the same day and send an invoice.",
      href: `mailto:${CONTACT_EMAIL}?subject=${upgradeSubject}&body=${upgradeBody}`,
      cta: "Email about a plan",
    },
    {
      icon: LifeBuoy,
      title: "Support",
      body: "Something not working? Include the website and what you expected to see.",
      href: `mailto:${CONTACT_EMAIL}?subject=${encodeURIComponent("Support request")}`,
      cta: "Email support",
    },
    {
      icon: Mail,
      title: "Everything else",
      body: "Partnerships, press, security reports or feedback.",
      href: `mailto:${CONTACT_EMAIL}`,
      cta: CONTACT_EMAIL,
    },
  ];

  return (
    <>
      <PageHero eyebrow="Contact" title="Talk to a human" lead="We reply within one working day." />
      <section className="ds-section">
        <div className="ds-container grid gap-5 md:grid-cols-3">
          {cards.map(({ icon: Icon, title, body, href, cta }) => (
            <div key={title} className="ds-card flex flex-col">
              <span className="ds-icon-tile"><Icon className="h-6 w-6" aria-hidden /></span>
              <h2 className="ds-h4 mt-5">{title}</h2>
              <p className="mt-2 flex-1 text-[var(--ds-text-muted)]">{body}</p>
              <a href={href} className="ds-btn ds-btn-outline mt-6 w-full">{cta}</a>
            </div>
          ))}
        </div>
        <p className="ds-container mt-10 text-center text-small text-[var(--ds-text-muted)]">
          Already have an account? <Link href="/login" className="font-semibold text-[var(--ds-link)]">Log in</Link> and your workspace name is in the sidebar.
        </p>
      </section>
    </>
  );
}
