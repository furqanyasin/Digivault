import { FileText, ChevronDown, ChevronRight, Send, CheckCircle2, XCircle } from "lucide-react";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { fmtRelative } from "@/lib/utils";
import {
  dedupeForms,
  destinationCount,
  errorsForForm,
  fmtPct,
  formLabel,
  health,
  pagePath,
  primaryRecipient,
  successRate,
  HEALTH_LABEL,
  HEALTH_VARIANT,
  type FormRow,
} from "@/lib/detected-forms";
import { FormDetailDialog } from "@/components/form-detail-dialog";
import { SyncFormRecipientsButton } from "@/components/sync-form-recipients-button";
import type { DetectedForm, FormSubmissionError } from "@/lib/api";

interface Props {
  forms: DetectedForm[];
  formErrors?: FormSubmissionError[];
  websiteId: string;
  /** WordPress sites can be asked where their forms deliver; others can't. */
  isWordPress?: boolean;
}

function StatTile({
  icon,
  tone,
  value,
  label,
}: {
  icon: React.ReactNode;
  tone: string;
  value: string | number;
  label: string;
}) {
  return (
    <div className="flex items-center gap-3 rounded-xl border bg-card px-4 py-3">
      <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-md ${tone}`}>
        {icon}
      </span>
      <div className="min-w-0">
        <p className="text-xl font-bold leading-tight tabular-nums">{value}</p>
        <p className="text-xs text-muted-foreground">{label}</p>
      </div>
    </div>
  );
}

export function FormsTab({
  forms,
  formErrors = [],
  websiteId,
  isWordPress = false,
}: Props) {
  if (forms.length === 0) {
    return (
      <div className="py-16 flex flex-col items-center gap-3 text-center">
        <FileText className="h-10 w-10 text-muted-foreground" />
        <p className="font-medium">No forms detected yet</p>
        <p className="text-sm text-muted-foreground max-w-sm">
          Forms will appear here once the tracking snippet fires on a page that contains a form.
        </p>
      </div>
    );
  }

  // Shared with the page's tab badge and overview tile so all three agree.
  const uniqueForms = dedupeForms(forms);
  const managedForms = uniqueForms.filter((f) => f.is_managed !== false);
  const embeddedForms = uniqueForms.filter((f) => f.is_managed === false);

  const totalSubmissions = managedForms.reduce((n, f) => n + (f.submission_count || 0), 0);

  // Weight by submission volume so one quiet form can't swing the average.
  const withTraffic = managedForms.filter((f) => (f.submission_count || 0) > 0);
  const totalFailed = withTraffic.reduce(
    (n, f) => n + Math.min(errorsForForm(f, formErrors).length, f.submission_count),
    0
  );
  const avgSuccess = totalSubmissions > 0
    ? ((totalSubmissions - totalFailed) / totalSubmissions) * 100
    : null;

  const failingCount = managedForms.filter(
    (f) => health(successRate(f, formErrors)) === "failing"
  ).length;

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile
          icon={<FileText className="h-4 w-4 text-violet-600" />}
          tone="bg-violet-100"
          value={managedForms.length}
          label={`Detected form${managedForms.length !== 1 ? "s" : ""}`}
        />
        <StatTile
          icon={<Send className="h-4 w-4 text-emerald-600" />}
          tone="bg-emerald-100"
          value={totalSubmissions}
          label="Submits (total)"
        />
        <StatTile
          icon={<CheckCircle2 className="h-4 w-4 text-emerald-600" />}
          tone="bg-emerald-100"
          value={fmtPct(avgSuccess)}
          label="Avg success"
        />
        <StatTile
          icon={<XCircle className="h-4 w-4 text-red-600" />}
          tone="bg-red-100"
          value={failingCount}
          label="Failing"
        />
      </div>

      {/* Offered only on WordPress: it reads the form plugins' own settings, and
          there is nothing equivalent to read on any other platform. */}
      {isWordPress && managedForms.some((f) => destinationCount(f) === 0) && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border bg-card px-4 py-3">
          <p className="text-xs text-muted-foreground">
            Some forms don&apos;t show where they deliver — WordPress keeps that address
            out of the page. With a saved WordPress credential Digivault can read it
            from Elementor and Gravity Forms through the site&apos;s own API.
          </p>
          <SyncFormRecipientsButton websiteId={websiteId} />
        </div>
      )}

      <FormsTable forms={managedForms} formErrors={formErrors} />

      {embeddedForms.length > 0 && (
        <details className="border rounded-lg">
          <summary className="cursor-pointer select-none px-4 py-3 text-sm font-medium flex items-center gap-2">
            <ChevronRight className="h-4 w-4 inline [details[open]_&]:hidden" />
            <ChevronDown className="h-4 w-4 hidden [details[open]_&]:inline" />
            Third-party embedded forms ({embeddedForms.length})
            <span className="font-normal text-muted-foreground">
              — hosted by a third party; submissions can&apos;t be counted from the page
            </span>
          </summary>
          <div className="px-2 pb-2">
            <FormsTable forms={embeddedForms} formErrors={formErrors} embedded />
          </div>
        </details>
      )}
    </div>
  );
}

function FormsTable({
  forms,
  formErrors,
  embedded = false,
}: {
  forms: FormRow[];
  formErrors: FormSubmissionError[];
  embedded?: boolean;
}) {
  return (
    <div className="overflow-x-auto rounded-lg border bg-card">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Form</TableHead>
            <TableHead>Path</TableHead>
            <TableHead>Goes to</TableHead>
            <TableHead className="text-right">Submits</TableHead>
            <TableHead className="text-right">Success</TableHead>
            <TableHead>Last submit</TableHead>
            <TableHead>Status</TableHead>
            <TableHead className="w-px"><span className="sr-only">Details</span></TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {forms.map((form) => {
            const errs = errorsForForm(form, formErrors);
            const rate = embedded ? null : successRate(form, formErrors);
            const state = embedded ? null : health(rate);
            return (
              <TableRow key={form.id}>
                <TableCell className="font-medium text-sm max-w-[220px] truncate" title={formLabel(form)}>
                  {formLabel(form)}
                </TableCell>
                <TableCell
                  className="font-mono text-xs text-muted-foreground max-w-[200px] truncate"
                  title={form.pages.join("\n")}
                >
                  {pagePath(form.page_url)}
                  {form.pages.length > 1 && (
                    <span className="ml-1 whitespace-nowrap font-sans">
                      +{form.pages.length - 1} more
                    </span>
                  )}
                </TableCell>
                <TableCell
                  className="font-mono text-xs text-muted-foreground max-w-[200px] truncate"
                  title={
                    destinationCount(form) > 0
                      ? [
                          ...form.recipients.to,
                          ...form.recipients.cc.map((e) => `${e} (Cc)`),
                          ...form.recipients.bcc.map((e) => `${e} (Bcc)`),
                        ].join("\n")
                      : embedded
                        ? "Handled by the form's provider — open Details"
                        : "No recipient in the page markup; set server-side — open Details"
                  }
                >
                  {destinationCount(form) > 0 ? (
                    <>
                      {primaryRecipient(form)}
                      {destinationCount(form) > 1 && (
                        <span className="ml-1 whitespace-nowrap font-sans">
                          +{destinationCount(form) - 1} more
                        </span>
                      )}
                    </>
                  ) : (
                    <span className="font-sans">{embedded ? "—" : "Server-side"}</span>
                  )}
                </TableCell>
                <TableCell className="text-right tabular-nums text-sm">
                  {embedded ? <span className="text-muted-foreground">n/a</span> : form.submission_count}
                </TableCell>
                <TableCell className="text-right tabular-nums text-sm">
                  {embedded ? <span className="text-muted-foreground">n/a</span> : fmtPct(rate)}
                </TableCell>
                <TableCell className="text-sm text-muted-foreground">
                  {embedded ? "n/a" : fmtRelative(form.last_submission_at)}
                </TableCell>
                <TableCell>
                  {state ? (
                    <Badge
                      variant={HEALTH_VARIANT[state]}
                      title={errs.length > 0 ? errs[0].message : undefined}
                    >
                      {HEALTH_LABEL[state]}
                    </Badge>
                  ) : (
                    <span className="text-xs text-muted-foreground">
                      {embedded ? "Not tracked" : "No submits yet"}
                    </span>
                  )}
                </TableCell>
                <TableCell className="text-right">
                  <FormDetailDialog form={form} formErrors={formErrors} embedded={embedded} />
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}
