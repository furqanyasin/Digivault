# Role-Based Access, My Account, and Departments — Design

**Date:** 2026-06-10
**Status:** Approved, implementing

## Problem

1. Renewal Center, Team, and Settings should not be visible to developers.
2. Each user needs to manage their own 2FA — but Settings (which holds 2FA today)
   is being hidden from developers.
3. The ClickUp integration should be owner/manager-only.
4. Activity log: each user sees their own; managers/owners see all. (Already true.)
5. The agency runs departments (SEO, Web) that each have their own clients and
   users, and wants member roles like Editor / SEO.

## Phase 1 — role access + My Account

- **New `/account` ("My Account") page, all roles.** Holds per-user 2FA
  (setup / disable / regenerate backup codes) and read-only profile (name,
  email, role, active team). The 2FA section moves here out of Settings.
- **`/settings` → owner/manager only.** Keeps only the ClickUp integration +
  team config. With Settings hidden from developers, ClickUp is automatically
  owner/manager-only.
- **Nav gating:** mark Renewal Center and Settings `managerOnly` (reusing the
  `Team.my_role` mechanism already added for the Team tab). Add an **Account**
  nav item visible to everyone. Each gated page also gets a server-side guard
  rendering an "access restricted" notice on direct navigation.
- **Activity Log** stays visible to all — backend already scopes it per-user for
  non-managers ([apps/audit/views.py](apps/audit/views.py)).

## Phase 2 — departments + custom roles

### Roles
Add `editor` and `seo` as **member-level** roles (same privilege tier as
`developer`). Touch points:
- `TeamMembership.Role` enum (+ no-op choices migration).
- `RolePermission.ROLE_LEVELS` and `accounts.views.ROLE_LEVELS`: `editor` and
  `seo` = level 2 (same as developer).
- `CredentialService._REVEAL_ROLES`: add `editor`, `seo` (they can reveal
  credentials shared with them; they still only *see* shared ones).
- `Credential.visible_to`: unchanged — only owner/manager see all; editor/seo,
  like developer, see only shares.
- Invite + role-change dropdowns include the new roles.

Behaviourally editor/seo == developer for all current gating (hidden from
Team/Settings/Renewal, own activity log only, no team management). The labels
exist for organisation and future role-specific features.

### Departments
A `Team` already *is* a department: clients/websites/credentials are team-scoped
and isolated, role is per-team, and the team switcher handles users in multiple
departments. Gaps to fill:
- **"Create department"** action for owners (existing `POST /api/v1/auth/teams/`).
- Invite a user into a chosen department + role; allow adding an existing user
  to a second department.

Self-registration still creates a personal team, but invited users only ever
*join* an existing team — so the owner creates SEO + Web once and invites
everyone into the right one. No new abstraction; no data-model change beyond the
role enum.

## Testing

- `my_role` already tested. Add: editor/seo accepted by invite/role-change;
  editor/seo can reveal a shared credential but cannot manage team/settings;
  ROLE_LEVELS ordering. Frontend: typecheck.

## Out of scope

GMB tracking and blog-post tracking modules — handled in Google/WordPress, not
Digivault.
