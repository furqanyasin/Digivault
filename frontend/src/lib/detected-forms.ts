/** Detected-form grouping, shared by the server page and the client tab.
 *
 *  Deliberately NOT in forms-tab.tsx, for the same reason as script-domains.ts:
 *  anything exported from a "use client" module becomes a client reference, so a
 *  server component importing it type-checks and lints cleanly and then throws at
 *  runtime. Plain helpers used on both sides of the boundary have to live in a
 *  module that declares neither.
 */

import type { DetectedForm, FormSubmissionError } from "@/lib/api";

/** A form merged across every page it was found on. */
export type FormRow = DetectedForm & {
  pages: string[];
  /** Distinct destinations collected across the pages it appears on. */
  recipients: { to: string[]; cc: string[]; bcc: string[] };
};

/** Every address in one kind, tolerating a row written before the shape existed. */
function kind(f: DetectedForm, name: "to" | "cc" | "bcc"): string[] {
  const value = f.recipients?.[name];
  return Array.isArray(value) ? value : [];
}

// A structural signature for a form, ignoring which page it appeared on, so the
// same form across pages collapses into a single row (with summed submissions).
//
// An id or a name is the whole signature when the form has one. The two other
// candidates both vary between pages for one and the same form, which is what
// left a site-wide form listed once per path it appears on: `form_action`
// resolves to the *document* URL when the form has no action attribute, and
// `fields` covers only the fields currently mounted — a multi-step form shows
// one step at a time. Anonymous forms still need them to be told apart, so they
// keep both, minus the action when it is just the page it was found on.
function formSignature(f: DetectedForm): string {
  if (f.form_id || f.form_name) {
    return ["id", f.detection_type, f.form_id, f.form_name].join("|");
  }
  const fields = f.fields.map((x) => `${x.name}:${x.type}`).join(",");
  const action = f.form_action === f.page_url ? "" : f.form_action;
  return ["anon", f.detection_type, action, f.provider, fields].join("|");
}

// Weakest to strongest, mirroring the backend's own ordering in
// `_apply_page_recipients`: the page markup is a proxy for a form's
// configuration, while the WordPress API and WP Connect are the configuration
// itself. An unset source ranks below all of them.
const SOURCE_RANK: Record<string, number> = {
  "": 0,
  page: 1,
  wp_api: 2,
  wordpress: 3,
};

/** True when this address came out of the site's WordPress, not its markup. */
export function isFromWordPress(f: DetectedForm): boolean {
  return f.recipient_source === "wordpress" || f.recipient_source === "wp_api";
}

/** Rows the forms table will render: one per structurally distinct form.
 *
 *  Keeps the most recently seen row, but sums submission counts so the total
 *  reflects every page the form appears on. Every page it was found on is kept
 *  so the row can say so — a collapsed row showing one path would otherwise read
 *  as "this form is only on that page".
 */
export function dedupeForms(forms: DetectedForm[]): FormRow[] {
  const bySignature = new Map<string, FormRow>();
  for (const f of forms) {
    const sig = formSignature(f);
    const existing = bySignature.get(sig);
    if (!existing) {
      bySignature.set(sig, {
        ...f,
        pages: [f.page_url],
        recipients: {
          to: [...kind(f, "to")],
          cc: [...kind(f, "cc")],
          bcc: [...kind(f, "bcc")],
        },
      });
    } else {
      existing.submission_count += f.submission_count;
      if (!existing.pages.includes(f.page_url)) existing.pages.push(f.page_url);
      // Descriptor detail comes from the richest reading, not the first row the
      // API happened to return. Rows are ordered by page then action, so a
      // server-scan row — whose regex extractor skips inputs with no `name` and
      // cannot see a JS-rendered form at all — sorted ahead of the browser's and
      // made a seven-field contact form render as "Fields (0)". An observation
      // that read nothing is not a form that has nothing.
      if (f.fields.length > existing.fields.length) existing.fields = f.fields;
      for (const name of ["to", "cc", "bcc"] as const) {
        for (const email of kind(f, name)) {
          if (!existing.recipients[name].includes(email)) {
            existing.recipients[name].push(email);
          }
        }
      }
      // One form's copies across pages share a destination, but not necessarily
      // a source: WordPress fills the rows it can match, and the markup fills
      // the rest. Report the strongest for the merged row. Ranked rather than
      // a single equality test, which knew only about "wordpress" and so read
      // every `wp_api` answer — the source the live sweep actually writes — as
      // if it had come out of the page markup.
      if (SOURCE_RANK[f.recipient_source] > SOURCE_RANK[existing.recipient_source]) {
        existing.recipient_source = f.recipient_source;
      }
      if (f.last_submission_at && (!existing.last_submission_at || f.last_submission_at > existing.last_submission_at)) {
        existing.last_submission_at = f.last_submission_at;
      }
      if (f.last_seen_at > existing.last_seen_at) {
        existing.page_url = f.page_url;
        existing.last_seen_at = f.last_seen_at;
      }
    }
  }
  return Array.from(bySignature.values());
}

