"use client";

import { useState } from "react";
import { Info, Mail, ServerCog } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  errorsForForm,
  fmtPct,
  formLabel,
  health,
  pagePath,
  successRate,
  HEALTH_LABEL,
  HEALTH_VARIANT,
  type FormRow,
} from "@/lib/detected-forms";
import type { FormSubmissionError } from "@/lib/api";
import { fmtDateTime, fmtRelative } from "@/lib/utils";

interface Props {
  form: FormRow;
  formErrors: FormSubmissionError[];
  /** A third-party form in an iframe: its internals aren't readable from the page. */
  embedded?: boolean;
}

const DETECTION_LABEL: Record<string, string> = {
  native: "Native <form>",
  dom: "Field group (no <form> tag)",
  embedded: "Embedded (iframe)",
};

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-3 text-xs">
      <span className="w-28 shrink-0 text-muted-foreground">{label}</span>
      <span className="min-w-0 flex-1 break-words">{children}</span>
    </div>
  );
}

/** Where submissions go, and — when that is unknown — why it can't be known.
 *
 *  "Server-side" is a real answer, not a gap in the data: the snippet reads a
 *  form's destination out of the page (a mailto: action, a data-* attribute, a
 *  hidden config input). Plugins that keep the address in the site's admin
 *  expose nothing to read. Users reasonably read a blank column as broken
 *  detection, so the dialog says which of the two it is.
 */
