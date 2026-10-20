# Credential Team Sharing — Design Spec

**Date:** 2026-05-26
**Status:** Approved, ready for plan
**Area:** `apps/credentials/`, `frontend/src/components/credentials-vault-client.tsx`

## Problem

Today every team member sees every team credential — visibility is enforced only at the team level (`Credential.objects.filter(team=team)`). The credentials page has a "Share" icon that opens a dialog labelled *"Share these credentials securely"*, but the dialog only reveals/copies the plaintext. There is no actual mechanism to share a specific credential with selected internal team members.

We want per-credential access control with role-based defaults and an explicit Share flow for developers.

## Goals

- Owners and managers see all team credentials by default.
- Developers see only credentials they created or had explicitly shared with them.
- A creator (or any owner/manager) can share a credential with selected developers via a dedicated Share dialog.
- Shared developers can view + reveal only — no edit, no delete, no re-share.
- All share / unshare actions are audit-logged.
- Existing developers do not lose access to credentials they could previously see.

## Non-goals

- External (public link) sharing.
- Per-share permission tiers (edit vs. view).
- Website-level inheritance (i.e., "if you can see the website you can see its credentials"). Each credential is governed by its own share list regardless of website link.
- Notification on share (out of scope — can be added later).

## Data model

New table `CredentialShare` in [apps/credentials/models.py](apps/credentials/models.py):

```python
class CredentialShare(BaseModel):
    credential = models.ForeignKey(
        Credential, on_delete=models.CASCADE, related_name="shares"
    )
    user = models.ForeignKey(
        "accounts.User", on_delete=models.CASCADE, related_name="credential_shares"
    )
    shared_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL,
        null=True, related_name="credential_shares_granted",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["credential", "user"], name="credentialshare_unique_per_user"
            )
        ]
        indexes = [models.Index(fields=["user", "credential"])]
```

No "permission" column — every share grants view + reveal only. Editing/deleting is gated by role + ownership separately.

## Visibility rules

A user `u` may **see** a credential `c` iff any of:

1. `u`'s role on `c.team` is `owner` or `manager`, OR
2. `c.created_by_id == u.id`, OR
3. A `CredentialShare(credential=c, user=u)` row exists.

Implement as `Credential.objects.visible_to(user)` on a custom manager/queryset. Replace the current `filter(team=team)` queryset in:

- `TeamCredentialListCreateView.get_queryset`
- `CredentialListCreateView.get_queryset` (website-scoped)
- `CredentialDetailView.get_queryset`
- `CredentialRevealView.post` (`Credential.objects.get(...)` → visibility-filtered)
- `ExtensionCredentialLookupView.get_queryset`

`ExtensionCredentialSaveView` continues to write under the active user; the new credential's `created_by` is the saving user so they get access automatically.

## Modification rules

A user `u` may **modify** (PATCH/DELETE/share/unshare) a credential `c` iff:

- `u`'s role on `c.team` is `owner` or `manager`, OR
- `c.created_by_id == u.id`.

A shared developer cannot modify. Implement as `apps/credentials/permissions.py::can_modify_credential(user, credential) -> bool` used by:

- `CredentialDetailView.update` and `perform_destroy` (return 403 on false).
- New share endpoints (see below).

## API endpoints

All under `/api/v1/credentials/<pk>/shares/`:

- `GET /api/v1/credentials/<pk>/shares/`
  Returns `[{ user_id, email, name, role, shared_by_email, created_at }]` for every `CredentialShare` row. Caller must have visibility on the credential.

- `POST /api/v1/credentials/<pk>/shares/`
  Body: `{ "user_ids": ["<uuid>", ...] }`.
  For each id: validate the user is a member of `credential.team` with role `developer`. Upsert `CredentialShare`. Ignore (200, no-op) ids that are owners/managers (they already have access) or already shared. Returns the updated share list. Caller must pass `can_modify_credential`.

- `DELETE /api/v1/credentials/<pk>/shares/<user_id>/`
  Removes the row. Caller must pass `can_modify_credential`. 204 on success, 404 if no row.

Audit each call via `AuditService.log_request` with new actions added to `apps/audit/models.py::ActivityLog.Action`:

- `CREDENTIAL_SHARED` — metadata `{ shared_with_user_ids: [...] }`.
- `CREDENTIAL_UNSHARED` — metadata `{ unshared_user_id: "..." }`.

URL wiring in [apps/credentials/urls.py](apps/credentials/urls.py).

## Serializers

- `CredentialShareSerializer` — `id, user (nested: id, email, name, role), shared_by_email, created_at`.
- `CredentialShareWriteSerializer` — `user_ids: list[UUIDField]`.