// A friendly name for a form: its name/id, else the embedded provider, else
// the page it lives on.
export function formLabel(f: DetectedForm): string {
  if (f.form_name) return f.form_name;
  if (f.form_id) return f.form_id;
  if (f.provider) return f.provider;
  return `Form on ${pagePath(f.page_url)}`;
}

export function pagePath(url: string): string {
  return url.replace(/^https?:\/\/[^/]+/, "") || "/";
}

/** The form's action, or null when it has none of its own.
 *
 *  A form with no action attribute is not action-less in the data: the browser's
 *  `form.action` getter returns the document URL, and the backend now resolves
 *  every source the same way, so the stored action of an Elementor-style AJAX
 *  form is simply the page it sits on. Printing that reads as a destination the
 *  form does not have.
 */
export function formAction(f: FormRow): string | null {
  if (!f.form_action) return null;
  if (f.form_action === f.page_url) return null;
  return f.pages.includes(f.form_action) ? null : f.form_action;
}

/** How many addresses a form delivers to in total, across To, Cc and Bcc. */
export function destinationCount(f: FormRow): number {
  return f.recipients.to.length + f.recipients.cc.length + f.recipients.bcc.length;
}

/** The one address to show when there is only room for one.
 *
 *  Falls back To -> Cc -> Bcc, mirroring the backend's primary_recipient() in
 *  apps/scripts/recipients.py: a Bcc-only form does have a destination, and
 *  reporting "" for it would read as "nobody receives this."
 */
export function primaryRecipient(f: FormRow): string {
  return f.recipients.to[0] ?? f.recipients.cc[0] ?? f.recipients.bcc[0] ?? "";
}

// Errors that belong to a form. The snippet identifies an error's form as
// `id || name`, while a detected form keeps id and name in separate columns, so
// matching on id alone could never link a form identified only by its name —
// every Elementor form, among others. Those forms always read 100% success no
// matter how many failures were recorded against them.
export function errorsForForm(
  f: DetectedForm,
  errors: FormSubmissionError[]
): FormSubmissionError[] {
  const keys = [f.form_id, f.form_name].filter(Boolean);
  if (keys.length === 0) return [];
  return errors.filter((e) => e.form_id && keys.includes(e.form_id));
}

// Share of observed submits that didn't produce a server-side failure. Null when
// nothing has been submitted yet — 0 submits is "no data", not "0% success".
export function successRate(
  f: DetectedForm,
  errors: FormSubmissionError[]
): number | null {
  const submits = f.submission_count || 0;
  if (submits === 0) return null;
  const failed = Math.min(errorsForForm(f, errors).length, submits);
  return ((submits - failed) / submits) * 100;
}

export type Health = "healthy" | "degraded" | "failing";

export function health(rate: number | null): Health | null {
  if (rate === null) return null;
  if (rate < 50) return "failing";
  if (rate < 95) return "degraded";
  return "healthy";
}

export const HEALTH_LABEL: Record<Health, string> = {
  healthy: "Healthy",
  degraded: "Degraded",
  failing: "Failing",
};

export const HEALTH_VARIANT: Record<Health, "success" | "warning" | "destructive"> = {
  healthy: "success",
  degraded: "warning",
  failing: "destructive",
};

export function fmtPct(rate: number | null): string {
  if (rate === null) return "—";
  // Keep a decimal only when it carries information (99.3% vs a clean 100%).
  return `${Number.isInteger(rate) ? rate : rate.toFixed(1)}%`;
}

/** Forms the site owns — third-party embedded forms are listed separately. */
function managedForms(forms: DetectedForm[]): FormRow[] {
  return dedupeForms(forms).filter((f) => f.is_managed !== false);
}

/** The number the tab badge and the "Detected forms" tile both show.
 *
 *  Counts the rows the table renders, not raw DetectedForm records: one form
 *  living on eight paths is eight records, and counting records made the badge
 *  read 12 next to a 5-row table.
 */
export function countManagedForms(forms: DetectedForm[]): number {
  return managedForms(forms).length;
}
