"use client";

import { History, Puzzle, Layers, Globe, Rocket, Pencil, Mail } from "lucide-react";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import type { SiteEvent } from "@/lib/api";
import { fmtDateTime } from "@/lib/utils";

interface Props {
  events: SiteEvent[];
}

const EVENT_ICON: Record<string, React.ReactNode> = {
  plugin_updated:   <Puzzle className="h-3.5 w-3.5" />,
  plugin_installed: <Puzzle className="h-3.5 w-3.5" />,
  plugin_removed:   <Puzzle className="h-3.5 w-3.5" />,
  theme_changed:    <Layers className="h-3.5 w-3.5" />,
  core_updated:     <Globe className="h-3.5 w-3.5" />,
  deployment:       <Rocket className="h-3.5 w-3.5" />,
  manual:           <Pencil className="h-3.5 w-3.5" />,
  form_recipients_changed: <Mail className="h-3.5 w-3.5" />,
};

const SEVERITY_CLASS: Record<string, string> = {
  info:     "bg-blue-50 text-blue-700 border-blue-200",
  warning:  "bg-amber-50 text-amber-700 border-amber-200",
  critical: "bg-red-50 text-red-700 border-red-200",
};

const EVENT_LABEL: Record<string, string> = {
  plugin_updated:   "Plugin Updated",
  plugin_installed: "Plugin Installed",
  plugin_removed:   "Plugin Removed",
  theme_changed:    "Theme Changed",
  core_updated:     "Core Updated",
  deployment:       "Deployment",
  manual:           "Manual Entry",
  form_recipients_changed: "Form Recipients Changed",
};

export function SiteEventsTab({ events }: Props) {
  if (events.length === 0) {
    return (
      <div className="py-16 flex flex-col items-center gap-3 text-center">
        <History className="h-10 w-10 text-muted-foreground" />
        <p className="font-medium">No change log entries yet</p>
        <p className="text-sm text-muted-foreground max-w-sm">
          Site events such as plugin updates, theme changes, and deployments will appear here automatically.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">{events.length} event{events.length !== 1 ? "s" : ""}</p>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Event</TableHead>
            <TableHead>Summary</TableHead>
            <TableHead>Actor</TableHead>
            <TableHead>Severity</TableHead>
            <TableHead className="whitespace-nowrap">Occurred</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {events.map((ev) => (
            <TableRow key={ev.id}>
              <TableCell>
                <div className="flex items-center gap-1.5 text-sm">
                  <span className="text-muted-foreground">{EVENT_ICON[ev.event_type] ?? <Pencil className="h-3.5 w-3.5" />}</span>
                  <span className="font-medium whitespace-nowrap">{EVENT_LABEL[ev.event_type] ?? ev.event_type}</span>
                </div>
              </TableCell>
              <TableCell className="max-w-xs">
                <p className="text-sm">{ev.summary}</p>
                {Object.keys(ev.details ?? {}).length > 0 && (
                  <p className="text-xs text-muted-foreground font-mono mt-0.5">
                    {Object.entries(ev.details).slice(0, 3).map(([k, v]) => `${k}: ${v}`).join(" · ")}
                  </p>
                )}
              </TableCell>
              <TableCell className="text-sm text-muted-foreground">
                {ev.actor || "—"}
              </TableCell>
              <TableCell>
                <span className={`inline-block px-2 py-0.5 rounded-full border text-xs font-medium capitalize ${SEVERITY_CLASS[ev.severity] ?? SEVERITY_CLASS.info}`}>
                  {ev.severity}
                </span>
              </TableCell>
              <TableCell className="text-xs text-muted-foreground whitespace-nowrap">
                {fmtDateTime(ev.occurred_at)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
