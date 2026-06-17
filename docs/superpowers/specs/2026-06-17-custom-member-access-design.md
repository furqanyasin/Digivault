# Custom Per-Member Feature Access — Design

**Date:** 2026-06-17
**Status:** Approved → implemented

## Problem
Team roles offered Viewer/Developer/Editor/Seo/Manager. Editor and Seo are
unused and confusing, and there's no way to grant a member a bespoke subset of
the product (e.g. "Reports + Websites only").

## Decision
- **Remove Editor and Seo** from the role picker (kept valid in the DB so any
  existing membership still works — just no longer offered).
- **Add a `custom` role.** A custom member's accessible sections are stored on
  the membership as `feature_access` (a list of feature keys).
- **Enforcement is frontend-only** (per the owner's explicit choice, for speed).
  The sidebar hides disallowed sections and a client guard redirects blocked
  pages to the dashboard. **The API is NOT restricted** — a custom member could
  still reach blocked data (incl. Credentials) via direct API calls. Recommended
  fast-follow: backend-gate Credentials at minimum.
- White-label was considered and **dropped** from scope.

## Feature keys (9)
`websites, clients, monitors, status_pages, alerts, reports, renewals,
credentials, activity_log`. Dashboard and My Account are always available.
`custom` sits at the developer privilege tier (level 2) for existing backend
role gates.

## Backend
- `TeamMembership`: `+ CUSTOM` role, `+ feature_access` JSONField (default `[]`).
- `ROLE_LEVELS` (views + permissions): `custom = 2`.
- `TeamMemberDetailView.patch`: when `role == custom`, save `feature_access`
  filtered to `CUSTOM_FEATURE_KEYS`; otherwise clear it.
- Serializers: `TeamMembershipSerializer.feature_access`;
  `TeamSerializer.my_features` (requesting user's keys, for nav gating).
- Migration `0009`.

## Frontend
- Team management: role options are Viewer/Developer/Manager/Custom; when a
  member is Custom, toggleable feature chips save `feature_access` via PATCH.
- Layout: nav filtered by `activeTeam.my_features` when `my_role === custom`.
- `FeatureGuard` client component redirects custom members off blocked routes.

## Testing
- Backend: feature sanitization, clearing on role switch, `my_features` output.
- Frontend: typecheck.
