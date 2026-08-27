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

/** The identity a scripts-table row is grouped under: the provider when we can
 *  name it, the domain otherwise.
 *
 *  Prefixed so a provider literally named after a host cannot collide with the
 *  domain fallback of some other script.
 */
export function scriptGroupKey(script: { provider?: string; src_url: string }): string {
  return script.provider && script.provider !== "unknown"
    ? `provider:${script.provider}`
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
 */
export function countScriptGroups(
  scripts: { provider?: string; src_url: string }[]
): number {
  return new Set(scripts.map(scriptGroupKey)).size;
}
