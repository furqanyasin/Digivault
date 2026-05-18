"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Plus, Eye, EyeOff, Trash2, ExternalLink, Copy } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
import type { Credential } from "@/lib/api";

const CREDENTIAL_TYPES = [
  { value: "wordpress", label: "WordPress Admin" },
  { value: "cpanel", label: "cPanel / Hosting" },
  { value: "godaddy", label: "GoDaddy" },
  { value: "namecheap", label: "Namecheap" },
  { value: "hostinger", label: "Hostinger" },
  { value: "cloudflare", label: "Cloudflare" },
  { value: "ftp", label: "FTP / SFTP" },
  { value: "wix", label: "Wix" },
  { value: "webflow", label: "Webflow" },
  { value: "shopify", label: "Shopify" },
  { value: "custom", label: "Custom" },
];

interface RevealData { username: string; password: string; notes: string }

function RevealButton({ credentialId }: { credentialId: string }) {
  const { toast } = useToast();
  const [revealed, setRevealed] = useState<RevealData | null>(null);
  const [visible, setVisible] = useState(false);
  const [loading, setLoading] = useState(false);

  async function reveal() {
    if (revealed) { setVisible(!visible); return; }
    setLoading(true);
    try {
      const res = await fetch(`/api/credentials/${credentialId}/reveal`, { method: "POST" });
      if (!res.ok) { toast({ variant: "destructive", title: "Cannot reveal credential" }); return; }
      const data: RevealData = await res.json();
      setRevealed(data);
      setVisible(true);
    } catch {
      toast({ variant: "destructive", title: "Network error" });
    } finally {
      setLoading(false);
    }
  }

  async function copy(text: string, label: string) {
    await navigator.clipboard.writeText(text);
    toast({ title: `${label} copied` });
  }

  return (
    <div className="space-y-1">
      <Button size="sm" variant="outline" onClick={reveal} disabled={loading}>
        {visible ? <EyeOff className="h-3.5 w-3.5 mr-1" /> : <Eye className="h-3.5 w-3.5 mr-1" />}
        {loading ? "Loading…" : visible ? "Hide" : "Reveal"}
      </Button>
      {visible && revealed && (
        <div className="bg-muted rounded p-2 space-y-1.5 text-xs font-mono">
          <div className="flex items-center justify-between gap-2">
            <span className="text-muted-foreground">user:</span>
            <span className="select-all">{revealed.username || "—"}</span>
            <Button size="sm" variant="ghost" className="h-5 px-1" onClick={() => copy(revealed.username, "Username")}>
              <Copy className="h-3 w-3" />
            </Button>
          </div>
          <div className="flex items-center justify-between gap-2">
            <span className="text-muted-foreground">pass:</span>
            <span className="select-all">{revealed.password || "—"}</span>
            <Button size="sm" variant="ghost" className="h-5 px-1" onClick={() => copy(revealed.password, "Password")}>
              <Copy className="h-3 w-3" />
            </Button>
          </div>
          {revealed.notes && (
            <p className="text-muted-foreground mt-1 border-t pt-1">{revealed.notes}</p>
          )}
        </div>
      )}
    </div>
  );
}

