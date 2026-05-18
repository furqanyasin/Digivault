import { FileText, ChevronDown, ChevronRight } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import type { DetectedForm } from "@/lib/api";
import { fmtDate } from "@/lib/utils";

interface Props {
  forms: DetectedForm[];
}

const METHOD_COLOR: Record<string, string> = {
  post: "bg-blue-100 text-blue-800",
  get: "bg-slate-100 text-slate-700",
};

function FieldBadge({ field }: { field: DetectedForm["fields"][number] }) {
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full border text-xs font-mono bg-muted">
      {field.label || field.name || field.type}
      {field.required && <span className="text-red-500">*</span>}
    </span>
  );
}

export function FormsTab({ forms }: Props) {
  if (forms.length === 0) {
    return (
      <div className="py-16 flex flex-col items-center gap-3 text-center">
        <FileText className="h-10 w-10 text-muted-foreground" />
        <p className="font-medium">No forms detected yet</p>
        <p className="text-sm text-muted-foreground max-w-sm">
          Forms will appear here once the tracking snippet fires on a page that contains a{" "}
          <code className="bg-muted px-1 rounded">&lt;form&gt;</code> element.
        </p>
      </div>
    );
  }

  const byPage: Record<string, DetectedForm[]> = {};
  for (const f of forms) {
    const key = f.page_url;
    if (!byPage[key]) byPage[key] = [];
    byPage[key].push(f);
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        {forms.length} form{forms.length !== 1 ? "s" : ""} detected across{" "}
        {Object.keys(byPage).length} page{Object.keys(byPage).length !== 1 ? "s" : ""}
      </p>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Page / Action</TableHead>
            <TableHead>Method</TableHead>
            <TableHead>ID / Name</TableHead>
            <TableHead>Fields</TableHead>
            <TableHead>Last seen</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {forms.map((form) => (
            <TableRow key={form.id}>
              <TableCell className="align-top">
                <div className="font-mono text-xs text-muted-foreground truncate max-w-[180px]" title={form.page_url}>
                  {form.page_url.replace(/^https?:\/\/[^/]+/, "") || "/"}
                </div>
                {form.form_action && (
                  <div className="font-mono text-xs truncate max-w-[180px] text-foreground" title={form.form_action}>
                    → {form.form_action.replace(/^https?:\/\/[^/]+/, "") || "(same page)"}
                  </div>
                )}
              </TableCell>
              <TableCell>
                <span className={`px-2 py-0.5 rounded text-xs font-semibold uppercase ${METHOD_COLOR[form.form_method] ?? "bg-slate-100 text-slate-700"}`}>
                  {form.form_method}
                </span>
              </TableCell>
              <TableCell className="text-xs font-mono text-muted-foreground">
                {form.form_id && <div>#{form.form_id}</div>}
                {form.form_name && <div>{form.form_name}</div>}
                {!form.form_id && !form.form_name && "—"}
              </TableCell>
              <TableCell>
                <div className="flex flex-wrap gap-1 max-w-xs">
                  {form.fields.length === 0 ? (
                    <span className="text-xs text-muted-foreground">—</span>
                  ) : (
                    form.fields.map((f, i) => <FieldBadge key={i} field={f} />)
                  )}
                </div>
              </TableCell>
              <TableCell className="text-xs text-muted-foreground whitespace-nowrap">
                {fmtDate(form.last_seen_at)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
