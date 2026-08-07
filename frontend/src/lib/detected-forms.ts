/** Detected-form grouping, shared by the server page and the client tab.
 *
 *  Deliberately NOT in forms-tab.tsx, for the same reason as script-domains.ts:
 *  anything exported from a "use client" module becomes a client reference, so a
 *  server component importing it type-checks and lints cleanly and then throws at
 *  runtime. Plain helpers used on both sides of the boundary have to live in a
 *  module that declares neither.
 */

import type { DetectedForm } from "@/lib/api";

/** A form merged across every page it was found on. */
export type FormRow = DetectedForm & { pages: string[] };

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
      bySignature.set(sig, { ...f, pages: [f.page_url] });
    } else {
      existing.submission_count += f.submission_count;
      if (!existing.pages.includes(f.page_url)) existing.pages.push(f.page_url);
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
