"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, Save } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";

const HOSTING_OPTIONS = [
  { value: "_unknown", label: "Unknown" }, { value: "wpengine", label: "WPEngine" },
  { value: "siteground", label: "SiteGround" }, { value: "cloudways", label: "Cloudways" },
  { value: "bluehost", label: "Bluehost" }, { value: "godaddy", label: "GoDaddy" },
  { value: "squarespace", label: "Squarespace" }, { value: "wix", label: "Wix" },
  { value: "shopify", label: "Shopify" }, { value: "other", label: "Other" },
];

export default function NewClientPage() {
  const router = useRouter();
  const [form, setForm] = useState({
    name: "", website_url: "", hosting_platform: "",
    hosting_renewal_date: "", contract_renewal_date: "", domain_access_location: "",
    migration_status: "", csm_migration_confirmation: "",
    running_ppc_ads: "", website_built_by_digi: "", website_maintained_by_digi: "",
    notes: "", comments: "", clickup_task_id: "",
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  function set<K extends keyof typeof form>(key: K, val: string) {
    setForm((f) => ({ ...f, [key]: val }));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError("");
    try {
      const payload = {
        ...form,
        hosting_platform: form.hosting_platform === "_unknown" ? "" : form.hosting_platform,
        hosting_renewal_date: form.hosting_renewal_date || null,
        contract_renewal_date: form.contract_renewal_date || null,
      };
      const res = await fetch("/api/clients", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) { setError(data?.detail ?? "Failed to create client."); return; }
      router.push(`/clients/${data.id}`);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="p-8 space-y-6 max-w-3xl">
      <div className="flex items-center gap-3">
        <Link href="/clients" className="text-muted-foreground hover:text-foreground">
          <ArrowLeft className="h-5 w-5" />
        </Link>
        <h1 className="text-2xl font-bold tracking-tight">Add new client</h1>
      </div>
      <form onSubmit={handleSubmit}>
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Client details</CardTitle>
          </CardHeader>
          <CardContent className="space-y-5">
            <div className="grid sm:grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <Label>Client name *</Label>
                <Input value={form.name} onChange={(e) => set("name", e.target.value)} required />
              </div>
              <div className="space-y-1.5">
                <Label>Website URL</Label>
                <Input value={form.website_url} onChange={(e) => set("website_url", e.target.value)} placeholder="example.com" />
              </div>
              <div className="space-y-1.5">
                <Label>Hosting platform</Label>
                <Select value={form.hosting_platform} onValueChange={(v) => set("hosting_platform", v)}>
                  <SelectTrigger><SelectValue placeholder="Select…" /></SelectTrigger>
                  <SelectContent>{HOSTING_OPTIONS.map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}</SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label>Domain access location</Label>
                <Input value={form.domain_access_location} onChange={(e) => set("domain_access_location", e.target.value)} placeholder="e.g. Khurram GoDaddy Account" />
              </div>
              <div className="space-y-1.5">
                <Label>Hosting renewal date</Label>
                <Input type="date" value={form.hosting_renewal_date} onChange={(e) => set("hosting_renewal_date", e.target.value)} />
              </div>
              <div className="space-y-1.5">
                <Label>Contract renewal date</Label>
                <Input type="date" value={form.contract_renewal_date} onChange={(e) => set("contract_renewal_date", e.target.value)} />
              </div>
              <div className="space-y-1.5">
                <Label>Website built by Digi</Label>
                <Select value={form.website_built_by_digi} onValueChange={(v) => set("website_built_by_digi", v)}>
                  <SelectTrigger><SelectValue placeholder="Select…" /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="unknown">Unknown</SelectItem>
                    <SelectItem value="YES">Yes</SelectItem>
                    <SelectItem value="NO">No</SelectItem>
                    <SelectItem value="Hosting">Hosting only</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label>Website maintained by Digi</Label>
                <Select value={form.website_maintained_by_digi} onValueChange={(v) => set("website_maintained_by_digi", v)}>
                  <SelectTrigger><SelectValue placeholder="Select…" /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="unknown">Unknown</SelectItem>
                    <SelectItem value="YES">Yes</SelectItem>
                    <SelectItem value="NO">No</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label>ClickUp task ID</Label>
                <Input value={form.clickup_task_id} onChange={(e) => set("clickup_task_id", e.target.value)} placeholder="e.g. 86evnnba3" className="font-mono text-sm" />
              </div>
            </div>
            <div className="space-y-1.5">
              <Label>Notes</Label>
              <Textarea value={form.notes} onChange={(e) => set("notes", e.target.value)} rows={3} />
            </div>
            <div className="space-y-1.5">
              <Label>Comments</Label>
              <Textarea value={form.comments} onChange={(e) => set("comments", e.target.value)} rows={3} />
            </div>
            {error && <p className="text-sm text-red-600">{error}</p>}
            <div className="flex gap-2 pt-2">
              <Button type="submit" disabled={saving}>
                <Save className="h-4 w-4 mr-1" />{saving ? "Saving…" : "Create client"}
              </Button>
              <Button type="button" variant="outline" onClick={() => router.push("/clients")}>Cancel</Button>
            </div>
          </CardContent>
        </Card>
      </form>
    </div>
  );
}
