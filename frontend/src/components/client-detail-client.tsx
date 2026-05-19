"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, RefreshCw, Save, ToggleLeft, ToggleRight } from "lucide-react";
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
import { fmtDate, fmtDateTime } from "@/lib/utils";

const HOSTING_OPTIONS = [
  { value: "_unknown", label: "Unknown" },
  { value: "wpengine", label: "WPEngine" },
  { value: "siteground", label: "SiteGround" },
  { value: "cloudways", label: "Cloudways" },
  { value: "bluehost", label: "Bluehost" },
  { value: "godaddy", label: "GoDaddy" },
  { value: "squarespace", label: "Squarespace" },
  { value: "wix", label: "Wix" },
  { value: "shopify", label: "Shopify" },
  { value: "other", label: "Other" },
];

const MIGRATION_STATUS_OPTIONS = [
  { value: "_unknown", label: "Unknown" },
  { value: "not_done", label: "No — We didn't do" },
  { value: "done_to_siteground", label: "Yes — From WPEngine to SiteGround" },
  { value: "not_applicable", label: "N/A" },
];

const MIGRATION_CONFIRM_OPTIONS = [
  { value: "_unknown", label: "Unknown" },
  { value: "can_do", label: "Yes, We can do Migration" },
  { value: "cannot", label: "No, We can't" },
];

