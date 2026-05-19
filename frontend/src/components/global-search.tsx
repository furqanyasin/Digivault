"use client";

import { useState, useRef, useEffect } from "react";
import { Search, Globe, Users } from "lucide-react";
import { useRouter } from "next/navigation";

interface SearchResult {
  id: string;
  label: string;
  sub: string;
  href: string;
  type: "website" | "client";
}

export function GlobalSearch() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const router = useRouter();
  const ref = useRef<HTMLDivElement>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        document.getElementById("global-search-input")?.focus();
      }
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  function onInput(q: string) {
    setQuery(q);
    clearTimeout(timerRef.current);
    if (!q.trim()) { setResults([]); setOpen(false); return; }
    timerRef.current = setTimeout(async () => {
      setLoading(true);
      try {
        const [wsRes, clRes] = await Promise.allSettled([
          fetch(`/api/websites`).then((r) => r.json()),
          fetch(`/api/clients/search?q=${encodeURIComponent(q)}`).then((r) => r.json()),
        ]);
        const websites: { id: string; name: string; domain: string }[] =
          wsRes.status === "fulfilled" ? (Array.isArray(wsRes.value) ? wsRes.value : []) : [];
        const clients: { id: string; name: string; domain: string }[] =
          clRes.status === "fulfilled" ? (Array.isArray(clRes.value) ? clRes.value : clRes.value?.results ?? []) : [];

        const ql = q.toLowerCase();
        const items: SearchResult[] = [
          ...websites
            .filter((w) => w.domain?.toLowerCase().includes(ql) || w.name?.toLowerCase().includes(ql))
            .slice(0, 5)
            .map((w) => ({ id: w.id, label: w.name || w.domain, sub: w.domain, href: `/websites/${w.id}`, type: "website" as const })),
          ...clients
            .slice(0, 5)
            .map((c) => ({ id: c.id, label: c.name, sub: c.domain || "", href: `/clients/${c.id}`, type: "client" as const })),
        ];
        setResults(items);
        setOpen(items.length > 0);
      } finally {
        setLoading(false);
      }
    }, 200);
  }

  function go(href: string) {
    setQuery("");
    setResults([]);
    setOpen(false);
    router.push(href);
  }

  return (
    <div ref={ref} className="relative px-3 py-2">
      <div className="flex items-center gap-2 bg-muted/60 rounded-md px-3 py-1.5 border border-border/50 focus-within:border-primary/50 focus-within:bg-background transition-colors">
        <Search className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
        <input
          id="global-search-input"
          value={query}
          onChange={(e) => onInput(e.target.value)}
          onFocus={() => results.length > 0 && setOpen(true)}
          placeholder="Search…"
          className="flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground min-w-0"
          autoComplete="off"
        />
        <kbd className="hidden sm:inline text-[10px] text-muted-foreground border rounded px-1 py-0.5 bg-muted">⌘K</kbd>
      </div>

      {open && (
        <div className="absolute left-3 right-3 top-full mt-1 z-50 bg-popover border rounded-md shadow-lg overflow-hidden">
          {loading && <div className="px-3 py-2 text-xs text-muted-foreground">Searching…</div>}
          {!loading && results.map((r) => (
            <button
              key={r.id}
              onClick={() => go(r.href)}
              className="w-full flex items-center gap-2 px-3 py-2 text-sm hover:bg-accent transition-colors text-left"
            >
              {r.type === "website"
                ? <Globe className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                : <Users className="h-3.5 w-3.5 text-muted-foreground shrink-0" />}
              <div className="min-w-0">
                <p className="font-medium truncate">{r.label}</p>
                {r.sub && <p className="text-xs text-muted-foreground font-mono truncate">{r.sub}</p>}
              </div>
              <span className="ml-auto text-xs text-muted-foreground shrink-0 capitalize">{r.type}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