function Destination({ form, embedded }: { form: FormRow; embedded: boolean }) {
  if (form.recipient_emails.length > 0) {
    return (
      <div className="rounded-lg border bg-muted/40 p-3 space-y-2">
        <p className="flex items-center gap-1.5 text-xs font-medium">
          <Mail className="h-3.5 w-3.5 text-emerald-600" />
          Submissions are sent to
        </p>
        <ul className="space-y-0.5">
          {form.recipient_emails.map((email) => (
            <li key={email} className="font-mono text-xs break-all">
              {email}
            </li>
          ))}
        </ul>
        <p className="text-xs text-muted-foreground">
          Read from the form&apos;s own markup — a <code>mailto:</code> action, a
          recipient <code>data-</code> attribute, or a hidden configuration field.
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border bg-muted/40 p-3 space-y-2">
      <p className="flex items-center gap-1.5 text-xs font-medium">
        <ServerCog className="h-3.5 w-3.5 text-muted-foreground" />
        {embedded ? "Handled by the form's provider" : "Set server-side — no address in the page"}
      </p>
      <p className="text-xs text-muted-foreground">
        {embedded ? (
          <>
            This form is hosted by{" "}
            {form.provider ? <span className="font-medium">{form.provider}</span> : "a third party"}{" "}
            and rendered in an iframe, so its recipient lives in that provider&apos;s account.
            Nothing in the page reveals it.
          </>
        ) : (
          <>
            Digivault reads a recipient from the page itself — a <code>mailto:</code>{" "}
            action, a recipient <code>data-</code> attribute, or a hidden configuration
            field. This form carries none of them, which is normal: Contact Form 7,
            WPForms, Elementor, Gravity Forms, Formspree and Netlify all keep the
            address in the site&apos;s admin, where no in-page script can see it. Check
            the form&apos;s settings in the CMS to confirm where it delivers.
          </>
        )}
      </p>
    </div>
  );
}

export function FormDetailDialog({ form, formErrors, embedded = false }: Props) {
  const [open, setOpen] = useState(false);

  const errs = errorsForForm(form, formErrors);
  const rate = embedded ? null : successRate(form, formErrors);
  const state = embedded ? null : health(rate);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="ghost" size="sm" className="gap-1 h-7 px-2 text-xs">
          <Info className="h-3.5 w-3.5" />
          Details
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="text-base pr-6 break-words">{formLabel(form)}</DialogTitle>
        </DialogHeader>

        <div className="space-y-4 pt-1">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <Badge variant="outline">
              {DETECTION_LABEL[form.detection_type] ?? form.detection_type}
            </Badge>
            {form.provider && <Badge variant="outline">{form.provider}</Badge>}
            <Badge variant="outline" className="uppercase">{form.form_method || "post"}</Badge>
            {state && (
              <Badge variant={HEALTH_VARIANT[state]}>{HEALTH_LABEL[state]}</Badge>
            )}
          </div>

          <Destination form={form} embedded={embedded} />

          <div className="rounded-lg border p-3 space-y-2">
            <p className="text-xs font-medium">Submissions</p>
            {embedded ? (
              <p className="text-xs text-muted-foreground">
                Submissions happen inside the provider&apos;s iframe, so they can&apos;t be
                counted from the page.
              </p>
            ) : (
              <>
                <Row label="Submits">
                  <span className="tabular-nums">{form.submission_count}</span>
                </Row>
                <Row label="Success">
                  <span className="tabular-nums">{fmtPct(rate)}</span>
                  {errs.length > 0 && (
                    <span className="ml-2 text-muted-foreground">
                      ({errs.length} recorded error{errs.length !== 1 ? "s" : ""})
                    </span>
                  )}
                </Row>
                <Row label="Last submit">{fmtRelative(form.last_submission_at)}</Row>
              </>
            )}
          </div>

          <div className="rounded-lg border p-3 space-y-2">
            <p className="text-xs font-medium">Form</p>
            {form.form_id && (
              <Row label="ID">
                <code className="font-mono">{form.form_id}</code>
              </Row>
            )}
            {form.form_name && (
              <Row label="Name">
                <code className="font-mono">{form.form_name}</code>
              </Row>
            )}
            <Row label="Action">
              {form.form_action ? (
                <code className="font-mono break-all">{form.form_action}</code>
              ) : (
                <span className="text-muted-foreground">
                  None — submitted by JavaScript, not a browser POST
                </span>
              )}
            </Row>
            <Row label="First seen">{fmtDateTime(form.first_seen_at)}</Row>
            <Row label="Last seen">{fmtDateTime(form.last_seen_at)}</Row>
          </div>

          <div className="rounded-lg border p-3 space-y-2">
            <p className="text-xs font-medium">
              Pages ({form.pages.length})
            </p>
            <ul className="space-y-0.5">
              {form.pages.map((p) => (
                <li key={p} className="font-mono text-xs text-muted-foreground break-all">
                  {pagePath(p)}
                </li>
              ))}
            </ul>
          </div>

          <div className="rounded-lg border p-3 space-y-2">
            <p className="text-xs font-medium">Fields ({form.fields.length})</p>
            {form.fields.length === 0 ? (
              <p className="text-xs text-muted-foreground">
                {embedded
                  ? "The fields sit inside a cross-origin iframe, so no in-page script can read them."
                  : "No fields were readable the last time this form was seen."}
              </p>
            ) : (
              <ul className="space-y-1">
                {form.fields.map((f, i) => (
                  <li key={`${f.name}-${f.type}-${i}`} className="flex flex-wrap items-baseline gap-2 text-xs">
                    <code className="font-mono">{f.name || "(unnamed)"}</code>
                    <span className="text-muted-foreground">{f.type}</span>
                    {f.label && <span className="text-muted-foreground">— {f.label}</span>}
                    {f.required && <Badge variant="outline">required</Badge>}
                  </li>
                ))}
              </ul>
            )}
          </div>

          {errs.length > 0 && (
            <div className="rounded-lg border p-3 space-y-2">
              <p className="text-xs font-medium">Recent errors</p>
              <ul className="space-y-1.5">
                {errs.slice(0, 10).map((e) => (
                  <li key={e.id} className="text-xs">
                    <span className="text-muted-foreground">{fmtDateTime(e.created_at)}</span>
                    <span className="ml-2 break-words">{e.message}</span>
                  </li>
                ))}
                {errs.length > 10 && (
                  <li className="text-xs text-muted-foreground">
                    +{errs.length - 10} more
                  </li>
                )}
              </ul>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
