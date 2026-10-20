// Copy and data for the public website. Pages read from here so a price or a
// feature line changes in one place.
//
// Plan limits must match apps/accounts/plans.py (the backend enforces those).

export const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "https://stacksmonitor.com";
export const CONTACT_EMAIL = "support@stacksmonitor.com";

export type IconKey =
  | "uptime" | "ssl" | "scripts" | "vault" | "status" | "performance"
  | "heatmap" | "reports" | "wordpress" | "alerts" | "extension" | "team";

export interface Feature {
  slug: string;
  icon: IconKey;
  name: string;
  short: string;
  title: string; // <title>, under 60 chars
  description: string; // meta description, under 155 chars
  h1: string;
  intro: string;
  points: { title: string; body: string }[];
  faq: { q: string; a: string }[];
  tool?: string; // slug of a related free tool
}

export const FEATURES: Feature[] = [
  {
    slug: "uptime-monitoring",
    icon: "uptime",
    name: "Uptime monitoring",
    short: "Know a client site is down before the client calls you.",
    title: "Uptime monitoring for agencies",
    description:
      "Monitor every client website for downtime with HTTP, ping, port and SSL checks. Instant alerts by email, Slack or ClickUp, plus public status pages.",
    h1: "Uptime monitoring for every client website",
    intro:
      "Stacks Monitor checks each site on a schedule, confirms an outage from a second attempt before it alerts, and tells you when a firewall is blocking the check instead of crying wolf.",
    points: [
      { title: "HTTP, ping, port and SSL checks", body: "Watch the homepage, a login page, an API or a mail port. Expected status codes and keyword checks catch a page that loads but is broken." },
      { title: "No false alarms", body: "Failures are retried before anyone is paged, and a Cloudflare or Sucuri challenge is reported as blocked, not down." },
      { title: "Response time history", body: "Every check is stored with its response time, so slow weeks show up on a chart before they become outages." },
      { title: "Alerts where your team works", body: "Email, Slack and ClickUp, with per-monitor rules and quiet digests for the noisy ones." },
    ],
    faq: [
      { q: "How often are sites checked?", a: "Free plans check every 5 minutes. Paid plans go down to every minute, and Agency Pro to every 30 seconds." },
      { q: "Do I need to install anything?", a: "No. Uptime checks run from our servers. The optional snippet adds script monitoring and heatmaps." },
    ],
    tool: "website-down-checker",
  },
  {
    slug: "ssl-domain-monitoring",
    icon: "ssl",
    name: "SSL and domain expiry",
    short: "Never let a certificate or a domain lapse again.",
    title: "SSL certificate and domain expiry monitoring",
    description:
      "Track SSL certificate and domain expiry dates for all client websites. Renewal reminders from 90 days out, plus registrar and hosting details.",
    h1: "SSL certificate and domain expiry monitoring",
    intro:
      "An expired certificate takes a site offline just as surely as a crashed server. Stacks Monitor reads every certificate and WHOIS record and reminds you before anything expires.",
    points: [
      { title: "Renewal Center", body: "One list of every certificate and domain across all clients, sorted by what expires next." },
      { title: "Registrar and hosting detection", body: "See who the domain is registered with, where it is hosted and whether it runs through Cloudflare." },
      { title: "Email deliverability checks", body: "SPF, DKIM and DMARC records are checked too, so client email does not quietly land in spam." },
      { title: "Reminders that escalate", body: "Domain reminders at 90, 60, 30, 14, 7 and 3 days. Certificate reminders at 90, 30 and 7 days." },
    ],
    faq: [
      { q: "Does it work with Let's Encrypt?", a: "Yes. Auto-renewing certificates are tracked too, so you hear about it when an auto-renewal fails." },
    ],
    tool: "ssl-checker",
  },
  {
    slug: "script-monitoring",
    icon: "scripts",
    name: "Third-party script monitoring",
    short: "See every script on a client site, and every change.",
    title: "Third-party script monitoring and change alerts",
    description:
      "Inventory every third-party script on client websites and get alerts when one is added, removed or changed. Supports PCI DSS 6.4.3 and 11.6.1.",
    h1: "Third-party script monitoring with change alerts",
    intro:
      "Tag managers, chat widgets and ad pixels change under you. A lightweight snippet records every script each page loads and alerts you the moment something new appears.",
    points: [
      { title: "Live script inventory", body: "Every script on every page, with its provider and category: analytics, ads, chat, payments or unknown." },
      { title: "Change detection", body: "Added, removed or modified scripts raise an alert with a diff. Unknown scripts wait for review." },
      { title: "Tracking that stays working", body: "Get told when Google Analytics, Tag Manager or a Meta Pixel disappears, before the client's ad reports go blank." },
      { title: "Compliance evidence", body: "An authorised script inventory and change log help with PCI DSS 6.4.3 and 11.6.1 on payment pages." },
    ],
    faq: [
      { q: "Will the snippet slow the site down?", a: "No. It loads asynchronously after the page and sends small batches in the background." },
      { q: "Does it work on WordPress?", a: "Yes, and on Shopify, Webflow, Wix or any site where you can add a script tag." },
    ],
    tool: "website-script-scanner",
  },
  {
    slug: "credentials-vault",
    icon: "vault",
    name: "Credentials vault",
    short: "Share client logins safely, not in spreadsheets.",
    title: "Password manager for agencies and client logins",
    description:
      "An encrypted credentials vault for client hosting, WordPress and DNS logins. Share by team or group, log every reveal, and hand over a client in one click.",
    h1: "A credentials vault built for agency teams",
    intro:
      "Client logins live in chats, sheets and memories. The vault keeps them encrypted, shares them with the right people, and records who opened what.",
    points: [
      { title: "Encrypted at rest", body: "Every password is encrypted with rotating keys. Plaintext is only decrypted when someone with access reveals it." },
      { title: "Groups and folders", body: "Give the web team hosting logins and the SEO team analytics logins without sharing everything with everyone." },
      { title: "Audit trail", body: "Every reveal, copy and change is logged with who and when." },
      { title: "Browser extension", body: "Fill a client's wp-admin login from the vault without ever seeing the password." },
    ],
    faq: [
      { q: "Can a client get their logins back?", a: "Yes. Handover exports a client's credentials so you can pass them on when a contract ends." },
    ],
  },
  {
    slug: "status-pages",
    icon: "status",
    name: "Status pages",
    short: "A public status page per client, updated automatically.",
    title: "Status pages for clients",
    description:
      "Give each client a public status page that updates from your uptime monitors. Post incidents and scheduled maintenance in seconds.",
    h1: "Status pages your clients can check themselves",
    intro:
      "Fewer \"is the site down?\" emails. Each client gets a clean status page fed by their monitors, with incidents and maintenance windows.",
    points: [
      { title: "Automatic", body: "Created with the website and updated by its monitors. No manual status changes." },
      { title: "Incidents and maintenance", body: "Post an incident or schedule maintenance and it shows up on the page right away." },
      { title: "Uptime history", body: "A 90-day uptime bar shows clients the reliability you deliver." },
    ],
    faq: [
      { q: "Can I use my own domain?", a: "Status pages live on stacksmonitor.com today. Custom domains are on the roadmap." },
    ],
  },
  {
    slug: "performance-monitoring",
    icon: "performance",
    name: "Performance and Core Web Vitals",
    short: "PageSpeed scores and real-user vitals over time.",
    title: "Core Web Vitals and PageSpeed monitoring",
    description:
      "Track PageSpeed scores and Core Web Vitals (LCP, INP, CLS) for every client site over time, with alerts when performance drops.",
    h1: "Core Web Vitals and PageSpeed monitoring",
    intro:
      "Scheduled Lighthouse runs and real-user Web Vitals show whether a site is getting faster or slower, and which change caused it.",
    points: [
      { title: "Daily PageSpeed runs", body: "Mobile and desktop scores, stored over time with the full Lighthouse audit." },
      { title: "Real-user vitals", body: "LCP, INP and CLS from actual visitors via the snippet, not only lab data." },
      { title: "SEO checks", body: "Titles, meta descriptions, headings and broken basics flagged per page." },
    ],
    faq: [],
  },
  {
    slug: "heatmaps",
    icon: "heatmap",
    name: "Heatmaps",
    short: "Click and scroll heatmaps without another tool.",
    title: "Website heatmaps for client sites",
    description:
      "Click and scroll heatmaps for every client website from the same snippet that monitors scripts. No extra tag, no extra bill.",
    h1: "Click and scroll heatmaps for client websites",
    intro:
      "See where visitors click and how far they scroll, page by page, using the snippet you already installed.",
    points: [
      { title: "Clicks and scroll depth", body: "Desktop, tablet and mobile views over a screenshot of the real page." },
      { title: "Privacy first", body: "No keystrokes, no form values and no session recordings." },
    ],
    faq: [],
  },
  {
    slug: "wordpress-monitoring",
    icon: "wordpress",
    name: "WordPress health",
    short: "PHP errors, plugin changes and one-click wp-admin login.",
    title: "WordPress monitoring for agencies",
    description:
      "Monitor WordPress sites for PHP errors, plugin and theme changes and vulnerable plugins. Log in to wp-admin with one click from your dashboard.",
    h1: "WordPress monitoring that agencies actually use",
    intro:
      "A small plugin snippet reports PHP errors, plugin updates and admin activity, so you know what changed on a client site and who changed it.",
    points: [
      { title: "PHP error log", body: "Fatal errors and warnings grouped and counted, with the file and line." },
      { title: "Plugin and theme changes", body: "Installs, updates and deactivations, with vulnerability checks on what is installed." },
      { title: "One-click login", body: "Open wp-admin from the dashboard with a role that matches your team role." },
    ],
    faq: [],
  },
  {
    slug: "client-reports",
    icon: "reports",
    name: "Client reports",
    short: "Monthly PDF reports that prove your maintenance work.",
    title: "Website maintenance reports for clients",
    description:
      "Send clients a monthly PDF with uptime, performance, SSL and security status. Show the value of your maintenance plan without building reports by hand.",
    h1: "Client reports that sell your maintenance plan",
    intro:
      "Uptime, response times, PageSpeed, certificates and script changes, in a clean PDF you can send every month.",
    points: [
      { title: "PDF and CSV", body: "One click per client, or generated for every client at the end of the month." },
      { title: "Your work, visible", body: "Updates, fixes and incidents handled are listed, so the retainer explains itself." },
    ],
    faq: [],
  },
];

