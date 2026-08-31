"use client";

import { useTheme } from "next-themes";
import { Sun, Moon, Monitor } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useEffect, useState } from "react";

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  // The theme is unknown until next-themes has read localStorage, so the first
  // paint has to render nothing or it hydrates against the wrong icon. The
  // microtask defers the flag out of the effect body — setting it synchronously
  // there cascades a second render pass (react-hooks/set-state-in-effect).
  useEffect(() => {
    (async () => {
      await Promise.resolve();
      setMounted(true);
    })();
  }, []);
  if (!mounted) return null;

  const next = theme === "dark" ? "light" : theme === "light" ? "system" : "dark";
  const Icon = theme === "dark" ? Moon : theme === "light" ? Sun : Monitor;
  const label = theme === "dark" ? "Dark" : theme === "light" ? "Light" : "System";

  return (
    <Button
      variant="ghost"
      size="sm"
      className="w-full justify-start gap-2 text-muted-foreground hover:text-foreground"
      onClick={() => setTheme(next)}
      title={`Switch theme (currently ${label})`}
    >
      <Icon className="h-4 w-4" />
      {label}
    </Button>
  );
}