`role` is computed by joining `accounts.TeamMembership`.

## Migration (data backfill)

Migration `0005_credentialshare_and_backfill.py`:

1. Schema migration creates `CredentialShare`.
2. Data migration: for every existing `Credential c`, find all `TeamMembership(team=c.team, role="developer")` and create a `CredentialShare(credential=c, user=m.user, shared_by=None)` for each. Idempotent (uses `bulk_create(ignore_conflicts=True)`).

Reason: preserves current behaviour for existing data. New credentials created after the migration get no auto-share — they follow the new rules from day one.

## Frontend

[frontend/src/components/credentials-vault-client.tsx](frontend/src/components/credentials-vault-client.tsx)

**Rename current "Share" icon → "Reveal"** (the dialog already shows plaintext and copy buttons; the label is what's wrong). Keep the existing dialog as the reveal flow.

**Add a new Share icon** on each credential card, rendered only when `can_modify` is true for the current user (creator id matches or `myRole in ["owner", "manager"]`).

Clicking opens a new `<CredentialShareDialog credentialId={...} />` component:

- **Header:** credential label + small subtitle "Manage who in your team can view this credential".
- **Section "Always has access"** — read-only avatar+name chips for every owner and manager of the active team. Small grey footer: "Owners and managers automatically see all team credentials."
- **Section "Shared with"** — list of current developer shares (avatar, name, email, "shared by X · 3d ago"), each with a trash icon → `DELETE /shares/<user_id>/`.
- **Section "Add developers"** — searchable multi-select (uses existing `TeamMember` data from `/api/v1/auth/teams/<id>/members/`) showing developers who are not already shared. Selecting + clicking **Share** posts to the share endpoint, refreshes the list, clears selection.
- No password / username / login URL shown anywhere in this dialog.

**Data fetching:** server component (page.tsx) already fetches `me`, `members`, `credentials`. Pass `members` down to `CredentialsVaultClient` so the Share dialog can render the role chips and the developer picker without an extra round trip. Share-list itself is fetched on dialog open via a small client fetch.

**Permission UI:**
- Edit and Delete icons on a card stay visible only when `can_modify` is true (owner/manager/creator). Currently the page exposes edit/delete to everyone in the team; we tighten this to match the backend rule.
- Reveal icon stays available to anyone who can see the credential.

## Audit

Beyond the two new `ActivityLog` actions, no change. Continue using `AuditService.log_request` for every share / unshare. Existing `CredentialAccessLog` (reveal-time audit) is untouched.

## Testing

Backend (pytest):

- `Credential.objects.visible_to(user)` returns expected set for each role × (created vs. shared vs. neither).
- Developer not in share list:
  - GET list → credential absent.
  - GET detail → 404.
  - POST reveal → 404.
  - PATCH → 403.
  - DELETE → 403.
  - POST shares → 403.
- Developer in share list:
  - GET list → credential present.
  - POST reveal → 200, audit row written.
  - PATCH → 403, DELETE → 403.
- Manager and owner:
  - Full access regardless of share rows.
- POST shares with an owner/manager user_id → no-op (200) and no row created.
- POST shares with a non-team-member user_id → 400.
- DELETE shares revoke → developer immediately loses access on next request.
- Audit logs written for share + unshare.
- Migration data backfill: existing developer × existing credential pairs all get rows; running it twice is a no-op.

Frontend: type-check + lint. Manual smoke via `npm run dev`:
- Share dialog opens, lists current shares, lets a manager add and remove a developer, and the developer (in a second browser session) sees the credential after refresh.

## Files touched

- `apps/credentials/models.py` — add `CredentialShare`, custom queryset/manager.
- `apps/credentials/permissions.py` — new module with `can_modify_credential`.
- `apps/credentials/serializers.py` — new share serializers.
- `apps/credentials/views.py` — swap querysets to `visible_to`, gate modify endpoints, add share views.
- `apps/credentials/urls.py` — wire share routes.
- `apps/credentials/migrations/0005_credentialshare_and_backfill.py` — schema + data migration.
- `apps/audit/models.py` — two new `ActivityLog.Action` choices.
- `tests/credentials/test_sharing.py` — new test module.
- `frontend/src/components/credentials-vault-client.tsx` — rename reveal action, add Share icon + dialog, tighten edit/delete visibility.
- `frontend/src/components/credential-share-dialog.tsx` — new component.
- `frontend/src/app/(dashboard)/credentials/page.tsx` — pass `members` down.
- `frontend/src/lib/api.ts` — types for `CredentialShare`.

## Open questions

None. Backfill keeps existing developers' access; website-linked credentials follow the same per-credential rule.
