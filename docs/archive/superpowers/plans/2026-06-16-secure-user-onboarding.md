# Secure User Onboarding + First-Login Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Admin-created users receive a secure set-password link (or a forced-change temp password), and every user changes their own password then enrols in 2FA before reaching the dashboard.

**Architecture:** A new `User.must_change_password` flag drives a new branch in the existing pre-auth `LoginView` (evaluated before the 2FA branches). `TeamCreateUserView` becomes two-path (blank password → emailed set-password link reusing the invite mechanism; admin password → forced change). A new public `FirstPasswordView` lets a mid-login user set their password using the short-lived pre-auth session key, then the existing `/2fa/setup` flow takes over.

**Tech Stack:** Django 5.1 + DRF, Redis cache (pre-auth session), pyotp (existing 2FA), Next.js 16 App Router (proxy routes + client pages), pytest.

---

## Reference facts (verified against the codebase)

- Pre-auth session: `LoginView` sets `cache.set(f"preauth:{session_key}", str(user.pk), timeout=_SESSION_TTL)` where `_SESSION_TTL = 300` ([apps/accounts/totp_views.py](../../../apps/accounts/totp_views.py)).
- `/2fa/setup` reads `session_key` from the URL and passes it as the `X-Pre-Auth-Key` header; `PreAuthSessionAuthentication` resolves the user from `preauth:{key}`. **Therefore `FirstPasswordView` must NOT delete the preauth key** — it refreshes its TTL so 2FA setup can reuse it.
- Invite set-password-link pattern to mirror: [apps/accounts/views.py:259-277](../../../apps/accounts/views.py#L259-L277).
- `auth_client` fixture's user is the **owner** of `team` ([tests/conftest.py](../../../tests/conftest.py)); login endpoint is `POST /api/v1/auth/login/`; tests use `config.settings.test` with locmem cache.
- DRF `response.data` in tests bypasses the envelope — assert `resp.data["..."]` directly.

---

## Task 1: Add `must_change_password` field

**Files:**
- Modify: `apps/accounts/models.py` (User model, after `totp_backup_codes`, ~line 43)
- Create: `apps/accounts/migrations/0010_user_must_change_password.py` (number = next available; use `makemigrations`)

- [ ] **Step 1: Add the field**

In `apps/accounts/models.py`, inside `class User`, directly after the `totp_backup_codes` line:

```python
    # Set when an admin creates the account with a temporary password; forces a
    # password change on first login before any other access.
    must_change_password = models.BooleanField(default=False)
```

- [ ] **Step 2: Generate the migration**

Run: `python manage.py makemigrations accounts`
Expected: creates a migration adding `must_change_password` (a `BooleanField` default `False`).

- [ ] **Step 3: Apply with a fresh test DB and confirm it imports**

Run: `python manage.py migrate` then `python -c "import django,os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings.development'); django.setup(); from apps.accounts.models import User; print('must_change_password' in [f.name for f in User._meta.get_fields()])"`
Expected: prints `True`

- [ ] **Step 4: Commit**

```bash
git add apps/accounts/models.py apps/accounts/migrations/
git commit -m "feat(accounts): add User.must_change_password flag"
```

---

## Task 2: Expose `must_change_password` on `/api/v1/auth/me/`

**Files:**
- Modify: `apps/accounts/serializers.py` (`UserSerializer`, ~line 32-38)
- Test: `tests/accounts/test_onboarding.py` (new file)

- [ ] **Step 1: Write the failing test**

Create `tests/accounts/test_onboarding.py`:

```python
import pytest


@pytest.mark.django_db
def test_me_includes_must_change_password(auth_client):
    resp = auth_client.get("/api/v1/auth/me/")
    assert resp.status_code == 200
    assert "must_change_password" in resp.data
    assert resp.data["must_change_password"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/accounts/test_onboarding.py::test_me_includes_must_change_password -v`
Expected: FAIL — `"must_change_password" not in resp.data`

- [ ] **Step 3: Add field to serializer**

In `apps/accounts/serializers.py`, `UserSerializer.Meta`, add `"must_change_password"` to `fields` and to `read_only_fields`:

```python
        fields = ("id", "email", "first_name", "last_name", "timezone", "active_team", "must_change_password", "created_at")
        read_only_fields = ("id", "email", "active_team", "must_change_password", "created_at")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/accounts/test_onboarding.py::test_me_includes_must_change_password -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/accounts/serializers.py tests/accounts/test_onboarding.py
git commit -m "feat(accounts): expose must_change_password on /me"
```

---

## Task 3: `LoginView` — forced-password-change branch

**Files:**
- Modify: `apps/accounts/totp_views.py` (`LoginView.post`, after the `session_key` is cached, ~line 313, before the `if user.totp_enabled:` block)
- Test: `tests/accounts/test_onboarding.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/accounts/test_onboarding.py`:

```python
from apps.accounts.models import TeamMembership, User


def _make_member(team, *, must_change, totp_enabled=False, password="TempPass1!"):
    u = User.objects.create_user(email="newbie@example.com", password=password)
    u.must_change_password = must_change
    u.totp_enabled = totp_enabled
    u.save(update_fields=["must_change_password", "totp_enabled"])
    TeamMembership.objects.create(user=u, team=team, role=TeamMembership.Role.DEVELOPER)
    return u


@pytest.mark.django_db
def test_login_requires_password_change_when_flagged(api_client, team):
    _make_member(team, must_change=True)
    resp = api_client.post(
        "/api/v1/auth/login/",
        {"email": "newbie@example.com", "password": "TempPass1!"},
        format="json",
    )
    assert resp.status_code == 200
    assert resp.data.get("requires_password_change") is True
    assert resp.data.get("session_key")


@pytest.mark.django_db
def test_password_change_takes_priority_over_2fa_setup(api_client, team):
    # must_change_password set, 2FA not enabled — must NOT short-circuit to requires_setup
    _make_member(team, must_change=True, totp_enabled=False)
    resp = api_client.post(
        "/api/v1/auth/login/",
        {"email": "newbie@example.com", "password": "TempPass1!"},
        format="json",
    )
    assert resp.data.get("requires_password_change") is True
    assert "requires_setup" not in resp.data
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/accounts/test_onboarding.py -k "requires_password_change or priority" -v`
Expected: FAIL — response has `requires_setup`, not `requires_password_change`

- [ ] **Step 3: Add the branch**

In `apps/accounts/totp_views.py`, `LoginView.post`, immediately after:

```python
        # Store a short-lived pre-auth session key
        session_key = secrets.token_hex(32)
        cache.set(f"preauth:{session_key}", str(user.pk), timeout=_SESSION_TTL)
```

insert:

```python
        # Forced password change (admin-created temp password) takes priority
        # over the 2FA gate — the user must own their password first.
        if user.must_change_password:
            return Response({"requires_password_change": True, "session_key": session_key})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/accounts/test_onboarding.py -k "requires_password_change or priority" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/accounts/totp_views.py tests/accounts/test_onboarding.py
git commit -m "feat(auth): login returns requires_password_change before 2FA gate"
```

---

## Task 4: `FirstPasswordView` endpoint

**Files:**
- Modify: `apps/accounts/totp_views.py` (add `FirstPasswordView` class, e.g. after `LoginView`)
- Modify: `apps/accounts/urls.py` (import + route)
- Test: `tests/accounts/test_onboarding.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/accounts/test_onboarding.py`:

```python
@pytest.mark.django_db
def test_first_password_sets_and_clears_flag(api_client, team):
    _make_member(team, must_change=True)
    login = api_client.post(
        "/api/v1/auth/login/",
        {"email": "newbie@example.com", "password": "TempPass1!"},
        format="json",
    )
    session_key = login.data["session_key"]

    resp = api_client.post(
        "/api/v1/auth/first-password/",
        {"session_key": session_key, "password": "BrandNewPass9!"},
        format="json",
    )
    assert resp.status_code == 200

    u = User.objects.get(email="newbie@example.com")
    assert u.must_change_password is False
    assert u.check_password("BrandNewPass9!")


@pytest.mark.django_db
def test_first_password_rejects_expired_session(api_client):
    resp = api_client.post(
        "/api/v1/auth/first-password/",
        {"session_key": "deadbeef", "password": "BrandNewPass9!"},
        format="json",
    )
    assert resp.status_code == 401


@pytest.mark.django_db
def test_first_password_rejects_weak_password(api_client, team):
    _make_member(team, must_change=True)
    login = api_client.post(
        "/api/v1/auth/login/",
        {"email": "newbie@example.com", "password": "TempPass1!"},
        format="json",
    )
    resp = api_client.post(
        "/api/v1/auth/first-password/",
        {"session_key": login.data["session_key"], "password": "123"},
        format="json",
    )
    assert resp.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/accounts/test_onboarding.py -k first_password -v`
Expected: FAIL — 404 (route does not exist yet)

- [ ] **Step 3: Add the view**

In `apps/accounts/totp_views.py`, add near the top with other imports:

```python
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
```

Then add the class (after `LoginView`):

```python
class FirstPasswordView(APIView):
    """POST /api/v1/auth/first-password/ — set the initial password for a user
    flagged must_change_password, using the pre-auth session key from login.

    Keeps the pre-auth session alive (refreshes TTL) so the caller can continue
    straight into the mandatory 2FA setup flow.
    """

    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request):
        from apps.accounts.models import User

        session_key = (request.data.get("session_key") or "").strip()
        new_password = request.data.get("password") or ""
        if not session_key or not new_password:
            return Response(
                {"detail": "session_key and password are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user_id = cache.get(f"preauth:{session_key}")
        if not user_id:
            return Response(
                {"detail": "Session expired or invalid. Please log in again."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return Response(status=status.HTTP_401_UNAUTHORIZED)

        try:
            validate_password(new_password, user=user)
        except DjangoValidationError as exc:
            return Response({"detail": " ".join(exc.messages)}, status=status.HTTP_400_BAD_REQUEST)

        user.set_password(new_password)
        user.must_change_password = False
        user.save(update_fields=["password", "must_change_password"])

        # Refresh the pre-auth window so 2FA setup (same session_key) can proceed.
        cache.set(f"preauth:{session_key}", str(user.pk), timeout=_SESSION_TTL)

        return Response({"detail": "Password set."})
```

- [ ] **Step 4: Wire the URL**

In `apps/accounts/urls.py`, add `FirstPasswordView` to the `apps.accounts.totp_views` import block, and add a route in the `# 2FA` / auth section:

```python
    path("first-password/", FirstPasswordView.as_view(), name="auth-first-password"),
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/accounts/test_onboarding.py -k first_password -v`
Expected: PASS (all three)

- [ ] **Step 6: Commit**

```bash
git add apps/accounts/totp_views.py apps/accounts/urls.py tests/accounts/test_onboarding.py
git commit -m "feat(auth): add first-password endpoint for forced password change"
```

---

## Task 5: `TeamCreateUserView` — optional password, two onboarding paths

**Files:**
- Modify: `apps/accounts/views.py` (`TeamCreateUserView.post`, ~line 456-525)
- Test: `tests/accounts/test_onboarding.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/accounts/test_onboarding.py`:

```python
from apps.accounts.models import PasswordResetRequest


@pytest.mark.django_db
def test_create_user_blank_password_emails_set_password_link(auth_client, team):
    resp = auth_client.post(
        f"/api/v1/auth/teams/{team.id}/users/",
        {"name": "Pat Doe", "email": "pat@example.com", "role": "developer"},
        format="json",
    )
    assert resp.status_code == 201
    u = User.objects.get(email="pat@example.com")
    assert not u.has_usable_password()
    assert u.must_change_password is False
    pr = PasswordResetRequest.objects.get(user=u)
    assert pr.status == PasswordResetRequest.Status.APPROVED
    assert pr.reset_token


@pytest.mark.django_db
def test_create_user_with_password_sets_must_change(auth_client, team):
    resp = auth_client.post(
        f"/api/v1/auth/teams/{team.id}/users/",
        {"name": "Sam Roe", "email": "sam@example.com", "role": "developer", "password": "AdminSet123!"},
        format="json",
    )
    assert resp.status_code == 201
    u = User.objects.get(email="sam@example.com")
    assert u.must_change_password is True
    assert u.check_password("AdminSet123!")
    assert not PasswordResetRequest.objects.filter(user=u).exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/accounts/test_onboarding.py -k create_user -v`
Expected: FAIL — blank-password request currently 400 ("Password must be at least 8 characters"); with-password case lacks `must_change_password`.

- [ ] **Step 3: Rewrite the new-user portion of the view**

In `apps/accounts/views.py`, `TeamCreateUserView.post`:

(a) Remove the hard password requirement. Replace:

```python
        if not password or len(password) < 8:
            return Response({"detail": "Password must be at least 8 characters."}, status=status.HTTP_400_BAD_REQUEST)
```

with:

```python
        if password and len(password) < 8:
            return Response({"detail": "Password must be at least 8 characters."}, status=status.HTTP_400_BAD_REQUEST)
```

(b) Replace the new-user creation block (from `try: validate_password(password)` through the end `send_mail(...)` / `return Response(...)`) with:

```python
        parts = name.split(" ", 1)
        first_name = parts[0]
        last_name = parts[1] if len(parts) > 1 else ""

        if password:
            # Path B — admin set a temporary password; force change on first login.
            try:
                validate_password(password)
            except DjangoValidationError as exc:
                return Response({"detail": " ".join(exc.messages)}, status=status.HTTP_400_BAD_REQUEST)
            user = User.objects.create_user(
                email=email, password=password, first_name=first_name, last_name=last_name,
            )
            user.must_change_password = True
            user.save(update_fields=["must_change_password"])
            email_body = (
                f"Hi {first_name},\n\n"
                f"An account has been created for you on Digivault by {request.user.email}.\n\n"
                f"Email: {email}\n"
                f"Team: {team.name} ({role})\n\n"
                f"Your administrator will share your temporary password separately. "
                f"You'll be asked to set your own password the first time you log in.\n\n"
                f"Log in at: {settings.FRONTEND_URL}/login\n"
            )
        else:
            # Path A — no password; email a set-password link (no credential emailed).
            user = User.objects.create_user(
                email=email, password=None, first_name=first_name, last_name=last_name,
            )
            user.set_unusable_password()
            user.save(update_fields=["password"])
            reset_token = secrets.token_urlsafe(48)
            PasswordResetRequest.objects.create(
                user=user,
                status=PasswordResetRequest.Status.APPROVED,
                reset_token=reset_token,
                approved_by=request.user,
                approved_at=timezone.now(),
                expires_at=timezone.now() + timedelta(days=7),
            )
            set_password_url = f"{settings.FRONTEND_URL}/reset-password?token={reset_token}"
            email_body = (
                f"Hi {first_name},\n\n"
                f"An account has been created for you on Digivault by {request.user.email}.\n\n"
                f"Email: {email}\n"
                f"Team: {team.name} ({role})\n\n"
                f"Set your password (link valid for 7 days):\n{set_password_url}\n\n"
                f"After setting your password you'll be guided through two-factor "
                f"authentication setup.\n"
            )

        membership = TeamMembership.objects.create(user=user, team=team, role=role)
        if not user.active_team:
            User.objects.filter(pk=user.pk).update(active_team=team)

        try:
            send_mail(
                subject="Your Digivault account has been created",
                message=email_body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[email],
                fail_silently=True,
            )
        except Exception as exc:
            logger.error("Failed to send new-user email to %s: %s", email, exc)

        return Response(TeamMembershipSerializer(membership).data, status=status.HTTP_201_CREATED)
```

(c) Confirm imports exist at the top of `views.py`: `secrets`, `timedelta` (from datetime), `timezone` (django.utils), `PasswordResetRequest`, `settings`, `send_mail`, `validate_password`, `DjangoValidationError`. All are already used elsewhere in this file — add any that are missing.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/accounts/test_onboarding.py -k create_user -v`
Expected: PASS (both)

- [ ] **Step 5: Run the full accounts onboarding suite**

Run: `pytest tests/accounts/test_onboarding.py -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add apps/accounts/views.py tests/accounts/test_onboarding.py
git commit -m "feat(accounts): two-path user onboarding (set-password link or forced-change temp password)"
```

---

## Task 6: Frontend proxy route for first-password

**Files:**
- Create: `frontend/src/app/api/auth/first-password/route.ts`

- [ ] **Step 1: Create the public proxy route**

```typescript
import { NextRequest, NextResponse } from "next/server";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// POST — public: set the initial password using a pre-auth session key.
export async function POST(req: NextRequest) {
  const body = await req.json();
  const upstream = await fetch(`${API_BASE}/api/v1/auth/first-password/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await upstream.json().catch(() => ({}));
  const payload = data?.data ?? data;
  return NextResponse.json(payload, { status: upstream.status });
}
```

- [ ] **Step 2: Lint**

Run: `cd frontend && npx eslint src/app/api/auth/first-password/route.ts`
Expected: no errors

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/api/auth/first-password/route.ts
git commit -m "feat(frontend): proxy route for first-password endpoint"
```

---

## Task 7: Frontend `/first-password` page

**Files:**
- Create: `frontend/src/app/(auth)/first-password/page.tsx`

- [ ] **Step 1: Create the page**

```tsx
"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";

export default function FirstPasswordPage() {
  const router = useRouter();
  const [sessionKey] = useState<string>(() => {
    if (typeof window === "undefined") return "";
    return new URLSearchParams(window.location.search).get("session_key") ?? "";
  });
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (password !== confirm) {
      setError("Passwords do not match.");
      return;
    }
    if (!sessionKey) {
      setError("Your session expired. Please sign in again.");
      return;
    }
    setLoading(true);
    try {
      const res = await fetch("/api/auth/first-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_key: sessionKey, password }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data?.detail ?? "Could not set your password.");
        return;
      }
      // Continue into the mandatory 2FA setup, reusing the same pre-auth session.
      router.push(`/2fa/setup?session_key=${sessionKey}`);
    } catch {
      setError("Could not reach the server.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-muted/40 px-4">
      <Card className="w-full max-w-md">
        <CardHeader className="space-y-1">
          <CardTitle className="text-2xl font-bold">Set your password</CardTitle>
          <CardDescription>
            Choose a new password for your account. You&apos;ll set up two-factor authentication next.
          </CardDescription>
        </CardHeader>
        <form onSubmit={handleSubmit}>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="password">New password</Label>
              <Input
                id="password"
                type="password"
                required
                minLength={8}
                autoFocus
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="confirm">Confirm password</Label>
              <Input
                id="confirm"
                type="password"
                required
                minLength={8}
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
              />
            </div>
            {error && <p className="text-sm text-red-600">{error}</p>}
          </CardContent>
          <CardFooter>
            <Button type="submit" className="w-full" disabled={loading}>
              {loading ? "Saving…" : "Set password & continue"}
            </Button>
          </CardFooter>
        </form>
      </Card>
    </div>
  );
}
```

- [ ] **Step 2: Lint**

Run: `cd frontend && npx eslint "src/app/(auth)/first-password/page.tsx"`
Expected: no errors

- [ ] **Step 3: Commit**

```bash
git add "frontend/src/app/(auth)/first-password/page.tsx"
git commit -m "feat(frontend): first-password page that hands off to 2FA setup"
```

---

## Task 8: Login page handles `requires_password_change`

**Files:**
- Modify: `frontend/src/app/(auth)/login/page.tsx` (`handleCredentials`, ~line 37-46)

- [ ] **Step 1: Add the branch**

In `handleCredentials`, immediately before the existing `if (data.requires_setup) {` block, add:

```tsx
      if (data.requires_password_change) {
        router.push(`/first-password?session_key=${data.session_key}`);
        return;
      }
```

- [ ] **Step 2: Lint**

Run: `cd frontend && npx eslint "src/app/(auth)/login/page.tsx"`
Expected: no new errors

- [ ] **Step 3: Commit**

```bash
git add "frontend/src/app/(auth)/login/page.tsx"
git commit -m "feat(frontend): route forced-change users to first-password on login"
```

---

## Task 9: Add Member form — password optional

**Files:**
- Modify: `frontend/src/components/team-management-client.tsx` (password Input + label, ~line 184-195)

- [ ] **Step 1: Make the password field optional with guidance**

Replace the password `<div className="space-y-1.5">` block (label + input) with:

```tsx
                  <div className="space-y-1.5">
                    <Label htmlFor="add-password">Password (optional)</Label>
                    <Input
                      id="add-password"
                      type="password"
                      placeholder="Leave blank to email a set-password link"
                      minLength={8}
                      value={addForm.password}
                      onChange={(e) => setAddForm((f) => ({ ...f, password: e.target.value }))}
                    />
                    <p className="text-xs text-muted-foreground">
                      Leave blank and the new member gets an email to set their own password.
                      If you set one, they&apos;ll be required to change it on first login.
                    </p>
                  </div>
```

(The key change: remove `required`. `minLength={8}` still applies only when a value is present.)

- [ ] **Step 2: Lint**

Run: `cd frontend && npx eslint src/components/team-management-client.tsx`
Expected: no new errors (a pre-existing unused-`Badge` warning may remain — leave it)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/team-management-client.tsx
git commit -m "feat(frontend): make Add Member password optional"
```

---

## Task 10: Full regression + manual smoke

- [ ] **Step 1: Run the backend suite**

Run: `pytest tests/accounts/ -v` (and `pytest -q` for the whole suite if time allows)
Expected: all PASS. Note: use the project venv (`.venv\Scripts\python.exe -m pytest`) — bare `pytest` may resolve to a sibling venv without all deps.

- [ ] **Step 2: Manual smoke (dev server)**

1. As an owner, Add Member with **blank** password → check the dev mail/console for a set-password link → open it → set password → log in → land on `/2fa/setup`.
2. Add Member **with** a password → log in as that user with the temp password → confirm redirect to `/first-password` → set new password → confirm redirect to `/2fa/setup` → finish 2FA → dashboard.
3. Confirm an existing fully-onboarded user logs in unchanged.

- [ ] **Step 3: Final commit (if any cleanup)**

```bash
git add -A && git commit -m "test: onboarding regression pass"
```

---

## Self-Review

- **Spec coverage:** field (T1), `/me` flag (T2), login branch (T3), first-password endpoint (T4), two-path creation + link email (T5), 2FA already enforced (no task — verified existing), frontend proxy/page/login/form (T6-T9). ✅
- **Priority ordering:** login checks `must_change_password` before `totp_enabled`/`requires_setup` — covered by `test_password_change_takes_priority_over_2fa_setup`. ✅
- **Session reuse:** `FirstPasswordView` refreshes (does not delete) `preauth:{session_key}`; `/first-password` page forwards the same `session_key` to `/2fa/setup`. ✅
- **Type/name consistency:** response keys `requires_password_change` + `session_key` identical across backend (T3), login page (T8), and first-password page (T7); endpoint path `/api/v1/auth/first-password/` consistent across T4 backend route, T6 proxy, T7/T8 callers. ✅
- **Out of scope (noted in spec):** legacy `/api/v1/auth/token/` 2FA bypass; the separate forgot-password 401 bug.
