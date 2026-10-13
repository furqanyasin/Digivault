/** Script-domain grouping, shared by the server page and the client table.
 *
 *  Deliberately NOT in scripts-tab.tsx. That module is "use client", so anything
 *  exported from it becomes a client reference — importing it into a server
 *  component type-checks and lints cleanly, then throws at runtime with
 *  "Attempted to call countScriptDomains() from the server". Plain helpers used
 *  on both sides of the boundary have to live in a module that declares neither.
 */

/** Hostname of a script URL, used as the grouping key for one third-party. */
export function shortDomain(url: string): string {
  try {
    const u = new URL(url.startsWith("//") ? `https:${url}` : url);
    return u.hostname;
  } catch {
    return url;
  }
}

/** The vendor name a row is labelled with. `provider_family` collapses the
 *  classifier's per-product names — Google Analytics 4, Google Tag Manager and
 *  Google Ads are all "Google", every HubSpot product is "HubSpot" — so a
 *  vendor reads once instead of four times.
 *
 *  Falls back to `provider` when the field is absent: the frontend deploys
 *  separately from the backend (host-pm2 vs Docker), so a frontend that ships
 *  first must keep rendering rather than label every row "undefined".
 */
export function providerLabel(script: {
  provider?: string;
  provider_family?: string;
}): string {
  return script.provider_family || script.provider || "unknown";
}

/** Whether a script belongs on the tracking inventory the Scripts tab shows.
 *
 *  The decision is the backend's (`is_tracked`, from apps/scripts/tracked.py)
 *  so the tab badge, the overview tile and the table can never disagree about
 *  which rows exist. It keeps only the installed tags of the monitored vendors
 *  (Google, HubSpot, Hotjar, WhatConverts, ClickUp, GoHighLevel) plus anything
 *  the backend flags as high-confidence injected code, which it folds into
 *  `is_tracked` itself.
 *
 *  `?? true` rather than `=== true`: an older backend omits the field, and the
 *  safe default there is to show the script, not to blank the whole tab.
 */
export function isTrackedScript(script: { is_tracked?: boolean }): boolean {
  return script.is_tracked ?? true;
}

/** The identity a scripts-table row is grouped under: the provider family when
 *  we can name it, the domain otherwise.
 *
 *  Prefixed so a provider literally named after a host cannot collide with the
 *  domain fallback of some other script.
 */
export function scriptGroupKey(script: {
  provider?: string;
  provider_family?: string;
  src_url: string;
}): string {
  const label = providerLabel(script);
  return label !== "unknown"
    ? `provider:${label}`
    : `domain:${shortDomain(script.src_url)}`;
}

/** Rows the scripts table will render.
 *
 *  The tab badge and the panel heading count this rather than raw Script
 *  records, so nine files from googletagmanager.com read as one service instead
 *  of making the badge say 9 beside a 1-row table.
 *
 *  It must group exactly as the table does. It used to count distinct *domains*
 *  while the table grouped by *provider*, and the two disagree whenever one
 *  host serves two services (googletagmanager.com serves both GTM and GA4) or
 *  one service serves from two hosts (Hotjar) — the badge read 9 above a table
 *  of 8 rows.
 *
 *  Pass it the same filtered list the table renders. It counts groups, not
 *  tracked-ness, so handing it an unfiltered list makes the badge count the
 *  jQuery and YouTube rows the table no longer shows.
 */
export function countScriptGroups(
  scripts: { provider?: string; provider_family?: string; src_url: string }[]
): number {
  return new Set(scripts.map(scriptGroupKey)).size;
}
