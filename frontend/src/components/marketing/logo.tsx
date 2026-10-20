import Link from "next/link";
import { PRODUCT_NAME } from "@/lib/brand";

// Inline SVG (same paths as /stacksmonitor-icon.svg) so the header needs no
// extra request and the mark is crisp at any size.
export function LogoMark({ className = "h-7 w-7" }: { className?: string }) {
  return (
    <svg viewBox="0 0 64 64" className={className} aria-hidden fill="none">
      <path d="M32 6 58 19 32 32 6 19Z" fill="#7678ED" />
      <path d="M6 31 32 44 58 31" stroke="#7678ED" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M6 43 32 56 58 43" stroke="#7678ED" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round" opacity="0.6" />
    </svg>
  );
}

export function Logo() {
  return (
    <Link href="/" className="flex items-center gap-2.5" aria-label={`${PRODUCT_NAME} home`}>
      <LogoMark />
      <span className="font-display text-lg font-bold tracking-tight text-[var(--ds-heading)]">{PRODUCT_NAME}</span>
    </Link>
  );
}
