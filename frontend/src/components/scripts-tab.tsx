"use client";

import { useMemo } from "react";
import { Code } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ScriptDetailDialog } from "@/components/script-detail-dialog";
import type { Script } from "@/lib/api";

interface Props {
  scripts: Script[];
  websiteId: string;
}

function providerVariant(p: string): "default" | "secondary" | "destructive" | "outline" {
  if (!p || p === "unknown") return "outline";
  if (p === "google-analytics" || p === "google-tag-manager") return "secondary";
  return "default";
}

function shortDomain(url: string) {
  try {
    const u = new URL(url.startsWith("//") ? `https:${url}` : url);
    return u.hostname;
  } catch {
    return url;
  }
}

export function ScriptsTab({ scripts, websiteId }: Props) {
  // Group scripts by src_domain — each unique domain = one row
  const groups = useMemo(() => {
    const map = new Map<string, Script[]>();
    for (const s of scripts) {
      const key = shortDomain(s.src_url);
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(s);
    }
    // Sort: known providers first, then by domain
    return Array.from(map.entries()).sort(([, a], [, b]) => {
      const aKnown = a[0].provider !== "unknown" ? 0 : 1;
      const bKnown = b[0].provider !== "unknown" ? 0 : 1;
      return aKnown - bKnown;
    });
  }, [scripts]);

  if (scripts.length === 0) {
    return (
      <div className="p-10 flex flex-col items-center gap-3 text-center">
        <Code className="h-10 w-10 text-muted-foreground" />
        <p className="font-medium">No scripts detected yet</p>
        <p className="text-sm text-muted-foreground">
          Install the snippet and visit a page — data appears within seconds.
        </p>
      </div>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Domain</TableHead>
          <TableHead>Provider</TableHead>
          <TableHead>Category</TableHead>
          <TableHead>Files</TableHead>
          <TableHead>Last seen</TableHead>
          <TableHead></TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {groups.map(([domain, group]) => {
          const rep = group[0];
          const lastSeen = group
            .map((s) => s.last_seen_at)
            .filter(Boolean)
            .sort()
            .at(-1);
          return (
            <TableRow key={domain}>
              <TableCell className="font-mono text-xs max-w-[200px] truncate" title={domain}>
                {domain}
              </TableCell>
              <TableCell>
                <Badge variant={providerVariant(rep.provider)} className="capitalize">
                  {rep.provider === "unknown" ? "—" : rep.provider}
                </Badge>
              </TableCell>
              <TableCell className="text-sm capitalize text-muted-foreground">
                {rep.category === "unknown" ? "—" : rep.category}
              </TableCell>
              <TableCell className="text-sm text-muted-foreground">
                {group.length} {group.length === 1 ? "file" : "files"}
              </TableCell>
              <TableCell className="text-sm text-muted-foreground">
                {lastSeen ? new Date(lastSeen).toLocaleDateString() : "—"}
              </TableCell>
              <TableCell>
                <ScriptDetailDialog
                  scripts={group}
                  websiteId={websiteId}
                  label={`${rep.provider !== "unknown" ? rep.provider : domain} — ${group.length} file${group.length > 1 ? "s" : ""}`}
                />
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
