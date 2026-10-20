"use client";

import { useTheme } from "next-themes";
import { Moon, Sun } from "lucide-react";
import { useEffect, useState } from "react";

// Compact light/dark switch for the website header.
export function ThemeSwitch() {
  const { resolvedTheme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    (async () => {
      await Promise.resolve();
      setMounted(true);
    })();
  }, []);

  const dark = mounted && resolvedTheme === "dark";
  return (
    <button
      type="button"
      onClick={() => setTheme(dark ? "light" : "dark")}
      className="inline-flex h-10 w-10 items-center justify-center rounded-[var(--radius-btn)] text-[var(--ds-text-muted)] transition-colors hover:bg-[var(--accent)] hover:text-[var(--accent-foreground)]"
      aria-label={dark ? "Switch to light mode" : "Switch to dark mode"}
      title={dark ? "Light mode" : "Dark mode"}
    >
      {/* Both icons render on the server; CSS shows the right one before JS. */}
      <Sun className="hidden h-5 w-5 dark:block" aria-hidden />
      <Moon className="h-5 w-5 dark:hidden" aria-hidden />
    </button>
  );
}
