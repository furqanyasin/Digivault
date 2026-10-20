"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Menu, X } from "lucide-react";
import { NAV_LINKS } from "./nav";

export function MobileMenu() {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();

  // Close when the route changes or Escape is pressed.
  useEffect(() => {
    (async () => {
      await Promise.resolve();
      setOpen(false);
    })();
  }, [pathname]);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [open]);

  return (
    <div className="lg:hidden">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="inline-flex h-10 w-10 items-center justify-center rounded-[var(--radius-btn)] text-[var(--ds-heading)] hover:bg-[var(--accent)]"
        aria-expanded={open}
        aria-controls="mobile-menu"
        aria-label={open ? "Close menu" : "Open menu"}
      >
        {open ? <X className="h-6 w-6" /> : <Menu className="h-6 w-6" />}
      </button>
      {open && (
        <div
          id="mobile-menu"
          className="fixed inset-x-0 bottom-0 top-[var(--header-height)] z-[var(--z-menu)] overflow-y-auto border-t border-[var(--ds-line)] bg-[var(--ds-surface)]"
        >
          <nav className="ds-container flex flex-col gap-1 py-6" aria-label="Mobile">
            {NAV_LINKS.map((l) => (
              <Link
                key={l.href}
                href={l.href}
                className="rounded-[var(--radius-btn)] px-3 py-3 text-lg font-medium text-[var(--ds-heading)] hover:bg-[var(--accent)]"
              >
                {l.label}
              </Link>
            ))}
            <div className="mt-6 grid gap-3">
              <Link href="/signup" className="ds-btn ds-btn-primary ds-btn-lg">Start free</Link>
              <Link href="/login" className="ds-btn ds-btn-outline ds-btn-lg">Log in</Link>
            </div>
          </nav>
        </div>
      )}
    </div>
  );
}
