"use client";

import { useState } from "react";
import { Bug, ChevronDown, ChevronRight } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { fmtRelative } from "@/lib/utils";

export interface JsErrorRow {
  id: string;
  message: string;
  source_url: string;
  line_no: number | null;
  col_no: number | null;
  stack: string;
  page_url: string;
  browser: string;
  hits: number;
  is_resolved: boolean;
  last_seen_at: string;
  created_at: string;
}

/** JavaScript errors caught on real page loads.
 *
 *  Rows are one *bug*, not one occurrence — the backend collapses repeats onto a
 *  hit counter, so a script failing in a loop shows as a single row with a large
 *  count rather than thousands of lines.
 */
export function JsErrorsTab({ errors }: { errors: JsErrorRow[] }) {
  const [openId, setOpenId] = useState<string | null>(null);

  if (errors.length === 0) {
    return (
      <div className="rounded-lg border bg-card p-10 text-center">
        <Bug className="mx-auto h-8 w-8 text-muted-foreground" aria-hidden />
        <p className="mt-3 font-medium">No JavaScript errors recorded</p>
        <p className="mt-1 text-sm text-muted-foreground">
          The snippet reports uncaught errors as visitors hit them. Nothing here
          means nothing has thrown since it was installed.
        </p>
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-lg border bg-card">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b">
            <th className="px-4 py-3 text-left font-medium text-muted-foreground">Error</th>
            <th className="px-4 py-3 text-left font-medium text-muted-foreground">Source</th>
            <th className="px-4 py-3 text-right font-medium text-muted-foreground">Hits</th>
            <th className="px-4 py-3 text-left font-medium text-muted-foreground">Last seen</th>
          </tr>
        </thead>
        <tbody>
          {errors.map((e) => {
            const open = openId === e.id;
            return (
              <>
                <tr
                  key={e.id}
                  className="cursor-pointer border-b last:border-0 hover:bg-muted/30"
                  onClick={() => setOpenId(open ? null : e.id)}
                >
                  <td className="px-4 py-3">
                    <div className="flex items-start gap-1.5">
                      {open
                        ? <ChevronDown className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
                        : <ChevronRight className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />}
                      <div className="min-w-0">
                        <p className="truncate font-medium" title={e.message}>{e.message}</p>
                        <p className="text-xs text-muted-foreground">
                          {e.browser && <span className="mr-2">{e.browser}</span>}
                          {e.is_resolved && <Badge variant="secondary" className="text-[10px]">resolved</Badge>}
                        </p>
                      </div>
                    </div>
                  </td>
                  <td className="max-w-[220px] px-4 py-3 font-mono text-xs text-muted-foreground">
                    <span className="block truncate" title={e.source_url}>{e.source_url || "—"}</span>
                    {e.line_no != null && (
                      <span className="text-[11px]">
                        line {e.line_no}{e.col_no != null ? `:${e.col_no}` : ""}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <Badge variant={e.hits > 50 ? "destructive" : "secondary"} className="tabular-nums">
                      {e.hits}
                    </Badge>
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-xs text-muted-foreground">
                    {fmtRelative(e.last_seen_at)}
                  </td>
                </tr>
                {open && (
                  <tr key={`${e.id}-detail`} className="border-b bg-muted/20 last:border-0">
                    <td colSpan={4} className="px-4 py-3">
                      <p className="mb-1 text-xs font-semibold text-muted-foreground">Page</p>
                      <p className="mb-3 break-all font-mono text-xs">{e.page_url}</p>
                      {e.stack && (
                        <>
                          <p className="mb-1 text-xs font-semibold text-muted-foreground">
                            Stack (first frames)
                          </p>
                          <pre className="max-h-40 overflow-auto whitespace-pre-wrap break-all rounded bg-background p-2 font-mono text-[11px]">
                            {e.stack}
                          </pre>
                        </>
                      )}
                    </td>
                  </tr>
                )}
              </>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