export const FEATURE_BY_SLUG = Object.fromEntries(FEATURES.map((f) => [f.slug, f]));

export interface Plan {
  key: string;
  name: string;
  monthly: number | null; // null = custom
  blurb: string;
  websites: string;
  highlights: string[];
  cta: { label: string; href: string };
  popular?: boolean;
}

export const PLANS: Plan[] = [
  {
    key: "free",
    name: "Free",
    monthly: 0,
    blurb: "Everything switched on for one website. Free forever.",
    websites: "1 website",
    highlights: [
      "3 uptime monitors, 5 minute checks",
      "SSL and domain expiry alerts",
      "Script change monitoring",
      "Credentials vault",
      "1 status page",
      "Email alerts",
    ],
    cta: { label: "Start free", href: "/signup" },
  },
  {
    key: "starter",
    name: "Starter",
    monthly: 19,
    blurb: "For freelancers looking after a handful of client sites.",
    websites: "10 websites",
    highlights: [
      "50 uptime monitors, 1 minute checks",
      "3 team members",
      "3 status pages",
      "Client reports (PDF)",
      "Slack and ClickUp alerts",
      "Email support",
    ],
    cta: { label: "Start free, then upgrade", href: "/signup?plan=starter" },
  },
  {
    key: "agency",
    name: "Agency",
    monthly: 49,
    blurb: "For agencies running maintenance plans across many clients.",
    websites: "30 websites",
    highlights: [
      "150 uptime monitors, 1 minute checks",
      "10 team members",
      "10 status pages",
      "Vault groups and folders",
      "ClickUp integration",
      "Priority email support",
    ],
    cta: { label: "Start free, then upgrade", href: "/signup?plan=agency" },
    popular: true,
  },
  {
    key: "agency_pro",
    name: "Agency Pro",
    monthly: 99,
    blurb: "For larger teams with a big client portfolio.",
    websites: "75 websites",
    highlights: [
      "400 uptime monitors, 30 second checks",
      "Unlimited team members",
      "Unlimited status pages",
      "Everything in Agency",
      "Onboarding call",
    ],
    cta: { label: "Start free, then upgrade", href: "/signup?plan=agency_pro" },
  },
];

