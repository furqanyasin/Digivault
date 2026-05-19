"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle,
} from "@/components/ui/card";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { useToast } from "@/hooks/use-toast";

interface ClientOption {
  id: string;
  name: string;
  website_url: string;
}

const NO_CLIENT = "__none__";

export default function NewWebsitePage() {
  const router = useRouter();
  const { toast } = useToast();
  const [loading, setLoading] = useState(false);
  const [form, setForm] = useState({ domain: "", name: "", client: NO_CLIENT });
  const [clients, setClients] = useState<ClientOption[]>([]);

  useEffect(() => {
    fetch("/api/clients?page_size=500")
      .then((r) => r.json())
      .then((data) => {
        const list = Array.isArray(data) ? data : (data.clients ?? data.results ?? []);
        setClients(list);
      })
      .catch(() => {});
  }, []);

  // Auto-fill domain from selected client
  function handleClientChange(clientId: string) {
    setForm((f) => {
      if (clientId === NO_CLIENT) return { ...f, client: NO_CLIENT };
      const c = clients.find((c) => c.id === clientId);
      if (!c) return { ...f, client: clientId };
      const domain = c.website_url.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "");
      return {
        ...f,
        client: clientId,
        domain: domain || f.domain,
        name: f.name || c.name,
      };
    });
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    try {
      const body: Record<string, string> = {
        domain: form.domain,
        name: form.name || form.domain,
      };
      if (form.client !== NO_CLIENT) body.client = form.client;

      const res = await fetch("/api/websites", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) {
        const msg =
          data?.errors?.map((e: { message: string }) => e.message).join(" ") ||
          data?.detail ||
          "Failed to create website";
        toast({ variant: "destructive", title: "Error", description: msg });
        return;
      }
      toast({ title: "Website added", description: `Now monitoring ${form.domain}` });
      router.push("/websites");
    } catch {
      toast({ variant: "destructive", title: "Network error" });
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="p-8 max-w-lg">
      <h1 className="text-3xl font-bold tracking-tight mb-6">Add website</h1>
      <Card>
        <CardHeader>
          <CardTitle>Website details</CardTitle>
          <CardDescription>
            Enter the domain you want to monitor. Optionally link it to a client.
          </CardDescription>
        </CardHeader>
        <form onSubmit={handleSubmit}>
          <CardContent className="space-y-4">
            {/* Client selector */}
            <div className="space-y-2">
              <Label htmlFor="client">Link to client (optional)</Label>
              <Select value={form.client} onValueChange={handleClientChange}>
                <SelectTrigger id="client">
                  <SelectValue placeholder="Select a client…" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={NO_CLIENT}>— No client —</SelectItem>
                  {clients.map((c) => (
                    <SelectItem key={c.id} value={c.id}>
                      {c.name}
                      {c.website_url ? (
                        <span className="ml-1 text-muted-foreground text-xs">
                          ({c.website_url})
                        </span>
                      ) : null}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground">
                Selecting a client auto-fills the domain below.
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="domain">Domain</Label>
              <Input
                id="domain"
                placeholder="example.com"
                required
                value={form.domain}
                onChange={(e) => setForm((f) => ({ ...f, domain: e.target.value }))}
              />
              <p className="text-xs text-muted-foreground">Just the domain, no https://</p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="name">Display name (optional)</Label>
              <Input
                id="name"
                placeholder="My Company Site"
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              />
            </div>
          </CardContent>
          <CardFooter className="gap-3">
            <Button type="submit" disabled={loading}>
              {loading ? "Adding…" : "Add website"}
            </Button>
            <Button type="button" variant="outline" onClick={() => router.back()}>
              Cancel
            </Button>
          </CardFooter>
        </form>
      </Card>
    </div>
  );
}
