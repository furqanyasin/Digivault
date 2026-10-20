import type { Metadata } from "next";
import { CONTACT_EMAIL } from "@/lib/marketing/content";

export const metadata: Metadata = {
  title: "Terms of service",
  description: "The terms that apply when you use Stacks Monitor.",
  alternates: { canonical: "/terms" },
};

const UPDATED = "21 October 2026";

export default function TermsPage() {
  return (
    <section className="ds-section">
      <div className="ds-container">
        <article className="ds-prose mx-auto">
          <p className="ds-eyebrow">Legal</p>
          <h1 className="ds-h1 mt-3">Terms of service</h1>
          <p className="mt-3 text-small">Last updated {UPDATED}</p>

          <h2>1. The service</h2>
          <p>Stacks Monitor lets you monitor websites, track renewals and store credentials for websites you manage. By creating an account you agree to these terms.</p>

          <h2>2. Your account</h2>
          <ul>
            <li>You must give a real email address and keep your password and 2FA codes safe.</li>
            <li>You are responsible for everything done in your workspace, including by people you invite.</li>
            <li>One free workspace per person.</li>
          </ul>

          <h2>3. Acceptable use</h2>
          <p>Only monitor websites you own or have permission to monitor. Do not use Stacks Monitor or its free tools to load-test, scan for vulnerabilities, or harass any website, to store data you have no right to store, or to break the law. We may suspend accounts that do.</p>

          <h2>4. Plans and payment</h2>
          <p>The Free plan is free. Paid plans are billed monthly or yearly in advance as shown on the pricing page. If you go over a plan limit you will be asked to upgrade before adding more. You can cancel at any time; the plan stays active until the end of the paid period.</p>

          <h2>5. Your data</h2>
          <p>You own the data you put into Stacks Monitor. You give us permission to process it only to provide the service. See the privacy policy for details. You can export your data at any time.</p>

          <h2>6. Availability</h2>
          <p>We work hard to keep Stacks Monitor running and alerts flowing, but the service is provided &quot;as is&quot;. Monitoring can miss events, and we are not liable for losses caused by downtime, missed alerts, or expired domains or certificates.</p>

          <h2>7. Liability</h2>
          <p>To the extent the law allows, our total liability for any claim is limited to the amount you paid us in the 12 months before the claim.</p>

          <h2>8. Ending the service</h2>
          <p>You can delete your workspace at any time. We may end or suspend an account that breaks these terms, after notice where reasonable.</p>

          <h2>9. Changes</h2>
          <p>We may update these terms. If a change is significant we will email workspace owners before it takes effect.</p>

          <h2>Contact</h2>
          <p>Email <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>.</p>
        </article>
      </div>
    </section>
  );
}
