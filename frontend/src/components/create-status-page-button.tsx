"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

function slugify(s: string) {
  return s
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

interface Props {
  className?: string;
}

export function CreateStatusPageButton({ className }: Props) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [description, setDescription] = useState("");

  function handleNameChange(v: string) {
    setName(v);
    setSlug(slugify(v));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await fetch("/api/status-pages", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, slug, description }),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        setError(d?.slug?.[0] ?? d?.detail ?? `Error ${res.status}`);
        return;
      }
      const page = await res.json();
      setOpen(false);
      router.push(`/status-pages/${page.id}`);
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <Button className={className} onClick={() => setOpen(true)}>
        <Plus className="h-4 w-4 mr-2" />
        New status page
      </Button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Create status page</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="sp-name">Name</Label>
              <Input
                id="sp-name"
                value={name}
                onChange={(e) => handleNameChange(e.target.value)}
                placeholder="My Service Status"
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="sp-slug">
                Slug
                <span className="ml-1 text-xs text-muted-foreground font-normal">
                  — public URL: /status/{slug || "my-service"}
                </span>
              </Label>
              <Input
                id="sp-slug"
                value={slug}
                onChange={(e) => setSlug(slugify(e.target.value))}
                placeholder="my-service"
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="sp-desc">Description <span className="text-muted-foreground font-normal">(optional)</span></Label>
              <Textarea
                id="sp-desc"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Real-time status of our services"
                rows={2}
              />
            </div>
            {error && <p className="text-sm text-red-600">{error}</p>}
            <DialogFooter>
              <Button type="button" variant="ghost" onClick={() => setOpen(false)}>Cancel</Button>
              <Button type="submit" disabled={loading || !name || !slug}>
                {loading ? "Creating…" : "Create"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );
}