export const COMPARE_ROWS: { label: string; values: string[] }[] = [
  { label: "Websites", values: ["1", "10", "30", "75"] },
  { label: "Uptime monitors", values: ["3", "50", "150", "400"] },
  { label: "Fastest check interval", values: ["5 min", "1 min", "1 min", "30 sec"] },
  { label: "Team members", values: ["1", "3", "10", "Unlimited"] },
  { label: "Status pages", values: ["1", "3", "10", "Unlimited"] },
  { label: "SSL and domain expiry", values: ["yes", "yes", "yes", "yes"] },
  { label: "Script change monitoring", values: ["yes", "yes", "yes", "yes"] },
  { label: "Credentials vault", values: ["yes", "yes", "yes", "yes"] },
  { label: "Vault groups and folders", values: ["no", "no", "yes", "yes"] },
  { label: "Heatmaps", values: ["yes", "yes", "yes", "yes"] },
  { label: "Client reports (PDF)", values: ["no", "yes", "yes", "yes"] },
  { label: "Slack and ClickUp alerts", values: ["no", "yes", "yes", "yes"] },
  { label: "Support", values: ["Docs", "Email", "Priority email", "Email + call"] },
];

export const PRICING_FAQ = [
  { q: "Is the free plan really free?", a: "Yes. One website with every core feature, no card needed, no time limit." },
  { q: "How do I upgrade?", a: "Start on Free, then contact us from your dashboard or the contact page. We switch your workspace to the new plan the same day and send an invoice." },
  { q: "What counts as a website?", a: "One domain you monitor, such as clientsite.com. Its uptime monitor, scripts, vault entries and status page all come with it." },
  { q: "Can I pay yearly?", a: "Yes. Yearly billing costs 10 months, so you get 2 months free." },
  { q: "What happens if I downgrade?", a: "Nothing is deleted. Websites above the new limit are paused until you choose which ones stay active." },
];

