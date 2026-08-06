"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, HelpCircle, Save } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  ACCESS_LEVEL_OPTIONS, ACCESS_LEVEL_TOOLTIP, DEPARTMENT_OPTIONS,
  HOSTING_OPTIONS, HOSTING_TOOLTIP, TIER_OPTIONS,
} from "@/lib/client-fields";

function Help({ text }: { text: string }) {
  return (
    <HelpCircle
      className="h-3.5 w-3.5 inline-block text-muted-foreground align-text-top ml-1 cursor-help"
      aria-label={text}
    >
      <title>{text}</title>
    </HelpCircle>
  );
}

export default function NewClientPage() {
  const router = useRouter();
  const [form, setForm] = useState({
    name: "", website_url: "", hosting_platform: "", hosting_platform_other: "",
    hosting_renewal_date: "", domain_renewal_date: "", domain_access_location: "",
    website_access_level: "", tier: "",
    running_ppc_ads: "", website_built_by_digi: "", website_maintained_by_digi: "",
    notes: "",
  });
  const [departments, setDepartments] = useState<string[]>([]);
  const [notifyDesktop, setNotifyDesktop] = useState(true);
  const [notifyEmail, setNotifyEmail] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  function set<K extends keyof typeof form>(key: K, val: string) {
    setForm((f) => ({ ...f, [key]: val }));
  }

  function toggleDepartment(dep: string) {
    setDepartments((d) => (d.includes(dep) ? d.filter((x) => x !== dep) : [...d, dep]));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError("");
    try {
      const payload = {
        ...form,
        hosting_platform: form.hosting_platform === "_unknown" ? "" : form.hosting_platform,
        website_access_level: form.website_access_level === "_unknown" ? "" : form.website_access_level,
        tier: form.tier === "_none" ? "" : form.tier,
        hosting_renewal_date: form.hosting_renewal_date || null,
        domain_renewal_date: form.domain_renewal_date || null,
        departments,
        notify_desktop: notifyDesktop,
        notify_email: notifyEmail,
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
          <CardHeader>
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
                <Label>Tier</Label>
                <Select value={form.tier} onValueChange={(v) => set("tier", v)}>
                  <SelectTrigger><SelectValue placeholder="Select…" /></SelectTrigger>
                  <SelectContent>{TIER_OPTIONS.map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}</SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label>
                  Hosting platform
                  <Help text={HOSTING_TOOLTIP} />
                </Label>
                <Select value={form.hosting_platform} onValueChange={(v) => set("hosting_platform", v)}>
                  <SelectTrigger><SelectValue placeholder="Select…" /></SelectTrigger>
                  <SelectContent>{HOSTING_OPTIONS.map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}</SelectContent>
                </Select>
              </div>
              {form.hosting_platform === "other" && (
                <div className="space-y-1.5">
                  <Label>Hosting platform name</Label>
                  <Input
                    value={form.hosting_platform_other}
                    onChange={(e) => set("hosting_platform_other", e.target.value)}
                    placeholder="e.g. Krystal, Kinsta…"
                  />
                </div>
              )}
              <div className="space-y-1.5">
                <Label>
                  Website access level
                  <Help text={ACCESS_LEVEL_TOOLTIP} />
                </Label>
                <Select value={form.website_access_level} onValueChange={(v) => set("website_access_level", v)}>
                  <SelectTrigger><SelectValue placeholder="Select…" /></SelectTrigger>
                  <SelectContent>{ACCESS_LEVEL_OPTIONS.map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}</SelectContent>
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
                <Label>Domain renewal date</Label>
                <Input type="date" value={form.domain_renewal_date} onChange={(e) => set("domain_renewal_date", e.target.value)} />
              </div>
              <div className="space-y-1.5">
                <Label>Website built by Digilatics</Label>
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
                <Label>Website maintained by Digilatics</Label>
                <Select value={form.website_maintained_by_digi} onValueChange={(v) => set("website_maintained_by_digi", v)}>
                  <SelectTrigger><SelectValue placeholder="Select…" /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="unknown">Unknown</SelectItem>
                    <SelectItem value="YES">Yes</SelectItem>
                    <SelectItem value="NO">No</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="space-y-1.5">
              <Label>Departments working on this client</Label>
              <div className="flex flex-wrap gap-3 pt-1">
                {DEPARTMENT_OPTIONS.map((d) => (
                  <label key={d.value} className="flex items-center gap-1.5 text-sm cursor-pointer">
                    <input
                      type="checkbox"
                      checked={departments.includes(d.value)}
                      onChange={() => toggleDepartment(d.value)}
                      className="h-4 w-4 rounded border-input"
                    />
                    {d.label}
                  </label>
                ))}
              </div>
            </div>
            <div className="space-y-1.5">
              <Label>Notifications</Label>
              <div className="flex flex-wrap gap-4 pt-1">
                <label className="flex items-center gap-1.5 text-sm cursor-pointer">
                  <input
                    type="checkbox"
                    checked={notifyDesktop}
                    onChange={(e) => setNotifyDesktop(e.target.checked)}
                    className="h-4 w-4 rounded border-input"
                  />
                  Desktop notifications
                </label>
                <label className="flex items-center gap-1.5 text-sm cursor-pointer">
                  <input
                    type="checkbox"
                    checked={notifyEmail}
                    onChange={(e) => setNotifyEmail(e.target.checked)}
                    className="h-4 w-4 rounded border-input"
                  />
                  Email notifications
                </label>
              </div>
            </div>
            <div className="space-y-1.5">
              <Label>Notes</Label>
              <Textarea value={form.notes} onChange={(e) => set("notes", e.target.value)} rows={3} />
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
