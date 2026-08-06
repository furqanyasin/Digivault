"use client";

import { useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";

const MONITOR_TYPES = [
  { value: "http", label: "HTTP / HTTPS" },
  { value: "ping", label: "Ping (DNS)" },
  { value: "port", label: "Port" },
  { value: "ssl", label: "SSL Certificate" },
];

// Checks all leave from one platform IP, so frequent polling across the client
// fleet gets that IP challenged or blocked by the sites' WAFs. 15 minutes is the
// default; the sub-5-minute options are deliberately not offered.
const INTERVALS = [
  { value: "300", label: "5 minutes" },
  { value: "600", label: "10 minutes" },
  { value: "900", label: "15 minutes (recommended)" },
  { value: "1800", label: "30 minutes" },
  { value: "3600", label: "1 hour" },
];

export default function NewMonitorPage() {
  const router = useRouter();
  // Set when arriving from a website's Uptime tab — links the monitor to it.
  const websiteId = useSearchParams().get("website");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [monitorType, setMonitorType] = useState("http");
  const [checkInterval, setCheckInterval] = useState("900");
  const [timeout, setTimeout_] = useState("30");
  const [retryCount, setRetryCount] = useState("3");
  const [expectedStatus, setExpectedStatus] = useState("200");
  const [keyword, setKeyword] = useState("");
  const [port, setPort] = useState("");
  const [notes, setNotes] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      const body: Record<string, unknown> = {
        name,
        url,
        monitor_type: monitorType,
        check_interval: parseInt(checkInterval),
        timeout: parseInt(timeout),
        retry_count: parseInt(retryCount),
        notes,
      };
      if (websiteId) body.website = websiteId;
      if (monitorType === "http") {
        body.expected_status_code = parseInt(expectedStatus);
        body.keyword = keyword;
      }
      if (monitorType === "port") {
        body.port = port ? parseInt(port) : null;
      }
      const res = await fetch("/api/monitors", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d?.detail ?? d?.url?.[0] ?? `Error ${res.status}`);
      }
      const created = await res.json();
      router.push(`/monitors/${created.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="p-8 max-w-2xl mx-auto space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">New Monitor</h1>
        <p className="text-muted-foreground mt-1">Configure uptime and performance monitoring for a service</p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-6">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Basic settings</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="name">Monitor name</Label>
              <Input id="name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Production API" required />
            </div>

            <div className="space-y-2">
              <Label htmlFor="url">URL / Hostname</Label>
              <Input
                id="url"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder={monitorType === "http" || monitorType === "ssl" ? "https://example.com" : "example.com"}
                required
              />
              <p className="text-xs text-muted-foreground">
                {monitorType === "http" && "Full URL including protocol"}
                {monitorType === "ssl" && "Domain to check SSL certificate"}
                {monitorType === "ping" && "Hostname or IP address (DNS resolution check)"}
                {monitorType === "port" && "Hostname or IP address"}
              </p>
            </div>

            <div className="space-y-2">
              <Label>Monitor type</Label>
              <Select value={monitorType} onValueChange={setMonitorType}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {MONITOR_TYPES.map((t) => (
                    <SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </CardContent>
        </Card>

        {monitorType === "http" && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">HTTP settings</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="expectedStatus">Expected status code</Label>
                <Input
                  id="expectedStatus"
                  type="number"
                  value={expectedStatus}
                  onChange={(e) => setExpectedStatus(e.target.value)}
                  min={100}
                  max={599}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="keyword">Keyword match (optional)</Label>
                <Input
                  id="keyword"
                  value={keyword}
                  onChange={(e) => setKeyword(e.target.value)}
                  placeholder="OK"
                />
                <p className="text-xs text-muted-foreground">If set, response body must contain this string</p>
              </div>
            </CardContent>
          </Card>
        )}

        {monitorType === "port" && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Port settings</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="port">Port number</Label>
                <Input
                  id="port"
                  type="number"
                  value={port}
                  onChange={(e) => setPort(e.target.value)}
                  placeholder="443"
                  min={1}
                  max={65535}
                  required
                />
              </div>
            </CardContent>
          </Card>
        )}

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Check schedule</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label>Check interval</Label>
              <Select value={checkInterval} onValueChange={setCheckInterval}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {INTERVALS.map((i) => (
                    <SelectItem key={i.value} value={i.value}>{i.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="timeout">Timeout (seconds)</Label>
                <Input
                  id="timeout"
                  type="number"
                  value={timeout}
                  onChange={(e) => setTimeout_(e.target.value)}
                  min={5}
                  max={60}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="retryCount">Retry count</Label>
                <Input
                  id="retryCount"
                  type="number"
                  value={retryCount}
                  onChange={(e) => setRetryCount(e.target.value)}
                  min={0}
                  max={5}
                />
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="notes">Notes (optional)</Label>
              <Textarea
                id="notes"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="Add any context about this monitor..."
                rows={3}
              />
            </div>
          </CardContent>
        </Card>

        {error && <p className="text-sm text-red-600">{error}</p>}

        <div className="flex gap-3">
          <Button type="submit" disabled={loading}>
            {loading ? "Creating…" : "Create monitor"}
          </Button>
          <Button type="button" variant="outline" onClick={() => router.back()}>
            Cancel
          </Button>
        </div>
      </form>
    </div>
  );
}
