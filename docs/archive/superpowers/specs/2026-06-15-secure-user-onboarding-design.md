# Secure User Onboarding + First-Login Hardening — Design

**Date:** 2026-06-15
**Status:** Approved (design); pending implementation plan

## Problem

When an admin creates a team member today ([`TeamCreateUserView`](../../../apps/accounts/views.py)),
the admin must type the new user's password, the user is created with it, and the
welcome email is sent **without** the password. The admin then has to share the
password out-of-band. There is no forced password rotation and no system-driven
secure handoff.

The request: new users should receive a secure credential by email and set their
own password, and every user must enrol in two-factor authentication (2FA).

## Key finding: 2FA is already mandatory

`LoginView` ([`apps/accounts/totp_views.py`](../../../apps/accounts/totp_views.py))
already returns `requires_setup: true` for any authenticated user who has not
enrolled in 2FA, and the frontend login page redirects them to `/2fa/setup`
before issuing JWTs. **No new work is needed to make 2FA mandatory** on the
normal login path.

Known gap (out of scope, noted for follow-up): the legacy
`POST /api/v1/auth/token/` endpoint issues JWTs directly and bypasses the 2FA
gate. The UI never uses it, but a hardening follow-up should close it.

## Decisions (from brainstorming)

1. **Default credential = emailed set-password link** (not a literally emailed
   password). Reuses the existing invite/reset machinery; no password ever
   travels by email.
2. **Admin password field stays, but optional.** If the admin types a password,
   the user is created with it and forced to change it on first login. If left
   blank, the system emails a set-password link.
3. **First-login order: change password → 2FA setup → dashboard.**

## Onboarding paths

The "Add Member" form keeps Name / Email / Role and an **optional** Password.

### Path A — blank password (default, recommended)
1. Backend creates the user with an *unusable* password.
2. Backend pre-approves a `PasswordResetRequest` and emails a set-password link
   (same mechanism as [`InvitationAcceptView`](../../../apps/accounts/views.py)).
3. User clicks the link → sets their own password.
4. First login → 2FA setup (mandatory, already enforced) → dashboard.

`must_change_password` is **not** set in this path — the user already chose their
own password via the link.

### Path B — admin types a password
1. Backend creates the user with that password and sets
   `must_change_password = True`.
2. Welcome email notifies the user (no password in the email); admin shares the
   temporary password out-of-band, as today.
3. First login with the temp password → **forced password change** → 2FA setup →
   dashboard.

## First-login flow (Path B / any `must_change_password` user)

New `User.must_change_password` boolean (default `False`).

`LoginView` gains a branch evaluated **before** the existing 2FA checks:

```
authenticate(email, password) OK
  ├─ must_change_password?  → { requires_password_change: true, session_key }
  ├─ totp_enabled?          → { requires_2fa: true, session_key }   (existing)
  └─ else                   → { requires_setup: true, session_key } (existing)
```

- Frontend login sees `requires_password_change` → routes to a new
  **`/first-password`** page, authorised by the short-lived pre-auth
  `session_key` (no JWT yet).
- New endpoint **`POST /api/v1/auth/first-password/`**: accepts `session_key` +
  new password, runs `validate_password`, sets the password, clears
  `must_change_password`, and keeps the pre-auth session valid.
- On success the page continues to `/2fa/setup` (still required because
  `totp_enabled` is `False`). Completing 2FA confirm issues the JWT → dashboard.

### Defense in depth
`MeView` exposes `must_change_password` so the dashboard layout can guard against
a user who somehow holds a token while still flagged, redirecting them to
`/first-password`.

## Components & boundaries

| Unit | Responsibility | Depends on |
|------|----------------|------------|
| `User.must_change_password` | Persisted flag driving the forced-change branch | migration |
| `TeamCreateUserView` | Optional password; pick Path A or B; send the right email | `PasswordResetRequest`, `send_mail` |
| `LoginView` | New `requires_password_change` branch (priority over 2FA) | pre-auth cache |
| `FirstPasswordView` | Pre-auth password set + clear flag | pre-auth cache, `validate_password` |
| `MeView` | Expose flag for dashboard guard | — |
| `/first-password` page | Collect new password, then hand off to `/2fa/setup` | login proxy, first-password proxy |
| Add Member form | Password optional + helper text | — |

## Error handling
- `first-password`: expired/invalid `session_key` → 401, prompt re-login;
  password failing `validate_password` → 400 with messages.
- `TeamCreateUserView`: duplicate email, role-too-high, invalid role — unchanged
  guards; email send failures are logged, not fatal (matches current behaviour).

## Testing
- User creation Path A (blank pw): unusable password set, reset request created,
  link email attempted.
- User creation Path B (admin pw): `must_change_password=True`.
- Login returns `requires_password_change` when flagged, and that branch takes
  priority over `requires_setup`.
- `FirstPasswordView`: valid session sets password + clears flag; expired session
  401; weak password 400.
- After first-password, login proceeds into 2FA setup.
- `MeView` includes `must_change_password`.

## Out of scope
- Closing the legacy `/api/v1/auth/token/` 2FA bypass (separate follow-up).
- The forgot-password 401 bug currently under separate investigation.
