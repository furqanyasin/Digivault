import type { Metadata } from "next";
import { ShieldCheck, Globe, Terminal } from "lucide-react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type MonitoringInfo = {
  user_agent: string;
  egress_ips: string[];
  allowlist: Record<string, string>;
  docs: string;
};

export const metadata: Metadata = {
  title: "Stacks Monitor Bot — Allowlist Information",
  description:
    "The IP addresses and user-agent Stacks Monitor's uptime monitor uses, with copy-paste firewall rules.",
  robots: "index, follow",
};

// This page is where the `+URL` in our user-agent points. Anyone reading it is
// most likely looking at a firewall log right now and wants two facts and a
// rule they can paste — so it stays a static, unauthenticated, no-JS page.
async function getInfo(): Promise<MonitoringInfo | null> {
  try {
    const res = await fetch(`${API_BASE}/api/v1/monitoring-info/`, {
      next: { revalidate: 3600 },
    });
    // An error answer is JSON too ({data: null, errors: [...]}); rendered as
    // info it crashed the prerender, and with it `next build`.
    if (!res.ok) return null;
    const envelope = await res.json();
    return (envelope?.data ?? null) as MonitoringInfo | null;
  } catch {
    return null;
  }
}

const VENDOR_LABELS: Record<string, string> = {
  cloudflare: "Cloudflare",
  wordfence: "Wordfence (WordPress)",
  sucuri: "Sucuri Firewall",
  htaccess: "Apache .htaccess",
};

export default async function BotInfoPage() {
  const info = await getInfo();

  if (!info) {
    return (
      <main className="mx-auto max-w-3xl px-6 py-16">
        <h1 className="text-2xl font-semibold">Stacks Monitor Bot</h1>
        <p className="mt-4 text-muted-foreground">
          Monitoring details are temporarily unavailable. Please contact the
          agency that manages your website.
        </p>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-3xl px-6 py-16">
      <div className="flex items-center gap-3">
        <ShieldCheck className="h-7 w-7 text-emerald-600" aria-hidden />
        <h1 className="text-2xl font-semibold">Stacks Monitor Bot</h1>
      </div>

      <p className="mt-4 text-muted-foreground">{info.docs}</p>

      <section className="mt-10">
        <h2 className="flex items-center gap-2 text-lg font-medium">
          <Globe className="h-5 w-5" aria-hidden />
          Who we are
        </h2>
        <dl className="mt-4 space-y-4">
          <div>
            <dt className="text-sm font-medium text-muted-foreground">
              User agent
            </dt>
            <dd className="mt-1 overflow-x-auto rounded-md bg-muted p-3 font-mono text-sm">
              {info.user_agent}
            </dd>
          </div>
          <div>
            <dt className="text-sm font-medium text-muted-foreground">
              Source IP {info.egress_ips.length === 1 ? "address" : "addresses"}
            </dt>
            <dd className="mt-1 overflow-x-auto rounded-md bg-muted p-3 font-mono text-sm">
              {info.egress_ips.length > 0
                ? info.egress_ips.join(", ")
                : "Contact your agency for the current monitoring IP."}
            </dd>
          </div>
        </dl>
      </section>

      <section className="mt-10">
        <h2 className="flex items-center gap-2 text-lg font-medium">
          <Terminal className="h-5 w-5" aria-hidden />
          Allowlist rules
        </h2>
        <p className="mt-2 text-sm text-muted-foreground">
          Adding any one of these restores uptime coverage. Your website is not
          affected either way — a blocked check is reported as “blocked”, never
          as downtime.
        </p>
        <div className="mt-4 space-y-6">
          {Object.entries(info.allowlist).map(([vendor, rule]) => (
            <div key={vendor}>
              <h3 className="text-sm font-semibold">
                {VENDOR_LABELS[vendor] ?? vendor}
              </h3>
              <pre className="mt-2 overflow-x-auto rounded-md bg-muted p-3 font-mono text-xs whitespace-pre-wrap">
                {rule}
              </pre>
            </div>
          ))}
        </div>
      </section>

      <section className="mt-10 rounded-md border p-4">
        <h2 className="text-base font-medium">What this monitor does</h2>
        <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-muted-foreground">
          <li>
            Sends one HTTP request to your homepage on a schedule, usually every
            15 minutes.
          </li>
          <li>
            Prefers <code className="font-mono">HEAD</code> requests, which
            transfer no page content.
          </li>
          <li>Never submits forms, never logs in, never crawls your site.</li>
          <li>
            Honours <code className="font-mono">Retry-After</code> and backs off
            after a rate-limit response.
          </li>
        </ul>
      </section>
    </main>
  );
}
