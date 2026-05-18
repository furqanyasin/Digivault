"use client";

import { useMemo } from "react";
import { Puzzle, AlertTriangle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ScriptDetailDialog } from "@/components/script-detail-dialog";
import type { Script } from "@/lib/api";

interface Props {
  scripts: Script[];
  websiteId: string;
}

function extractPlugin(script: Script): string | null {
  // Use the wp_plugin field if set
  if (script.wp_plugin) return script.wp_plugin;

  // Extract from URL: /wp-content/plugins/<name>/...
  const m = script.src_url.match(/\/wp-content\/plugins\/([^/]+)\//);
  if (m) return m[1];

  // Extract from URL: /wp-includes/...
  if (script.src_url.includes("/wp-includes/")) return "WordPress Core";

  return null;
}

function humanize(slug: string) {
  return slug.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

interface PluginGroup {
  name: string;
  scripts: Script[];
  conflicts: string[];
}

export function PluginsTab({ scripts, websiteId }: Props) {
  const plugins = useMemo<PluginGroup[]>(() => {
    const map = new Map<string, Script[]>();

    for (const s of scripts) {
      const plugin = extractPlugin(s);
      if (!plugin) continue;
      if (!map.has(plugin)) map.set(plugin, []);
      map.get(plugin)!.push(s);
    }

    return Array.from(map.entries())
      .map(([name, pluginScripts]) => {
        const conflicts: string[] = [];

        // Conflict: multiple scripts from the same base library loaded
        const bases = pluginScripts.map((s) => {
          const m = s.src_url.match(/\/([^/?#]+)\.min\.js|\/([^/?#]+)\.js/);
          return m?.[1] ?? m?.[2] ?? "";
        });
        const seen = new Set<string>();
        const dupes = new Set<string>();
        bases.forEach((b) => {
          if (b && seen.has(b)) dupes.add(b);
          if (b) seen.add(b);
        });
        if (dupes.size > 0) {
          conflicts.push(`Duplicate file loaded: ${[...dupes].join(", ")}`);
        }

        return { name, scripts: pluginScripts, conflicts };
      })
      .sort((a, b) => {
        // Conflicts first, then by name
        if (a.conflicts.length !== b.conflicts.length)
          return b.conflicts.length - a.conflicts.length;
        return a.name.localeCompare(b.name);
      });
  }, [scripts]);

  const pluginScripts = scripts.filter((s) => extractPlugin(s) !== null);

  if (pluginScripts.length === 0) {
    return (
      <div className="p-10 flex flex-col items-center gap-3 text-center">
        <Puzzle className="h-10 w-10 text-muted-foreground" />
        <p className="font-medium">No WordPress plugins detected</p>
        <p className="text-sm text-muted-foreground">
          Plugin detection works when scripts are loaded from <code>/wp-content/plugins/</code>.
        </p>
      </div>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Plugin</TableHead>
          <TableHead>Files</TableHead>
          <TableHead>Status</TableHead>
          <TableHead></TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {plugins.map((plugin) => (
          <TableRow key={plugin.name}>
            <TableCell className="font-medium text-sm">
              {humanize(plugin.name)}
            </TableCell>
            <TableCell className="text-sm text-muted-foreground">
              {plugin.scripts.length} {plugin.scripts.length === 1 ? "file" : "files"}
            </TableCell>
            <TableCell>
              {plugin.conflicts.length > 0 ? (
                <div className="space-y-1">
                  {plugin.conflicts.map((c, i) => (
                    <div key={i} className="flex items-center gap-1.5 text-xs text-amber-600">
                      <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                      {c}
                    </div>
                  ))}
                </div>
              ) : (
                <Badge variant="outline" className="text-emerald-600 border-emerald-200 bg-emerald-50 text-xs">
                  OK
                </Badge>
              )}
            </TableCell>
            <TableCell>
              <ScriptDetailDialog
                scripts={plugin.scripts}
                websiteId={websiteId}
                label={`${humanize(plugin.name)} — ${plugin.scripts.length} file${plugin.scripts.length > 1 ? "s" : ""}`}
              />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