const DIGI_OPTIONS = [
  { value: "unknown", label: "Unknown" },
  { value: "YES", label: "Yes" },
  { value: "NO", label: "No" },
  { value: "Hosting", label: "Hosting only" },
];

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
    hosting_platform: toSelect(initial.hosting_platform),
    hosting_renewal_date: initial.hosting_renewal_date ?? "",
    domain_access_location: initial.domain_access_location,
    migration_status: toSelect(initial.migration_status),
    csm_migration_confirmation: toSelect(initial.csm_migration_confirmation),
    running_ppc_ads: initial.running_ppc_ads,
    website_built_by_digi: initial.website_built_by_digi || "unknown",
    website_maintained_by_digi: initial.website_maintained_by_digi || "unknown",
    notes: initial.notes,
    comments: initial.comments,
    clickup_task_id: initial.clickup_task_id,
  });

  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState("");
  const [saveError, setSaveError] = useState("");
  const [syncing, setSyncing] = useState(false);
  const [syncMsg, setSyncMsg] = useState("");
  const [status, setStatus] = useState(initial.status);
  const [toggling, setToggling] = useState(false);

  function refresh() {
    startTransition(() => router.refresh());
  }

  function set<K extends keyof typeof form>(key: K, val: string) {
    setForm((f) => ({ ...f, [key]: val }));
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setSaveMsg("");
    setSaveError("");
    try {
      const payload = {
        ...form,
        hosting_platform: fromSelect(form.hosting_platform),
        migration_status: fromSelect(form.migration_status),
        csm_migration_confirmation: fromSelect(form.csm_migration_confirmation),
        website_built_by_digi: form.website_built_by_digi === "unknown" ? "" : form.website_built_by_digi,
        website_maintained_by_digi: form.website_maintained_by_digi === "unknown" ? "" : form.website_maintained_by_digi,
      };
      const res = await fetch(`/api/clients/${initial.id}/`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) {
        setSaveError(data?.detail ?? "Save failed.");
        return;
      }
      setSaveMsg("Saved successfully.");
      refresh();
    } finally {
      setSaving(false);
    }
  }

  async function handleSync() {
    setSyncing(true);
    setSyncMsg("");
    try {
      const res = await fetch(`/api/clients/${initial.id}/sync`, { method: "POST" });
      const data = await res.json();
      if (!res.ok) {
        setSyncMsg(data?.detail ?? "Sync failed.");
        return;
      }
      setSyncMsg("Synced from ClickUp.");
      refresh();
    } finally {
      setSyncing(false);
    }
  }

  async function handleToggleStatus() {
    setToggling(true);
    const action = status === "active" ? "deactivate" : "activate";
    try {
      const res = await fetch(`/api/clients/${initial.id}/${action}`, { method: "POST" });
      if (res.ok) {
        setStatus(status === "active" ? "inactive" : "active");
        refresh();
      }
    } finally {
      setToggling(false);
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
        <Badge variant={status === "active" ? "success" : "secondary"} className="capitalize">{status}</Badge>
      </div>

      {/* Actions bar */}
      <div className="flex gap-2 flex-wrap">
        {form.clickup_task_id && (
          <Button variant="outline" size="sm" onClick={handleSync} disabled={syncing}>
            <RefreshCw className={`h-4 w-4 mr-1 ${syncing ? "animate-spin" : ""}`} />
            {syncing ? "Syncing…" : "Sync from ClickUp"}
          </Button>
        )}
        <Button
          variant="outline"
          size="sm"
          onClick={handleToggleStatus}
          disabled={toggling}
          className={status === "active" ? "text-red-600 hover:text-red-700" : "text-emerald-600 hover:text-emerald-700"}
        >
          {status === "active"
            ? <><ToggleLeft className="h-4 w-4 mr-1" />Deactivate</>
            : <><ToggleRight className="h-4 w-4 mr-1" />Reactivate</>}
        </Button>
      </div>

      {syncMsg && (
        <p className="text-sm text-blue-700 bg-blue-50 border border-blue-200 rounded-md px-3 py-2">{syncMsg}</p>
      )}

      <form onSubmit={handleSave}>
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Client details</CardTitle>
          </CardHeader>
          <CardContent className="space-y-5">
            <div className="grid sm:grid-cols-2 gap-4">
              <Field label="Client name">
                <Input value={form.name} onChange={(e) => set("name", e.target.value)} required />
              </Field>
              <Field label="Website URL">
                <Input value={form.website_url} onChange={(e) => set("website_url", e.target.value)} placeholder="example.com" />
              </Field>
              <Field label="Hosting platform">
                <SelectField value={form.hosting_platform} onChange={(v) => set("hosting_platform", v)} options={HOSTING_OPTIONS} />
              </Field>
              <Field label="Hosting renewal date">
                <Input type="date" value={form.hosting_renewal_date} onChange={(e) => set("hosting_renewal_date", e.target.value)} />
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
              <Field label="Migration status">
                <SelectField value={form.migration_status} onChange={(v) => set("migration_status", v)} options={MIGRATION_STATUS_OPTIONS} />
              </Field>
              <Field label="CSM migration confirmation">
                <SelectField value={form.csm_migration_confirmation} onChange={(v) => set("csm_migration_confirmation", v)} options={MIGRATION_CONFIRM_OPTIONS} />
              </Field>
              <Field label="ClickUp task ID">
                <Input
                  value={form.clickup_task_id}
                  onChange={(e) => set("clickup_task_id", e.target.value)}
                  placeholder="e.g. 86evnnba3"
                  className="font-mono text-sm"
                />
              </Field>
            </div>

            <Field label="Notes">
              <Textarea value={form.notes} onChange={(e) => set("notes", e.target.value)} rows={3} placeholder="Internal notes…" />
            </Field>
            <Field label="Comments">
              <Textarea value={form.comments} onChange={(e) => set("comments", e.target.value)} rows={3} placeholder="Comments…" />
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
        <CardContent className="pt-4 grid sm:grid-cols-2 gap-2 text-xs text-muted-foreground">
          <span>Created: {fmtDateTime(initial.created_at)}</span>
          <span>Updated: {fmtDateTime(initial.updated_at)}</span>
          {initial.clickup_synced_at && (
            <span>ClickUp synced: {fmtDateTime(initial.clickup_synced_at)}</span>
          )}
          {initial.clickup_task_id && (
            <span className="font-mono">ClickUp ID: {initial.clickup_task_id}</span>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <Label>{label}</Label>
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
