"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, HelpCircle, Save } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import type { ClientRecord } from "@/app/(dashboard)/clients/page";
import { fmtDateTime } from "@/lib/utils";
import {
  ACCESS_LEVEL_OPTIONS, ACCESS_LEVEL_TOOLTIP, DEPARTMENT_OPTIONS,
  HOSTING_OPTIONS, HOSTING_TOOLTIP, STATUS_OPTIONS, TIER_OPTIONS,
} from "@/lib/client-fields";

const DIGI_OPTIONS = [
  { value: "unknown", label: "Unknown" },
  { value: "YES", label: "Yes" },
  { value: "NO", label: "No" },
  { value: "Hosting", label: "Hosting only" },
];

const STATUS_BADGE: Record<string, "success" | "warning" | "secondary"> = {
  active: "success",
  paused: "warning",
  offboarded: "secondary",
};

interface Props {
  client: ClientRecord;
}

export function ClientDetailClient({ client: initial }: Props) {
  const router = useRouter();
  const [, startTransition] = useTransition();

  const toSelect = (v: string) => v || "_unknown";
  const fromSelect = (v: string) => v === "_unknown" ? "" : v;

  const [form, setForm] = useState({
    name: initial.name,
    website_url: initial.website_url,
    status: initial.status,
    tier: initial.tier || "_none",
    hosting_platform: toSelect(initial.hosting_platform),
    hosting_platform_other: initial.hosting_platform_other ?? "",
    hosting_renewal_date: initial.hosting_renewal_date ?? "",
    domain_renewal_date: initial.domain_renewal_date ?? "",
    domain_access_location: initial.domain_access_location,
    website_access_level: toSelect(initial.website_access_level ?? ""),
    running_ppc_ads: initial.running_ppc_ads,
    website_built_by_digi: initial.website_built_by_digi || "unknown",
    website_maintained_by_digi: initial.website_maintained_by_digi || "unknown",
    notes: initial.notes,
  });
  const [departments, setDepartments] = useState<string[]>(initial.departments ?? []);
  const [notifyDesktop, setNotifyDesktop] = useState(initial.notify_desktop ?? true);
  const [notifyEmail, setNotifyEmail] = useState(initial.notify_email ?? true);

  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState("");
  const [saveError, setSaveError] = useState("");

  function refresh() {
    startTransition(() => router.refresh());
  }

  function set<K extends keyof typeof form>(key: K, val: string) {
    setForm((f) => ({ ...f, [key]: val }));
  }

  function toggleDepartment(dep: string) {
    setDepartments((d) => (d.includes(dep) ? d.filter((x) => x !== dep) : [...d, dep]));
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setSaveMsg("");
    setSaveError("");
    try {
      const payload = {
        ...form,
        tier: form.tier === "_none" ? "" : form.tier,
        hosting_platform: fromSelect(form.hosting_platform),
        website_access_level: fromSelect(form.website_access_level),
        // An empty <input type="date"> yields "" — DRF's DateField rejects that;
        // send null so it clears the field instead of erroring.
        hosting_renewal_date: form.hosting_renewal_date || null,
        domain_renewal_date: form.domain_renewal_date || null,
        website_built_by_digi: form.website_built_by_digi === "unknown" ? "" : form.website_built_by_digi,
        website_maintained_by_digi: form.website_maintained_by_digi === "unknown" ? "" : form.website_maintained_by_digi,
        departments,
        notify_desktop: notifyDesktop,
        notify_email: notifyEmail,
      };
      const res = await fetch(`/api/clients/${initial.id}/`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) {
        // Surface the real reason: { detail } or the envelope's first error message.
        setSaveError(data?.detail || data?.errors?.[0]?.message || "Save failed.");
        return;
      }
      setSaveMsg("Saved successfully.");
      refresh();
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
        <div className="flex-1">
          <h1 className="text-2xl font-bold tracking-tight">{initial.name}</h1>
          <p className="text-muted-foreground text-sm">{initial.website_url}</p>
        </div>
        <Badge variant={STATUS_BADGE[form.status] ?? "secondary"} className="capitalize">{form.status}</Badge>
        {form.tier !== "_none" && (
          <Badge variant="outline" className="capitalize">{form.tier}</Badge>
        )}
      </div>

      <form onSubmit={handleSave}>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Client details</CardTitle>
          </CardHeader>
          <CardContent className="space-y-5">
            <div className="grid sm:grid-cols-2 gap-4">
              <Field label="Client name *">
                <Input value={form.name} onChange={(e) => set("name", e.target.value)} required />
              </Field>
              <Field label="Website URL">
                <Input value={form.website_url} onChange={(e) => set("website_url", e.target.value)} placeholder="example.com" />
              </Field>
              <Field label="Status">
                <SelectField value={form.status} onChange={(v) => set("status", v)} options={STATUS_OPTIONS} />
              </Field>
              <Field label="Tier">
                <SelectField value={form.tier} onChange={(v) => set("tier", v)} options={TIER_OPTIONS} />
              </Field>
              <Field label="Hosting platform" help={HOSTING_TOOLTIP}>
                <SelectField value={form.hosting_platform} onChange={(v) => set("hosting_platform", v)} options={HOSTING_OPTIONS} />
              </Field>
              {form.hosting_platform === "other" && (
                <Field label="Hosting platform name">
                  <Input
                    value={form.hosting_platform_other}
                    onChange={(e) => set("hosting_platform_other", e.target.value)}
                    placeholder="e.g. Krystal, Kinsta…"
                  />
                </Field>
              )}
              <Field label="Website access level" help={ACCESS_LEVEL_TOOLTIP}>
                <SelectField value={form.website_access_level} onChange={(v) => set("website_access_level", v)} options={ACCESS_LEVEL_OPTIONS} />
              </Field>
              <Field label="Hosting renewal date">
                <Input type="date" value={form.hosting_renewal_date} onChange={(e) => set("hosting_renewal_date", e.target.value)} />
              </Field>
              <Field label="Domain renewal date">
                <Input type="date" value={form.domain_renewal_date} onChange={(e) => set("domain_renewal_date", e.target.value)} />
              </Field>
              <Field label="Domain access location">
                <Input
                  value={form.domain_access_location}
                  onChange={(e) => set("domain_access_location", e.target.value)}
                  placeholder="e.g. Khurram GoDaddy Account"
                />
              </Field>
              <Field label="Website built by Digi">
                <SelectField value={form.website_built_by_digi} onChange={(v) => set("website_built_by_digi", v)} options={DIGI_OPTIONS} />
              </Field>
              <Field label="Website maintained by Digi">
                <SelectField value={form.website_maintained_by_digi} onChange={(v) => set("website_maintained_by_digi", v)} options={DIGI_OPTIONS} />
              </Field>
            </div>

            <Field label="Departments working on this client">
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
            </Field>

            <Field label="Notifications">
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
            </Field>

            <Field label="Notes">
              <Textarea value={form.notes} onChange={(e) => set("notes", e.target.value)} rows={3} placeholder="Internal notes…" />
            </Field>

            {saveError && <p className="text-sm text-red-600">{saveError}</p>}
            {saveMsg && <p className="text-sm text-emerald-700">{saveMsg}</p>}

            <div className="flex gap-2 pt-2">
              <Button type="submit" disabled={saving}>
                <Save className="h-4 w-4 mr-1" />
                {saving ? "Saving…" : "Save changes"}
              </Button>
              <Button type="button" variant="outline" onClick={() => router.push("/clients")}>
                Cancel
              </Button>
            </div>
          </CardContent>
        </Card>
      </form>

      {/* Metadata */}
      <Card>
        <CardContent className="grid sm:grid-cols-2 gap-2 text-xs text-muted-foreground">
          <span>Created: {fmtDateTime(initial.created_at)}</span>
          <span>Updated: {fmtDateTime(initial.updated_at)}</span>
        </CardContent>
      </Card>
    </div>
  );
}

function Field({ label, help, children }: { label: string; help?: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <Label>
        {label}
        {help && (
          <HelpCircle className="h-3.5 w-3.5 inline-block text-muted-foreground align-text-top ml-1 cursor-help" aria-label={help}>
            <title>{help}</title>
          </HelpCircle>
        )}
      </Label>
      {children}
    </div>
  );
}

function SelectField({
  value, onChange, options,
}: {
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger>
        <SelectValue placeholder="Select…" />
      </SelectTrigger>
      <SelectContent>
        {options.map((o) => (
          <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
