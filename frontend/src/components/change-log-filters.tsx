"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

/**
 * Filters for the Change Log tab.
 *
 * Drives the server-side query through URL search params rather than filtering
 * an array in the browser: the backend already caps the timeline at 500 rows,
 * so once WordPress activity lands here a client-side filter would be filtering
 * a truncated list and quietly hiding older matches.
 */

const CATEGORIES: { value: string; label: string }[] = [
  { value: "users", label: "Users" },
  { value: "plugins", label: "Plugins" },
  { value: "themes", label: "Themes" },
  { value: "core", label: "Core" },
  { value: "content", label: "Posts & pages" },
  { value: "commerce", label: "WooCommerce" },
  { value: "files", label: "Files" },
  { value: "seo", label: "SEO" },
  { value: "forms", label: "Forms" },
  { value: "discovery", label: "New pages" },
];

export function ChangeLogFilters({ websiteId }: { websiteId: string }) {
  const router = useRouter();
  const params = useSearchParams();

  const active = (params.get("category") ?? "").split(",").filter(Boolean);
  const [search, setSearch] = useState(params.get("q") ?? "");

  const apply = useCallback(
    (next: URLSearchParams) => {
      // The tab lives in the URL too, so it has to survive a filter change or
      // applying a filter would bounce the reader back to Overview.
      next.set("tab", "changelog");
      router.push(`/websites/${websiteId}?${next.toString()}`);
    },
    [router, websiteId]
  );

  function toggleCategory(value: string) {
    const next = new URLSearchParams(params.toString());
    const set = new Set(active);
    if (set.has(value)) {
      set.delete(value);
    } else {
      set.add(value);
    }
    if (set.size) {
      next.set("category", [...set].join(","));
    } else {
      next.delete("category");
    }
    apply(next);
  }

  function submitSearch(e: React.FormEvent) {
    e.preventDefault();
    const next = new URLSearchParams(params.toString());
    if (search.trim()) {
      next.set("q", search.trim());
    } else {
      next.delete("q");
    }
    apply(next);
  }

  function clearAll() {
    setSearch("");
    apply(new URLSearchParams());
  }

  const hasFilters = active.length > 0 || (params.get("q") ?? "") !== "";

  return (
    <div className="flex flex-col gap-3 border-b px-4 py-3">
      <div className="flex flex-wrap items-center gap-1.5">
        {CATEGORIES.map((c) => (
          <button key={c.value} type="button" onClick={() => toggleCategory(c.value)}>
            <Badge
              variant={active.includes(c.value) ? "default" : "outline"}
              className="cursor-pointer text-xs h-6"
            >
              {c.label}
            </Badge>
          </button>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <form onSubmit={submitSearch} className="flex items-center gap-2">
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search descriptions…"
            className="h-8 w-56 text-sm"
            aria-label="Search the change log"
          />
          <Button type="submit" size="sm" variant="secondary" className="h-8">
            Search
          </Button>
        </form>
        {hasFilters && (
          <Button type="button" size="sm" variant="ghost" className="h-8" onClick={clearAll}>
            Clear
          </Button>
        )}
      </div>
    </div>
  );
}
