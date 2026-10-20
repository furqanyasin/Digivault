import type { Metadata } from "next";
import { Building2, ClipboardList, KeyRound, LockKeyhole, Network, ShieldCheck } from "lucide-react";
import { CtaBand, PageHero } from "@/components/marketing/sections";
import { CONTACT_EMAIL } from "@/lib/marketing/content";

export const metadata: Metadata = {
  title: "Security",
  description: "How Stacks Monitor protects agency and client data: isolated workspaces, encrypted vault, two-factor authentication and a full audit log.",
  alternates: { canonical: "/security" },
};

const ITEMS = [
  { icon: Building2, title: "Isolated workspaces", body: "Every workspace is a separate tenant. Every API route is tested to prove one workspace can never read another's data." },
  { icon: KeyRound, title: "Encrypted vault", body: "Stored passwords are encrypted at rest with rotating keys and decrypted only when someone with access reveals them." },
  { icon: LockKeyhole, title: "Two-factor authentication", body: "TOTP 2FA with backup codes. Workspace owners can make it mandatory for every member." },
  { icon: ClipboardList, title: "Audit log", body: "Logins, credential reveals, permission changes and deletions are recorded with who, when and from where." },
  { icon: Network, title: "Safe outbound checks", body: "Our checkers refuse private and internal addresses and identify themselves with a clear user agent, so client firewalls can allowlist us." },
  { icon: ShieldCheck, title: "Least privilege roles", body: "Owner, manager, developer and viewer roles, custom section access, and vault groups so people only see the logins they need." },
];

export default function SecurityPage() {
  return (
    <>
      <PageHero eyebrow="Security" title="Built to hold your clients' keys" lead="An agency tool holds logins to dozens of businesses. We treat that the way it deserves." />
      <section className="ds-section">
        <div className="ds-container grid gap-5 md:grid-cols-2 lg:grid-cols-3">
          {ITEMS.map(({ icon: Icon, title, body }) => (
            <div key={title} className="ds-card">
              <span className="ds-icon-tile"><Icon className="h-6 w-6" aria-hidden /></span>
              <h2 className="ds-h4 mt-5">{title}</h2>
              <p className="mt-2 text-[var(--ds-text-muted)]">{body}</p>
            </div>
          ))}
        </div>
        <p className="ds-container mt-10 text-center text-small text-[var(--ds-text-muted)]">
          Found a vulnerability? Email <a className="font-semibold text-[var(--ds-link)]" href={`mailto:${CONTACT_EMAIL}?subject=Security%20report`}>{CONTACT_EMAIL}</a>. We respond within 48 hours.
        </p>
      </section>
      <CtaBand />
    </>
  );
}