export interface FreeTool {
  slug: string;
  kind: "ssl" | "domain" | "uptime" | "scripts";
  icon: IconKey;
  name: string;
  short: string;
  title: string;
  description: string;
  h1: string;
  intro: string;
  placeholder: string;
  param: "domain" | "url";
  feature: string; // feature slug for the upsell
  about: { title: string; body: string }[];
}

export const TOOLS: FreeTool[] = [
  {
    slug: "ssl-checker",
    kind: "ssl",
    icon: "ssl",
    name: "SSL checker",
    short: "Check a certificate's issuer, expiry date and covered domains.",
    title: "Free SSL checker: check certificate expiry",
    description: "Check any website's SSL certificate: issuer, expiry date, days left, TLS version and the domains it covers. Free, no signup.",
    h1: "SSL certificate checker",
    intro: "Enter a domain to see who issued its certificate, when it expires and which names it covers.",
    placeholder: "example.com",
    param: "domain",
    feature: "ssl-domain-monitoring",
    about: [
      { title: "Why certificates expire", body: "Public certificates last 90 days to 13 months. When one expires, browsers show a full-page warning and most visitors leave." },
      { title: "Auto-renewal still fails", body: "Let's Encrypt renews automatically, until a DNS change, a firewall rule or a full disk stops it. Daily monitoring catches the silent failures." },
    ],
  },
  {
    slug: "domain-expiry-checker",
    kind: "domain",
    icon: "ssl",
    name: "Domain expiry checker",
    short: "Look up a domain's registrar, expiry date and nameservers.",
    title: "Domain expiry checker: WHOIS expiry date lookup",
    description: "Find out when any domain expires, who it is registered with and which nameservers it uses. Free WHOIS expiry lookup, no signup.",
    h1: "Domain expiry checker",
    intro: "Enter a domain to see its registrar, registration date, expiry date and nameservers.",
    placeholder: "example.com",
    param: "domain",
    feature: "ssl-domain-monitoring",
    about: [
      { title: "An expired domain takes everything with it", body: "Website, email and every login tied to that address stop working, and a lapsed domain can be bought by someone else." },
      { title: "Track every client domain", body: "Stacks Monitor checks WHOIS for every client site and reminds you from 90 days before renewal." },
    ],
  },
  {
    slug: "website-down-checker",
    kind: "uptime",
    icon: "uptime",
    name: "Is my website down?",
    short: "Check if a website is up from our servers right now.",
    title: "Is my website down? Free website down checker",
    description: "Check whether a website is down for everyone or just you. See the HTTP status, response time and whether a firewall blocked the request.",
    h1: "Is my website down?",
    intro: "Enter a website address and we will request it from our servers and report what came back.",
    placeholder: "https://example.com",
    param: "url",
    feature: "uptime-monitoring",
    about: [
      { title: "Down for everyone or just you?", body: "If our check says up but you cannot load the site, the problem is likely your network, DNS cache or a firewall rule for your IP." },
      { title: "Blocked is not down", body: "Cloudflare and other firewalls sometimes challenge automated checks. We say so instead of reporting the site as down." },
    ],
  },
  {
    slug: "website-script-scanner",
    kind: "scripts",
    icon: "scripts",
    name: "Website script scanner",
    short: "List every third-party script a page loads.",
    title: "Website script scanner: find third-party scripts",
    description: "See every third-party JavaScript a web page loads: analytics, ads, chat and unknown scripts. Free scanner, no signup.",
    h1: "Third-party script scanner",
    intro: "Enter a page address to list the external scripts in its HTML and which provider each one belongs to.",
    placeholder: "https://example.com",
    param: "url",
    feature: "script-monitoring",
    about: [
      { title: "Why it matters", body: "Every third-party script can read the page it runs on, including checkout forms. Knowing what is there is the first step of PCI DSS 6.4.3." },
      { title: "A scan is a snapshot", body: "This scan reads the page HTML once. Tag managers add more scripts in the browser. The Stacks Monitor snippet records those too, on every visit, and alerts on changes." },
    ],
  },
];

export const TOOL_BY_SLUG = Object.fromEntries(TOOLS.map((t) => [t.slug, t]));

export const HOME_FAQ = [
  { q: "Who is Stacks Monitor for?", a: "Web agencies and freelancers who look after client websites: maintenance plans, hosting, SEO or ads." },
  { q: "Do I need to install anything on client sites?", a: "Uptime, SSL and domain checks need nothing. Script monitoring, heatmaps and Web Vitals use one small async snippet. WordPress health uses an optional code snippet." },
  { q: "Is client data safe?", a: "Each workspace is fully isolated, vault passwords are encrypted at rest, and every sensitive action is written to an audit log." },
  { q: "Can my whole team use it?", a: "Yes. Invite teammates with owner, manager, developer or viewer roles, or a custom set of sections." },
];
