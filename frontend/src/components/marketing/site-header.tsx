import Link from "next/link";
import { Logo } from "./logo";
import { MobileMenu } from "./mobile-menu";
import { NAV_LINKS } from "./nav";
import { ThemeSwitch } from "./theme-switch";

export function SiteHeader() {
  return (
    <header className="sticky top-0 z-[var(--z-header)] border-b border-[var(--ds-line)] bg-[color-mix(in_oklab,var(--ds-surface)_85%,transparent)] backdrop-blur-md">
      <div className="ds-container-wide flex h-[var(--header-height)] items-center justify-between gap-4">
        <Logo />
        <nav className="hidden items-center gap-1 lg:flex" aria-label="Main">
          {NAV_LINKS.map((l) => (
            <Link
              key={l.href}
              href={l.href}
              className="rounded-[var(--radius-btn)] px-3 py-2 text-[0.9375rem] font-medium text-[var(--ds-text-muted)] transition-colors hover:text-[var(--ds-heading)]"
            >
              {l.label}
            </Link>
          ))}
        </nav>
        <div className="flex items-center gap-1 sm:gap-2">
          <ThemeSwitch />
          <Link href="/login" className="ds-btn ds-btn-ghost ds-btn-sm hidden sm:inline-flex">Log in</Link>
          <Link href="/signup" className="ds-btn ds-btn-primary ds-btn-sm hidden sm:inline-flex">Start free</Link>
          <MobileMenu />
        </div>
      </div>
    </header>
  );
}
