import type { Metadata } from "next";
import { CONTACT_EMAIL } from "@/lib/marketing/content";

export const metadata: Metadata = {
  title: "Privacy policy",
  description: "What data Stacks Monitor collects, why, how long we keep it and your rights.",
  alternates: { canonical: "/privacy" },
};

const UPDATED = "21 October 2026";

export default function PrivacyPage() {
  return (
    <section className="ds-section">
      <div className="ds-container">
        <article className="ds-prose mx-auto">
          <p className="ds-eyebrow">Legal</p>
          <h1 className="ds-h1 mt-3">Privacy policy</h1>
          <p className="mt-3 text-small">Last updated {UPDATED}</p>

          <h2>Who we are</h2>
          <p>Stacks Monitor (&quot;we&quot;) provides website monitoring for agencies at stacksmonitor.com. For questions about this policy, email <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>.</p>

          <h2>What we collect</h2>
          <ul>
            <li><strong>Account data:</strong> your name, email address, password hash, workspace name, and 2FA settings.</li>
            <li><strong>Workspace data:</strong> the websites, clients, monitors, alert settings and credentials you add. Vault passwords are encrypted at rest.</li>
            <li><strong>Monitoring data:</strong> results of checks we run against websites you add (status codes, response times, certificates, WHOIS records, scripts found).</li>
            <li><strong>Snippet data:</strong> if you install our snippet, it reports the scripts a page loads, performance metrics, and anonymous click and scroll positions for heatmaps. It does not record keystrokes, form values or sessions.</li>
            <li><strong>Usage and security logs:</strong> IP address, browser and actions taken in the dashboard, kept in an audit log for security.</li>
            <li><strong>Free tools:</strong> the domain or URL you check and your IP address, used only for rate limiting.</li>
          </ul>

          <h2>Why we use it</h2>
          <ul>
            <li>To provide the service you signed up for (performance of a contract).</li>
            <li>To keep accounts and workspaces secure and prevent abuse (legitimate interest).</li>
            <li>To send service emails such as alerts, verification and password resets.</li>
          </ul>
          <p>We do not sell personal data and we do not use it for advertising.</p>

          <h2>Cookies</h2>
          <p>We use strictly necessary cookies to keep you signed in, and local storage to remember your light or dark theme. The public website does not use advertising or tracking cookies.</p>

          <h2>Who we share it with</h2>
          <p>Only service providers that help us run Stacks Monitor, such as our hosting provider and our email delivery provider, under contracts that require them to protect it. Alerts you configure are delivered to the services you choose (for example Slack or ClickUp).</p>

          <h2>How long we keep it</h2>
          <p>Account and workspace data is kept while your account is active. Monitoring history is kept for the retention period of your plan. When you delete a workspace or account, its data is deleted within 30 days, except where the law requires us to keep records.</p>

          <h2>Your rights</h2>
          <p>You can access, correct, export or delete your data, and object to or restrict how we use it. Email <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a> and we will respond within 30 days. If you are in the EU or UK you may also complain to your data protection authority.</p>

          <h2>Agencies and their clients</h2>
          <p>When you add a client website or client credentials, you decide what is collected and why, and we process that data on your behalf. You are responsible for having the right to add it.</p>

          <h2>Changes</h2>
          <p>We will post changes here and, for significant changes, email workspace owners.</p>
        </article>
      </div>
    </section>
  );
}
