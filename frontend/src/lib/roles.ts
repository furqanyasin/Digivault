/** Team role slugs and their display strings.
 *
 * Role slugs are not display strings: "seo_executive" title-cased by CSS reads
 * "Seo_executive". Everything that renders a role name goes through
 * `roleLabel()` rather than `capitalize`.
 *
 * Mirrors TeamMembership.Role in apps/accounts/models.py.
 */

export const ROLE_LABEL: Record<string, string> = {
  owner: "Owner",
  manager: "Manager",
  developer: "Developer",
  custom: "Custom",
  seo_executive: "SEO Executive",
  // Legacy — retired from the pickers, still valid on existing memberships.
  editor: "Editor",
  seo: "SEO",
  viewer: "Viewer",
};

export function roleLabel(role: string): string {
  return ROLE_LABEL[role] ?? role;
}

/** Member-level roles a credential can be shared with — mirrors
 *  SHAREABLE_ROLES in apps/credentials/services.py. Owners and managers see
 *  the whole vault already, and a viewer can never decrypt, so neither is
 *  listed. Filtering on "developer" alone hid every SEO executive. */
export const SHAREABLE_ROLES = new Set([
  "developer",
  "seo_executive",
  "seo",
  "editor",
]);
