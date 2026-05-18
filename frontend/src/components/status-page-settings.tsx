"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Settings2, Trash2, AlertTriangle } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type { StatusPage } from "@/lib/api";

function slugify(s: string) {
  return s.toLowerCase().trim().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
}

interface Props {
  page: StatusPage;
}

export function StatusPageSettings({ page }: Props) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState("");

  const [name, setName] = useState(page.name);
  const [slug, setSlug] = useState(page.slug);
  const [description, setDescription] = useState(page.description);
  const [allowIndexing, setAllowIndexing] = useState(page.allow_indexing);

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      const res = await fetch(`/api/status-pages/${page.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, slug, description, allow_indexing: allowIndexing }),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        setError(d?.slug?.[0] ?? d?.detail ?? `Error ${res.status}`);
        return;
      }
      setOpen(false);
      router.refresh();
    } finally {
      setLoading(false);
    }
  }

  async function handleDelete() {
    if (!confirm(`Delete status page "${page.name}"? This cannot be undone.`)) return;
    setDeleting(true);
    await fetch(`/api/status-pages/${page.id}`, { method: "DELETE" });
    router.push("/status-pages");
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-3">
        <CardTitle className="text-base flex items-center gap-2">
          <Settings2 className="h-4 w-4" />
          Page settings
        </CardTitle>
        <div className="flex items-center gap-2">
          <Button size="sm" variant="outline" onClick={() => setOpen((v) => !v)}>
            {open ? "Cancel" : "Edit"}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="text-red-500 hover:text-red-600"
            disabled={deleting}
            onClick={handleDelete}
            title="Delete status page"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        {!open ? (
          <dl className="space-y-3 text-sm">
            <div className="flex justify-between gap-4">
              <dt className="text-muted-foreground">Name</dt>
              <dd className="font-medium text-right">{page.name}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-muted-foreground">Slug</dt>
              <dd className="font-mono text-xs">/status/{page.slug}</dd>
            </div>
            {page.description && (
              <div className="flex justify-between gap-4">
                <dt className="text-muted-foreground">Description</dt>
                <dd className="text-right text-xs">{page.description}</dd>
              </div>
            )}
            <div className="flex justify-between gap-4">
              <dt className="text-muted-foreground">Search indexing</dt>
              <dd className={`text-xs font-medium ${page.allow_indexing ? "text-amber-600" : "text-emerald-600"}`}>
                {page.allow_indexing ? "Allowed" : "Blocked (noindex)"}
              </dd>
            </div>
          </dl>
        ) : (
          <form onSubmit={handleSave} className="space-y-4">
            <div className="space-y-2">
              <Label>Name</Label>
              <Input value={name} onChange={(e) => { setName(e.target.value); setSlug(slugify(e.target.value)); }} required />
            </div>
            <div className="space-y-2">
              <Label>Slug <span className="text-xs text-muted-foreground font-normal">— /status/{slug || "…"}</span></Label>
              <Input value={slug} onChange={(e) => setSlug(slugify(e.target.value))} required />
            </div>
            <div className="space-y-2">
              <Label>Description</Label>
              <Textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={2} />
            </div>
            <div className="space-y-2">
              <Label className="flex items-center gap-3 cursor-pointer">
                <input
                  type="checkbox"
                  checked={allowIndexing}
                  onChange={(e) => setAllowIndexing(e.target.checked)}
                  className="h-4 w-4 rounded"
                />
                Allow search engine indexing
              </Label>
              {allowIndexing && (
                <div className="flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
                  <AlertTriangle className="h-3.5 w-3.5 mt-0.5 shrink-0" />
                  This page is currently visible to search engines.
                </div>
              )}
              {!allowIndexing && (
                <p className="text-xs text-muted-foreground">
                  The page will include <code className="bg-muted px-1 rounded">noindex, nofollow</code> tags — recommended for status pages.
                </p>
              )}
            </div>
            {error && <p className="text-sm text-red-600">{error}</p>}
            <div className="flex gap-2">
              <Button type="submit" size="sm" disabled={loading}>{loading ? "Saving…" : "Save changes"}</Button>
              <Button type="button" size="sm" variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
            </div>
          </form>
        )}
      </CardContent>
    </Card>
  );
}
