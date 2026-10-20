import { Activity, FileCode2, KeyRound, LockKeyhole } from "lucide-react";

// Decorative product preview for the hero, drawn in HTML so it costs no image
// request and follows light/dark mode. Sample data only.
const ROWS = [
  { site: "brightsmile-dental.com", uptime: "99.98%", ssl: "84 days", scripts: "12", state: "up" },
  { site: "northfield-law.co.uk", uptime: "100%", ssl: "61 days", scripts: "8", state: "up" },
  { site: "urbanbrew.coffee", uptime: "99.41%", ssl: "6 days", scripts: "15", state: "warn" },
  { site: "kitchenpro-shop.com", uptime: "97.20%", ssl: "203 days", scripts: "+1 new", state: "down" },
  { site: "greenleaf-yoga.com", uptime: "99.99%", ssl: "45 days", scripts: "6", state: "up" },
];

const DOT: Record<string, string> = {
  up: "bg-emerald-500",
  warn: "bg-amber-500",
  down: "bg-red-500",
};

export function DashboardPreview() {
  return (
    <div aria-hidden className="relative">
      <div className="absolute -inset-4 rounded-[2rem] bg-[var(--ds-hero-glow)] blur-2xl" />
      <div className="relative overflow-hidden rounded-[var(--radius-panel)] border border-[var(--ds-line)] bg-[var(--ds-surface-raised)] shadow-[var(--shadow-panel)]">
        <div className="flex items-center gap-1.5 border-b border-[var(--ds-line)] px-4 py-3">
          <span className="h-2.5 w-2.5 rounded-full bg-red-400" />
          <span className="h-2.5 w-2.5 rounded-full bg-amber-400" />
          <span className="h-2.5 w-2.5 rounded-full bg-emerald-400" />
          <span className="ml-3 truncate text-caption text-[var(--ds-text-muted)]">stacksmonitor.com/dashboard</span>
        </div>
        <div className="grid grid-cols-2 gap-3 p-4 sm:grid-cols-4">
          {[
            { icon: Activity, label: "Sites up", value: "47 / 48" },
            { icon: LockKeyhole, label: "SSL expiring", value: "2" },
            { icon: FileCode2, label: "New scripts", value: "3" },
            { icon: KeyRound, label: "Vault logins", value: "312" },
          ].map(({ icon: Icon, label, value }) => (
            <div key={label} className="rounded-[var(--radius-card)] border border-[var(--ds-line)] p-3">
              <Icon className="h-4 w-4 text-[var(--primary)]" />
              <p className="mt-2 font-display text-lg font-bold text-[var(--ds-heading)] dv-num">{value}</p>
              <p className="text-caption text-[var(--ds-text-muted)]">{label}</p>
            </div>
          ))}
        </div>
        <div className="px-4 pb-4">
          <div className="overflow-hidden rounded-[var(--radius-card)] border border-[var(--ds-line)]">
            <div className="grid grid-cols-[1.6fr_1fr_1fr] gap-2 bg-[var(--ds-surface-sunken)] px-3 py-2 text-caption font-semibold text-[var(--ds-text-muted)] sm:grid-cols-[1.6fr_1fr_1fr_0.8fr]">
              <span>Website</span><span>Uptime 30d</span><span>SSL</span><span className="hidden sm:block">Scripts</span>
            </div>
            {ROWS.map((r) => (
              <div key={r.site} className="grid grid-cols-[1.6fr_1fr_1fr] items-center gap-2 border-t border-[var(--ds-line)] px-3 py-2.5 text-small sm:grid-cols-[1.6fr_1fr_1fr_0.8fr]">
                <span className="flex min-w-0 items-center gap-2">
                  <span className={`h-2 w-2 shrink-0 rounded-full ${DOT[r.state]}`} />
                  <span className="truncate text-[var(--ds-heading)]">{r.site}</span>
                </span>
                <span className="dv-num text-[var(--ds-text-muted)]">{r.uptime}</span>
                <span className={`dv-num ${r.state === "warn" ? "font-semibold text-amber-600 dark:text-amber-400" : "text-[var(--ds-text-muted)]"}`}>{r.ssl}</span>
                <span className={`hidden dv-num sm:block ${r.state === "down" ? "font-semibold text-red-600 dark:text-red-400" : "text-[var(--ds-text-muted)]"}`}>{r.scripts}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
