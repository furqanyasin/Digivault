"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Settings2 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import type { Monitor } from "@/lib/api";

const INTERVALS = [
  { value: "30", label: "30 seconds" },
  { value: "60", label: "1 minute" },
  { value: "300", label: "5 minutes" },
  { value: "600", label: "10 minutes" },
  { value: "1800", label: "30 minutes" },
  { value: "3600", label: "1 hour" },
];

interface Props {
  monitor: Monitor;
}

export function MonitorEditForm({ monitor }: Props) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const [name, setName] = useState(monitor.name);
  const [url, setUrl] = useState(monitor.url);
  const [checkInterval, setCheckInterval] = useState(String(monitor.check_interval));
  const [timeout, setTimeout_] = useState(String(monitor.timeout));
  const [retryCount, setRetryCount] = useState(String(monitor.retry_count));
  const [expectedStatus, setExpectedStatus] = useState(String(monitor.expected_status_code));
  const [keyword, setKeyword] = useState(monitor.keyword ?? "");
  const [port, setPort] = useState(monitor.port ? String(monitor.port) : "");
  const [notes, setNotes] = useState(monitor.notes ?? "");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      const body: Record<string, unknown> = {
        name,
        url,
        check_interval: parseInt(checkInterval),
        timeout: parseInt(timeout),
        retry_count: parseInt(retryCount),
        notes,
      };
      if (monitor.monitor_type === "http") {
        body.expected_status_code = parseInt(expectedStatus);
        body.keyword = keyword;
      }
      if (monitor.monitor_type === "port") {
        body.port = port ? parseInt(port) : null;
      }
      const res = await fetch(`/api/monitors/${monitor.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d?.detail ?? `Error ${res.status}`);
      }
      setOpen(false);
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-3">
        <CardTitle className="text-base flex items-center gap-2">
          <Settings2 className="h-4 w-4" />
          Configuration
        </CardTitle>
        <Button size="sm" variant="outline" onClick={() => setOpen((v) => !v)}>
          {open ? "Cancel" : "Edit"}
        </Button>
      </CardHeader>
      <CardContent>
        {!open ? (
          <dl className="space-y-3 text-sm">
            <div className="flex justify-between">
              <dt className="text-muted-foreground">Type</dt>
              <dd className="font-mono uppercase text-xs border rounded px-1.5 py-0.5">{monitor.monitor_type}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-muted-foreground">Check interval</dt>
              <dd className="font-medium">{monitor.check_interval}s</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-muted-foreground">Timeout</dt>
              <dd className="font-medium">{monitor.timeout}s</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-muted-foreground">Retry count</dt>
              <dd className="font-medium">{monitor.retry_count}</dd>
            </div>
            {monitor.monitor_type === "http" && (
              <div className="flex justify-between">
                <dt className="text-muted-foreground">Expected status</dt>
                <dd className="font-mono font-medium">{monitor.expected_status_code}</dd>
              </div>
            )}
            {monitor.keyword && (
              <div className="flex justify-between">
                <dt className="text-muted-foreground">Keyword</dt>
                <dd className="font-mono font-medium">{monitor.keyword}</dd>
              </div>
            )}
            {monitor.port && (
              <div className="flex justify-between">
                <dt className="text-muted-foreground">Port</dt>
                <dd className="font-mono font-medium">{monitor.port}</dd>
              </div>
            )}
            {monitor.notes && (
              <div className="pt-2 border-t">
                <dt className="text-muted-foreground mb-1">Notes</dt>
                <dd>{monitor.notes}</dd>
              </div>
            )}
          </dl>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2 col-span-2">
                <Label>Monitor name</Label>
                <Input value={name} onChange={(e) => setName(e.target.value)} required />
              </div>
              <div className="space-y-2 col-span-2">
                <Label>URL / Hostname</Label>
                <Input value={url} onChange={(e) => setUrl(e.target.value)} required />
              </div>
            </div>

            {monitor.monitor_type === "http" && (
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label>Expected status code</Label>
                  <Input type="number" value={expectedStatus} onChange={(e) => setExpectedStatus(e.target.value)} min={100} max={599} />
                </div>
                <div className="space-y-2">
                  <Label>Keyword match</Label>
                  <Input value={keyword} onChange={(e) => setKeyword(e.target.value)} placeholder="optional" />
                </div>
              </div>
            )}

            {monitor.monitor_type === "port" && (
              <div className="space-y-2">
                <Label>Port</Label>
                <Input type="number" value={port} onChange={(e) => setPort(e.target.value)} min={1} max={65535} />
              </div>
            )}

            <div className="grid grid-cols-3 gap-4">
              <div className="space-y-2">
                <Label>Check interval</Label>
                <Select value={checkInterval} onValueChange={setCheckInterval}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {INTERVALS.map((i) => (
                      <SelectItem key={i.value} value={i.value}>{i.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>Timeout (s)</Label>
                <Input type="number" value={timeout} onChange={(e) => setTimeout_(e.target.value)} min={5} max={60} />
              </div>
              <div className="space-y-2">
                <Label>Retry count</Label>
                <Input type="number" value={retryCount} onChange={(e) => setRetryCount(e.target.value)} min={0} max={5} />
              </div>
            </div>

            <div className="space-y-2">
              <Label>Notes</Label>
              <Textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} placeholder="Optional context..." />
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
