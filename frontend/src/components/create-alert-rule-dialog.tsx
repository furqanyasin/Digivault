"use client";

import { useState } from "react";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useToast } from "@/hooks/use-toast";
import { useRouter } from "next/navigation";

export function CreateAlertRuleDialog() {
  const { toast } = useToast();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [form, setForm] = useState({
    channel: "in_app",
    min_severity: "medium",
    delivery_mode: "immediate",
  });

  function update(key: string, value: string) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    try {
      const res = await fetch("/api/alert-rules", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          channel: form.channel,
          min_severity: form.min_severity,
          delivery_mode: form.delivery_mode,
          is_active: true,
        }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        const msg = Object.values(data).flat().join(" ") || "Failed to create rule";
        toast({ variant: "destructive", title: "Error", description: msg as string });
        return;
      }
      toast({ title: "Alert rule created" });
      setOpen(false);
      setForm({ channel: "in_app", min_severity: "medium", delivery_mode: "immediate" });
      router.refresh();
    } catch {
      toast({ variant: "destructive", title: "Network error" });
    } finally {
      setLoading(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm">
          <Plus className="h-4 w-4 mr-1" />
          New rule
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Create alert rule</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <Label>Channel</Label>
            <Select value={form.channel} onValueChange={(v) => update("channel", v)}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="in_app">In-app</SelectItem>
                <SelectItem value="email">Email</SelectItem>
                <SelectItem value="clickup">ClickUp</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label>Trigger on</Label>
            <Select value={form.min_severity} onValueChange={(v) => update("min_severity", v)}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="high">High severity only</SelectItem>
                <SelectItem value="medium">Medium &amp; above</SelectItem>
                <SelectItem value="low">All changes</SelectItem>
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">Only notify for changes at or above this severity.</p>
          </div>
          <div className="space-y-1.5">
            <Label>Delivery</Label>
            <Select value={form.delivery_mode} onValueChange={(v) => update("delivery_mode", v)}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="immediate">Immediate</SelectItem>
                <SelectItem value="hourly_digest">Hourly digest</SelectItem>
                <SelectItem value="daily_digest">Daily digest</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setOpen(false)} disabled={loading}>Cancel</Button>
            <Button type="submit" disabled={loading}>{loading ? "Creating…" : "Create"}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
