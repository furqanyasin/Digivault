"use client";

import { AlertTriangle, Bug, Info, AlertCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import type { PhpError } from "@/lib/api";
import { fmtDateTime } from "@/lib/utils";

interface Props {
  errors: PhpError[];
}

const LEVEL_CONFIG: Record<PhpError["level"], { label: string; className: string; icon: React.ReactNode }> = {
  fatal:      { label: "Fatal",      className: "bg-red-100 text-red-800 border-red-200",         icon: <AlertCircle className="h-3 w-3" /> },
  error:      { label: "Error",      className: "bg-red-50 text-red-700 border-red-100",           icon: <Bug className="h-3 w-3" /> },
  warning:    { label: "Warning",    className: "bg-amber-50 text-amber-700 border-amber-200",     icon: <AlertTriangle className="h-3 w-3" /> },
  notice:     { label: "Notice",     className: "bg-blue-50 text-blue-700 border-blue-200",        icon: <Info className="h-3 w-3" /> },
  deprecated: { label: "Deprecated", className: "bg-slate-100 text-slate-600 border-slate-200",   icon: <Info className="h-3 w-3" /> },
  info:       { label: "Info",       className: "bg-slate-50 text-slate-600 border-slate-100",    icon: <Info className="h-3 w-3" /> },
};

export function PhpErrorsTab({ errors }: Props) {
  if (errors.length === 0) {
    return (
      <div className="py-16 flex flex-col items-center gap-3 text-center">
        <Bug className="h-10 w-10 text-muted-foreground" />
        <p className="font-medium">No PHP errors logged</p>
        <p className="text-sm text-muted-foreground max-w-sm">
          Install the companion WordPress plugin to capture PHP errors and send them here automatically.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">{errors.length} error{errors.length !== 1 ? "s" : ""} (most recent 200)</p>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-24">Level</TableHead>
            <TableHead>Message</TableHead>
            <TableHead>File / Line</TableHead>
            <TableHead className="whitespace-nowrap">Captured</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {errors.map((err) => {
            const cfg = LEVEL_CONFIG[err.level] ?? LEVEL_CONFIG.error;
            return (
              <TableRow key={err.id}>
                <TableCell>
                  <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full border text-xs font-medium ${cfg.className}`}>
                    {cfg.icon}
                    {cfg.label}
                  </span>
                </TableCell>
                <TableCell className="font-mono text-xs max-w-xs">
                  <p className="break-words whitespace-pre-wrap">{err.message}</p>
                  {err.url && (
                    <p className="text-muted-foreground truncate mt-0.5" title={err.url}>
                      {err.url.replace(/^https?:\/\/[^/]+/, "") || "/"}
                    </p>
                  )}
                </TableCell>
                <TableCell className="font-mono text-xs text-muted-foreground max-w-[200px]">
                  {err.file ? (
                    <>
                      <p className="truncate" title={err.file}>{err.file.split(/[/\\]/).slice(-2).join("/")}</p>
                      {err.line != null && <p>line {err.line}</p>}
                    </>
                  ) : "—"}
                </TableCell>
                <TableCell className="text-xs text-muted-foreground whitespace-nowrap">
                  {fmtDateTime(err.captured_at)}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}
