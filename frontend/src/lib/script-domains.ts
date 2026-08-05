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

/** Rows the scripts table will render: one per distinct third-party domain.
 *
 *  The tab badge and the panel heading count this rather than raw Script
 *  records, so three files from googletagmanager.com read as one service
 *  instead of making the badge say 9 beside a 7-row table.
 */
export function countScriptDomains(scripts: { src_url: string }[]): number {
  return new Set(scripts.map((s) => shortDomain(s.src_url))).size;
}
