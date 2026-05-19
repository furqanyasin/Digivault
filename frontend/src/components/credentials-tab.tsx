"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Plus, Eye, EyeOff, Trash2, ExternalLink, Copy, KeyRound } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
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

const TYPE_COLORS: Record<string, string> = {
  wordpress:  "bg-blue-50 text-blue-700 border-blue-200",
  cpanel:     "bg-orange-50 text-orange-700 border-orange-200",
  godaddy:    "bg-green-50 text-green-700 border-green-200",
  cloudflare: "bg-amber-50 text-amber-700 border-amber-200",
  ftp:        "bg-purple-50 text-purple-700 border-purple-200",
  shopify:    "bg-emerald-50 text-emerald-700 border-emerald-200",
};

interface RevealData { username: string; password: string; notes: string }

function CredentialRow({ cred, typeLabel, onDeleted }: {
  cred: Credential;
  typeLabel: string;
  onDeleted: () => void;
}) {
  const { toast } = useToast();
  const [revealed, setRevealed] = useState<RevealData | null>(null);
  const [visible, setVisible] = useState(false);
  const [loading, setLoading] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);

  async function reveal() {
    if (revealed) { setVisible(!visible); return; }
    setLoading(true);
    try {
      const res = await fetch(`/api/credentials/${cred.id}/reveal`, { method: "POST" });
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
    toast({ title: `${label} copied to clipboard` });
  }

  async function handleDelete() {
    setDeleting(true);
    try {
      const res = await fetch(`/api/credentials/${cred.id}`, { method: "DELETE" });
      if (!res.ok && res.status !== 204) { toast({ variant: "destructive", title: "Failed to delete" }); return; }
      toast({ title: "Credential deleted" });
      setDeleteOpen(false);
      onDeleted();
    } catch {
      toast({ variant: "destructive", title: "Network error" });
    } finally {
      setDeleting(false);
    }
  }

  const colorClass = TYPE_COLORS[cred.credential_type] ?? "bg-slate-50 text-slate-600 border-slate-200";

  return (
    <div className="border rounded-lg overflow-hidden">
      {/* Main row */}
      <div className="flex items-center gap-3 px-4 py-2.5">
        <span className={`shrink-0 text-xs font-medium px-2 py-0.5 rounded-full border ${colorClass}`}>
          {typeLabel}
        </span>
        <span className="font-medium text-sm flex-1 min-w-0 truncate">{cred.label}</span>
        {cred.login_url && (
          <a
            href={cred.login_url}
            target="_blank"
            rel="noopener noreferrer"
            className="shrink-0 text-xs text-muted-foreground hover:text-foreground font-mono truncate max-w-[200px] hidden sm:block"
            title={cred.login_url}
          >
            {cred.login_url.replace(/^https?:\/\//, "")}
          </a>
        )}
        <div className="flex items-center gap-1 shrink-0">
          {cred.login_url && (
            <a href={cred.login_url} target="_blank" rel="noopener noreferrer">
              <Button size="sm" variant="ghost" className="h-7 w-7 p-0" title="Open login URL">
                <ExternalLink className="h-3.5 w-3.5" />
              </Button>
            </a>
          )}
          <Button size="sm" variant="outline" className="h-7 px-2 text-xs gap-1" onClick={reveal} disabled={loading}>
            {visible ? <EyeOff className="h-3 w-3" /> : <Eye className="h-3 w-3" />}
            {loading ? "…" : visible ? "Hide" : "Reveal"}
          </Button>
          <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
            <DialogTrigger asChild>
              <Button size="sm" variant="ghost" className="h-7 w-7 p-0 text-destructive hover:text-destructive hover:bg-destructive/10">
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader><DialogTitle>Delete credential?</DialogTitle></DialogHeader>
              <p className="text-sm text-muted-foreground">This will permanently delete <strong>{cred.label}</strong> and cannot be undone.</p>
              <DialogFooter>
                <Button variant="outline" onClick={() => setDeleteOpen(false)} disabled={deleting}>Cancel</Button>
                <Button variant="destructive" onClick={handleDelete} disabled={deleting}>
                  {deleting ? "Deleting…" : "Delete"}
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </div>
      </div>

      {/* Revealed credentials inline */}
      {visible && revealed && (
        <div className="border-t bg-muted/40 px-4 py-2.5 grid grid-cols-2 gap-x-6 gap-y-1.5">
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground w-16">Username</span>
            <span className="text-xs font-mono select-all flex-1 truncate">{revealed.username || "—"}</span>
            {revealed.username && (
              <Button size="sm" variant="ghost" className="h-5 w-5 p-0 shrink-0" onClick={() => copy(revealed.username, "Username")}>
                <Copy className="h-3 w-3" />
              </Button>
            )}
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground w-16">Password</span>
            <span className="text-xs font-mono select-all flex-1 truncate">{revealed.password || "—"}</span>
            {revealed.password && (
              <Button size="sm" variant="ghost" className="h-5 w-5 p-0 shrink-0" onClick={() => copy(revealed.password, "Password")}>
                <Copy className="h-3 w-3" />
              </Button>
            )}
          </div>
          {revealed.notes && (
            <p className="col-span-2 text-xs text-muted-foreground border-t pt-1.5 mt-0.5">{revealed.notes}</p>
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
    label: "", credential_type: "", login_url: "", username: "", password: "", notes: "",
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
        <Button size="sm"><Plus className="h-4 w-4 mr-1" />Add credential</Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader><DialogTitle>Add credential</DialogTitle></DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-3">
          <div className="space-y-1.5">
            <Label>Label</Label>
            <Input placeholder="e.g. WordPress Admin" value={form.label} onChange={(e) => update("label", e.target.value)} required />
          </div>
          <div className="space-y-1.5">
            <Label>Type</Label>
            <Select value={form.credential_type} onValueChange={(v) => update("credential_type", v)}>
              <SelectTrigger><SelectValue placeholder="Select type" /></SelectTrigger>
              <SelectContent>
                {CREDENTIAL_TYPES.map((t) => <SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label>Login URL</Label>
            <Input placeholder="https://example.com/wp-admin" value={form.login_url} onChange={(e) => update("login_url", e.target.value)} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label>Username</Label>
              <Input value={form.username} onChange={(e) => update("username", e.target.value)} required />
            </div>
            <div className="space-y-1.5">
              <Label>Password</Label>
              <Input type="password" value={form.password} onChange={(e) => update("password", e.target.value)} required />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label>Notes <span className="text-muted-foreground">(optional)</span></Label>
            <Textarea placeholder="e.g. 2FA backup codes, account email…" value={form.notes} onChange={(e) => update("notes", e.target.value)} rows={2} />
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

export function CredentialsTab({ websiteId, initialCredentials }: {
  websiteId: string;
  initialCredentials: Credential[];
}) {
  const router = useRouter();
  const typeLabel = (t: string) => CREDENTIAL_TYPES.find((x) => x.value === t)?.label ?? t;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          {initialCredentials.length === 0
            ? "No credentials saved yet."
            : `${initialCredentials.length} credential${initialCredentials.length > 1 ? "s" : ""} stored`}
        </p>
        <AddCredentialDialog websiteId={websiteId} onAdded={() => router.refresh()} />
      </div>

      {initialCredentials.length === 0 ? (
        <div className="border rounded-lg py-10 flex flex-col items-center gap-2 text-center text-muted-foreground">
          <KeyRound className="h-8 w-8 opacity-30" />
          <p className="text-sm font-medium">No credentials saved</p>
          <p className="text-xs">Add logins for WordPress, cPanel, GoDaddy, and more.</p>
        </div>
      ) : (
        <div className="space-y-2">
          {initialCredentials.map((cred) => (
            <CredentialRow
              key={cred.id}
              cred={cred}
              typeLabel={typeLabel(cred.credential_type)}
              onDeleted={() => router.refresh()}
            />
          ))}
        </div>
      )}
    </div>
  );
}
