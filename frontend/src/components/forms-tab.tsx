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

const DETECTION_LABEL: Record<DetectedForm["detection_type"], string> = {
  native: "native",
  dom: "div-based",
  embedded: "embedded",
};

const DETECTION_COLOR: Record<DetectedForm["detection_type"], string> = {
  native: "bg-emerald-100 text-emerald-800",
  dom: "bg-amber-100 text-amber-800",
  embedded: "bg-violet-100 text-violet-800",
};

function DetectionBadge({ form }: { form: DetectedForm }) {
  const label =
    form.detection_type === "embedded" && form.provider
      ? `embedded — ${form.provider}`
      : DETECTION_LABEL[form.detection_type] ?? form.detection_type;
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium ${DETECTION_COLOR[form.detection_type] ?? "bg-slate-100 text-slate-700"}`}>
      {label}
    </span>
  );
}

function FieldBadge({ field }: { field: DetectedForm["fields"][number] }) {
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full border text-xs font-mono bg-muted">
      {field.label || field.name || field.type}
      {field.required && <span className="text-red-500">*</span>}
    </span>
  );
}

// A structural signature for a form, ignoring which page it appeared on. The
// same form (e.g. a footer newsletter signup) shows up on every page, producing
// one DetectedForm row per page — collapse those into a single entry.
function formSignature(f: DetectedForm): string {
  const fields = f.fields.map((x) => `${x.name}:${x.type}`).join(",");
  return [
    f.detection_type, f.form_method, f.form_id, f.form_name,
    f.form_action, f.provider, fields,
  ].join("|");
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

  // Deduplicate identical forms across pages, keeping the most recently seen.
  const bySignature = new Map<string, DetectedForm>();
  for (const f of forms) {
    const sig = formSignature(f);
    const existing = bySignature.get(sig);
    if (!existing || f.last_seen_at > existing.last_seen_at) {
      bySignature.set(sig, f);
    }
  }
  const uniqueForms = Array.from(bySignature.values());
  const pageCount = new Set(forms.map((f) => f.page_url)).size;

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        {uniqueForms.length} form{uniqueForms.length !== 1 ? "s" : ""} detected across{" "}
        {pageCount} page{pageCount !== 1 ? "s" : ""}
      </p>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Page / Action</TableHead>
            <TableHead>Method</TableHead>
            <TableHead>Detected as</TableHead>
            <TableHead>ID / Name</TableHead>
            <TableHead>Fields</TableHead>
            <TableHead>Last seen</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {uniqueForms.map((form) => (
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
              <TableCell>
                <DetectionBadge form={form} />
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