function AddCredentialDialog({ websiteId, onAdded }: { websiteId: string; onAdded: () => void }) {
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [form, setForm] = useState({
    label: "",
    credential_type: "",
    login_url: "",
    username: "",
    password: "",
    notes: "",
  });

  function update(key: string, val: string) {
    setForm((f) => ({ ...f, [key]: val }));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    try {
      const res = await fetch(`/api/websites/${websiteId}/credentials`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
      if (!res.ok) { toast({ variant: "destructive", title: "Failed to save credential" }); return; }
      toast({ title: "Credential saved" });
      setOpen(false);
      setForm({ label: "", credential_type: "", login_url: "", username: "", password: "", notes: "" });
      onAdded();
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
          Add credential
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Add credential</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-3">
          <div className="space-y-1.5">
            <Label>Label</Label>
            <Input placeholder="e.g. Client WordPress" value={form.label} onChange={(e) => update("label", e.target.value)} required />
          </div>
          <div className="space-y-1.5">
            <Label>Type</Label>
            <Select value={form.credential_type} onValueChange={(v) => update("credential_type", v)}>
              <SelectTrigger><SelectValue placeholder="Select type" /></SelectTrigger>
              <SelectContent>
                {CREDENTIAL_TYPES.map((t) => (
                  <SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label>Login URL</Label>
            <Input placeholder="https://example.com/wp-admin" value={form.login_url} onChange={(e) => update("login_url", e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label>Username</Label>
            <Input value={form.username} onChange={(e) => update("username", e.target.value)} required />
          </div>
          <div className="space-y-1.5">
            <Label>Password</Label>
            <Input type="password" value={form.password} onChange={(e) => update("password", e.target.value)} required />
          </div>
          <div className="space-y-1.5">
            <Label>Notes</Label>
            <Textarea placeholder="Optional notes" value={form.notes} onChange={(e) => update("notes", e.target.value)} rows={2} />
          </div>
          <DialogFooter className="pt-2">
            <Button type="button" variant="outline" onClick={() => setOpen(false)} disabled={loading}>Cancel</Button>
            <Button type="submit" disabled={loading}>{loading ? "Saving…" : "Save"}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function DeleteCredentialButton({ id, onDeleted }: { id: string; onDeleted: () => void }) {
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);

  async function handleDelete() {
    setLoading(true);
    try {
      const res = await fetch(`/api/credentials/${id}`, { method: "DELETE" });
      if (!res.ok && res.status !== 204) { toast({ variant: "destructive", title: "Failed to delete" }); return; }
      toast({ title: "Credential deleted" });
      setOpen(false);
      onDeleted();
    } catch {
      toast({ variant: "destructive", title: "Network error" });
    } finally {
      setLoading(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm" variant="ghost" className="text-destructive hover:text-destructive hover:bg-destructive/10">
          <Trash2 className="h-3.5 w-3.5" />
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Delete credential?</DialogTitle>
        </DialogHeader>
        <p className="text-sm text-muted-foreground">This action is permanent and cannot be undone.</p>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)} disabled={loading}>Cancel</Button>
          <Button variant="destructive" onClick={handleDelete} disabled={loading}>
            {loading ? "Deleting…" : "Delete"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function CredentialsTab({
  websiteId,
  initialCredentials,
}: {
  websiteId: string;
  initialCredentials: Credential[];
}) {
  const router = useRouter();

  function handleAdded() {
    router.refresh();
  }

  function handleDeleted() {
    router.refresh();
  }

  const credentials = initialCredentials;

  const typeLabel = (t: string) => CREDENTIAL_TYPES.find((x) => x.value === t)?.label ?? t;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          {credentials.length === 0
            ? "No credentials saved yet."
            : `${credentials.length} credential${credentials.length > 1 ? "s" : ""} stored`}
        </p>
        <AddCredentialDialog websiteId={websiteId} onAdded={handleAdded} />
      </div>

      {credentials.length === 0 ? (
        <Card>
          <CardContent className="py-12 flex flex-col items-center gap-2 text-center">
            <p className="font-medium">No credentials saved</p>
            <p className="text-sm text-muted-foreground">Add logins for WordPress admin, cPanel, GoDaddy, and more.</p>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-3">
          {credentials.map((cred) => (
            <Card key={cred.id}>
              <CardHeader className="pb-2 pt-4 px-4">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-sm font-semibold">{cred.label}</CardTitle>
                  <div className="flex items-center gap-1">
                    {cred.login_url && (
                      <a href={cred.login_url} target="_blank" rel="noopener noreferrer">
                        <Button size="sm" variant="ghost" title="Open login URL">
                          <ExternalLink className="h-3.5 w-3.5" />
                        </Button>
                      </a>
                    )}
                    <DeleteCredentialButton id={cred.id} onDeleted={handleDeleted} />
                  </div>
                </div>
              </CardHeader>
              <CardContent className="px-4 pb-4 space-y-3">
                <div className="flex items-center gap-2 flex-wrap">
                  <Badge variant="outline" className="text-xs">{typeLabel(cred.credential_type)}</Badge>
                  {cred.login_url && (
                    <span className="text-xs text-muted-foreground font-mono truncate max-w-[240px]">{cred.login_url}</span>
                  )}
                </div>
                <RevealButton credentialId={cred.id} />
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
