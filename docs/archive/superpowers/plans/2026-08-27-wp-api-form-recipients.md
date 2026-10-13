# WP API Form Recipients Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fill in a form's "Goes to" address for Elementor and Gravity Forms sites by reading the site's own WordPress REST API with credentials already in the vault, so those sites no longer need the WP Connect PHP snippet.

**Architecture:** A new `apps/websites/wp_api_forms.py` resolves a WordPress credential for a website, presents it as HTTP Basic auth through the existing `apps.common.outbound` client, and runs two readers (Elementor, Gravity Forms). Each reader emits the same entry dicts the WP Connect path already produces, so `wp_forms.apply_recipients()` — parametrised with a new source — does the matching and writing unchanged.

**Tech Stack:** Django 5.1, DRF, Celery, `apps.common.outbound` (urllib-based, SSRF-guarded), Fernet-encrypted `Credential` model, Next.js 16 frontend.

**Spec:** `docs/superpowers/specs/2026-08-27-wp-api-form-recipients-design.md`

## Global Constraints

- Coverage is **Elementor >= 3.27.0** and **Gravity Forms >= 2.4.21.4** only. Contact Form 7 and WPForms are unreachable server-side and must keep falling back to WP Connect. Do not add readers for them.
- All outbound HTTP goes through `apps.common.outbound.fetch`. Never use `requests` or bare `urllib` — the per-host token bucket, honest user-agent, WAF fingerprinting and per-redirect-hop SSRF guard are mandatory.
- Never impersonate a browser user-agent.
- Precedence is `page < wp_api < wordpress`. A WP Connect answer always wins.
- Every failure is a normal state: no raise, no `logger.error`/`logger.exception`, no effect on health score. Use `logger.debug` / `logger.warning`.
- A truncated response is a **failure**, never "no recipient found".
- An authentication failure must be persisted and not retried on the next daily sweep.
- Tests: run `pytest --create-db` after any migration. The autouse `no_network_in_tests` fixture in `tests/conftest.py` only patches Website-creation checks — every `outbound.fetch` in these tests needs its own mock.
- DRF `response.data` in tests is the raw payload, not the envelope.

---

### Task 1: Add the `wp_api` recipient source and protect it from pageviews

Establishes the new source and the precedence guard before anything can write it. Without the guard, every pageview would wipe an API-sourced address with the markup's empty reading.

**Files:**
- Modify: `apps/scripts/models.py:234-236`
- Modify: `apps/scripts/tasks.py:522-560` (`_apply_page_recipients`)
- Create: `apps/scripts/migrations/00XX_detectedform_wp_api_source.py` (generated)
- Test: `tests/scripts/test_recipient_precedence.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `DetectedForm.RecipientSource.WP_API` (value `"wp_api"`), consumed by Tasks 4, 7, 9, 10.

- [ ] **Step 1: Write the failing test**

```python
# tests/scripts/test_recipient_precedence.py
import pytest

from apps.scripts.models import DetectedForm
from apps.scripts.tasks import _apply_page_recipients

pytestmark = pytest.mark.django_db


def _form(website, **kwargs):
    return DetectedForm.objects.create(
        website=website,
        page_url="https://example.com/contact",
        fingerprint="abc123",
        **kwargs,
    )


def test_pageview_does_not_clear_a_wp_api_recipient(website):
    """The markup reads nothing on an Elementor form. That is not evidence the
    configured address is gone."""
    form = _form(
        website,
        recipients={"to": ["leads@example.com"], "cc": [], "bcc": []},
        recipient_source=DetectedForm.RecipientSource.WP_API,
    )

    _apply_page_recipients(form, {"recipients": {"to": "", "cc": "", "bcc": ""}})

    form.refresh_from_db()
    assert form.recipients["to"] == ["leads@example.com"]
    assert form.recipient_source == DetectedForm.RecipientSource.WP_API


def test_pageview_does_not_override_wp_api_with_a_markup_address(website):
    """Even a non-empty markup reading loses to the site's own configuration."""
    form = _form(
        website,
        recipients={"to": ["leads@example.com"], "cc": [], "bcc": []},
        recipient_source=DetectedForm.RecipientSource.WP_API,
    )

    _apply_page_recipients(form, {"recipients": {"to": "spam@example.com"}})

    form.refresh_from_db()
    assert form.recipients["to"] == ["leads@example.com"]
```

The `website` fixture already exists in `tests/conftest.py`. If it does not resolve, check the fixture name there before inventing one.

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/scripts/test_recipient_precedence.py -v`
Expected: FAIL — `AttributeError: WP_API` on `RecipientSource`.

- [ ] **Step 3: Add the choice**

```python
# apps/scripts/models.py — inside DetectedForm
    class RecipientSource(models.TextChoices):
        PAGE = "page", "Read from the page markup"
        WP_API = "wp_api", "Read over the site's WordPress API"
        WORDPRESS = "wordpress", "Reported by WordPress"
```

- [ ] **Step 4: Widen the guard in `_apply_page_recipients`**

Replace the single-source early return:

```python
    if form.recipient_source == DetectedForm.RecipientSource.WORDPRESS:
        return
```

with:

```python
    # Both of these are the form's actual configuration, read from the site's
    # own database. The markup is only a proxy for it, and on the plugins that
    # matter it reads nothing at all — so an ingest must never overwrite either.
    if form.recipient_source in (
        DetectedForm.RecipientSource.WORDPRESS,
        DetectedForm.RecipientSource.WP_API,
    ):
        return
```

- [ ] **Step 5: Generate and apply the migration**

```bash
python manage.py makemigrations scripts
python manage.py migrate
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `pytest tests/scripts/test_recipient_precedence.py -v --create-db`
Expected: PASS (2 tests)

- [ ] **Step 7: Run the existing recipient tests for regressions**

Run: `pytest tests/scripts/ tests/websites/ -q`
Expected: PASS, no new failures.

- [ ] **Step 8: Commit**

```bash
git add apps/scripts/models.py apps/scripts/tasks.py apps/scripts/migrations/ tests/scripts/test_recipient_precedence.py
git commit -m "feat(forms): add wp_api recipient source and shield it from pageviews"
```

---

### Task 2: Resolve a WordPress credential for a website, with an audit trail

Gives the readers something to authenticate with, and answers the spec's open question about auditing an unattended read: `CredentialAccessLog.user` becomes nullable and gains a `SYSTEM_READ` action.

**Files:**
- Modify: `apps/credentials/models.py:66-82` (add credential type), `apps/credentials/models.py:177-192` (log action + nullable user)
- Create: `apps/credentials/wp_access.py`
- Create: `apps/credentials/migrations/00XX_wp_app_password_and_system_reads.py` (generated)
- Test: `tests/credentials/test_wp_access.py`

**Interfaces:**
- Consumes: `DetectedForm.RecipientSource.WP_API` (Task 1) — not directly, but the same feature.
- Produces:
  - `Credential.CredentialType.WORDPRESS_APP_PASSWORD` (value `"wordpress_app_password"`)
  - `WpCredential` dataclass with fields `username: str`, `password: str`, `credential_id: uuid.UUID`, `is_app_password: bool`
  - `resolve_wp_credential(website) -> WpCredential | None`
  - `log_system_read(credential_id: uuid.UUID) -> None`

  All consumed by Tasks 4 and 7.

- [ ] **Step 1: Write the failing test**

```python
# tests/credentials/test_wp_access.py
import pytest

from apps.credentials.models import Credential, CredentialAccessLog
from apps.credentials.wp_access import log_system_read, resolve_wp_credential

pytestmark = pytest.mark.django_db


def _credential(team, website, credential_type, username, password):
    cred = Credential(
        team=team, website=website, label="wp", credential_type=credential_type
    )
    cred.set_username(username)
    cred.set_password(password)
    cred.save()
    return cred


def test_returns_none_when_the_site_has_no_wordpress_credential(website):
    assert resolve_wp_credential(website) is None


def test_returns_the_wordpress_credential(website, team):
    _credential(team, website, Credential.CredentialType.WORDPRESS, "admin", "hunter2")

    got = resolve_wp_credential(website)

    assert got.username == "admin"
    assert got.password == "hunter2"
    assert got.is_app_password is False


def test_an_application_password_outranks_the_admin_login(website, team):
    _credential(team, website, Credential.CredentialType.WORDPRESS, "admin", "hunter2")
    _credential(
        team,
        website,
        Credential.CredentialType.WORDPRESS_APP_PASSWORD,
        "admin",
        "abcd efgh ijkl mnop qrst uvwx",
    )

    got = resolve_wp_credential(website)

    assert got.is_app_password is True
    assert got.password == "abcd efgh ijkl mnop qrst uvwx"


def test_a_credential_that_cannot_be_decrypted_is_skipped(website, team, monkeypatch):
    """A key rotation must degrade to "no credential", not crash the sweep."""
    cred = _credential(
        team, website, Credential.CredentialType.WORDPRESS, "admin", "hunter2"
    )
    monkeypatch.setattr(
        type(cred), "get_password", lambda self: (_ for _ in ()).throw(Exception("bad key"))
    )

    assert resolve_wp_credential(website) is None


def test_a_system_read_is_audited_without_a_user(website, team):
    cred = _credential(
        team, website, Credential.CredentialType.WORDPRESS, "admin", "hunter2"
    )

    log_system_read(cred.pk)

    entry = CredentialAccessLog.objects.get(credential=cred)
    assert entry.user is None
    assert entry.action == CredentialAccessLog.Action.SYSTEM_READ
```

The `team` fixture already exists in `tests/conftest.py`; confirm its name there before use.

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/credentials/test_wp_access.py -v`
Expected: FAIL — `ModuleNotFoundError: apps.credentials.wp_access`.

- [ ] **Step 3: Add the credential type**

```python
# apps/credentials/models.py — inside Credential.CredentialType, after WORDPRESS
        WORDPRESS = "wordpress", "WordPress Admin"
        WORDPRESS_APP_PASSWORD = (
            "wordpress_app_password",
            "WordPress Application Password",
        )
```

- [ ] **Step 4: Allow an unattended read to be audited**

```python
# apps/credentials/models.py — inside CredentialAccessLog
    class Action(models.TextChoices):
        VIEWED = "viewed", "Viewed"
        COPIED_PASSWORD = "copied_password", "Copied Password"
        EDITED = "edited", "Edited"
        SYSTEM_READ = "system_read", "Read by a scheduled task"
```

and make the actor optional, since a scheduled sweep has none:

```python
    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="credential_access_logs",
    )
```

- [ ] **Step 5: Write the resolver**

```python
# apps/credentials/wp_access.py
"""Which WordPress credential Digivault may use to read a site's own API.

Separate from the vault's request-facing code because the caller here is a
scheduled task with no user: it resolves a credential, records that it did, and
never returns plaintext to an HTTP response.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WpCredential:
    username: str
    password: str
    credential_id: uuid.UUID
    is_app_password: bool


def resolve_wp_credential(website) -> WpCredential | None:
    """The best WordPress credential linked to `website`, or None.

    An Application Password is preferred over the admin login: it is revocable
    on its own, capability-scoped, and a failed Basic auth against it does not
    burn a login-lockout budget the way a real password does.

    A credential whose ciphertext will not decrypt (key rotated, row copied
    between environments) is skipped rather than raised — the sweep's job is to
    fill in what it can, not to fail the site.
    """
    from apps.credentials.models import Credential

    order = (
        Credential.CredentialType.WORDPRESS_APP_PASSWORD,
        Credential.CredentialType.WORDPRESS,
    )
    by_type = {}
    for cred in website.credentials.filter(credential_type__in=order):
        by_type.setdefault(cred.credential_type, cred)

    for credential_type in order:
        cred = by_type.get(credential_type)
        if cred is None:
            continue
        try:
            username = cred.get_username()
            password = cred.get_password()
        except Exception:
            logger.debug("wp_access: credential %s will not decrypt", cred.pk)
            continue
        if not username or not password:
            continue
        return WpCredential(
            username=username,
            password=password,
            credential_id=cred.pk,
            is_app_password=(
                credential_type == Credential.CredentialType.WORDPRESS_APP_PASSWORD
            ),
        )

    return None


def log_system_read(credential_id: uuid.UUID) -> None:
    """Record that a scheduled task used a credential.

    Credential hygiene is a selling point of the product, so an automated read
    leaves the same trail a human reveal does — minus the actor, which is the
    honest representation of "nobody asked for this, the schedule did".
    """
    from apps.credentials.models import CredentialAccessLog

    CredentialAccessLog.objects.create(
        credential_id=credential_id,
        user=None,
        action=CredentialAccessLog.Action.SYSTEM_READ,
    )
```

- [ ] **Step 6: Generate and apply the migration**

```bash
python manage.py makemigrations credentials
python manage.py migrate
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `pytest tests/credentials/test_wp_access.py -v --create-db`
Expected: PASS (5 tests)

- [ ] **Step 8: Commit**

```bash
git add apps/credentials/ tests/credentials/test_wp_access.py
git commit -m "feat(credentials): resolve a site's WordPress credential for unattended reads"
```

---

### Task 3: Let `outbound.fetch` report a truncated body

`_elementor_data` routinely exceeds the 65536-byte default. A silently truncated body parses as broken JSON, and the reader must be able to tell that apart from "this page has no form".

**Files:**
- Modify: `apps/common/outbound.py:348-358` (`FetchResult`), `apps/common/outbound.py:400-425` (body reads)
- Test: `tests/common/test_outbound_truncation.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `FetchResult.truncated: bool`, consumed by Task 4.

- [ ] **Step 1: Write the failing test**

```python
# tests/common/test_outbound_truncation.py
import io

import pytest

from apps.common import outbound


class _Resp(io.BytesIO):
    status = 200

    def __init__(self, payload):
        super().__init__(payload)
        self.headers = {}

    def geturl(self):
        return "https://example.com/wp-json/wp/v2/pages"

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture(autouse=True)
def _no_budget(monkeypatch):
    monkeypatch.setattr(outbound, "cooldown_remaining", lambda host: 0)
    monkeypatch.setattr(outbound, "consume_budget", lambda host: True)
    monkeypatch.setattr(outbound, "_record_outcome", lambda host, result: None)


def test_a_body_that_fills_the_cap_is_reported_as_truncated(monkeypatch):
    payload = b"x" * 100
    monkeypatch.setattr(
        outbound, "_opener", lambda: type("O", (), {"open": lambda s, r, timeout: _Resp(payload)})()
    )

    result = outbound.fetch("https://example.com/a", read_bytes=100)

    assert result.truncated is True


def test_a_body_under_the_cap_is_not_truncated(monkeypatch):
    payload = b"x" * 50
    monkeypatch.setattr(
        outbound, "_opener", lambda: type("O", (), {"open": lambda s, r, timeout: _Resp(payload)})()
    )

    result = outbound.fetch("https://example.com/a", read_bytes=100)

    assert result.truncated is False
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/common/test_outbound_truncation.py -v`
Expected: FAIL — `AttributeError: 'FetchResult' object has no attribute 'truncated'`.

- [ ] **Step 3: Add the field**

```python
# apps/common/outbound.py
@dataclass
class FetchResult:
    status_code: int
    body: str
    headers: dict[str, str]
    elapsed_ms: int
    final_url: str
    #: The read hit `read_bytes` exactly, so the body may be a prefix of the
    #: real response. A caller parsing JSON must treat this as a failed fetch:
    #: a half-read Elementor payload is indistinguishable from a page with no
    #: form unless it is flagged here.
    truncated: bool = False
```

- [ ] **Step 4: Set it at both read sites**

Read one byte past the cap so a body exactly at the limit is still detected. In the success path:

```python
            raw = resp.read(read_bytes + 1)
            truncated = len(raw) > read_bytes
            body = raw[:read_bytes].decode("utf-8", errors="ignore")
            result = FetchResult(
                status_code=getattr(resp, "status", None) or resp.getcode(),
                body=body,
                headers={k.lower(): v for k, v in resp.headers.items()},
                elapsed_ms=int((time.monotonic() - start) * 1000),
                final_url=resp.geturl(),
                truncated=truncated,
            )
```

Note the test above asserts a body of exactly `read_bytes` is truncated, which this satisfies only if the stream really holds no more; with `read_bytes + 1` a 100-byte body under a 100-byte cap reads 100 and reports `False`. Change the first test's payload to `b"x" * 101` so it exercises a genuinely over-long body, and keep the second as written.

Apply the same `read_bytes + 1` treatment in the `urllib.error.HTTPError` branch, defaulting `truncated` to `False` when the error body cannot be read.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/common/test_outbound_truncation.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Run the outbound suite for regressions**

Run: `pytest tests/common/ tests/monitors/ -q`
Expected: PASS, no new failures.

- [ ] **Step 7: Commit**

```bash
git add apps/common/outbound.py tests/common/test_outbound_truncation.py
git commit -m "feat(outbound): flag a response body that hit the read cap"
```

---

### Task 4: Parametrise `apply_recipients` by source, and add the reader scaffold

Makes the existing matching and writing logic reusable by the new path, and stands up the module the readers plug into. No reader yet — this task ends with a working sync that finds nothing.

**Files:**
- Modify: `apps/websites/wp_forms.py:152-208` (`apply_recipients`)
- Create: `apps/websites/wp_api_forms.py`
- Test: `tests/websites/test_wp_api_forms.py`

**Interfaces:**
- Consumes: `DetectedForm.RecipientSource.WP_API` (Task 1); `resolve_wp_credential`, `WpCredential`, `log_system_read` (Task 2); `FetchResult.truncated` (Task 3).
- Produces:
  - `wp_forms.apply_recipients(website, entries, source=DetectedForm.RecipientSource.WORDPRESS) -> int`
  - `wp_api_forms.basic_auth_header(credential: WpCredential) -> dict[str, str]`
  - `wp_api_forms.fetch_json(website, path: str, credential: WpCredential, *, read_bytes: int = 2_000_000) -> tuple[object | None, int]` returning `(parsed_or_None, status_code)`; status `0` means the request never happened
  - `wp_api_forms.READERS: tuple` of callables `(website, credential) -> list[dict]`
  - `wp_api_forms.sync_website(website) -> int`

  Consumed by Tasks 5, 6, 7, 8, 9.

- [ ] **Step 1: Write the failing test**

```python
# tests/websites/test_wp_api_forms.py
import pytest

from apps.credentials.models import Credential
from apps.scripts.models import DetectedForm
from apps.websites import wp_api_forms
from apps.websites.wp_forms import apply_recipients

pytestmark = pytest.mark.django_db


def _wp_credential(team, website):
    cred = Credential(
        team=team,
        website=website,
        label="wp",
        credential_type=Credential.CredentialType.WORDPRESS_APP_PASSWORD,
    )
    cred.set_username("admin")
    cred.set_password("app pass")
    cred.save()
    return cred


def test_basic_auth_header_is_standard_basic(team, website):
    from apps.credentials.wp_access import resolve_wp_credential

    _wp_credential(team, website)
    header = wp_api_forms.basic_auth_header(resolve_wp_credential(website))

    # base64("admin:app pass")
    assert header == {"Authorization": "Basic YWRtaW46YXBwIHBhc3M="}


def test_apply_recipients_writes_the_source_it_is_given(website):
    form = DetectedForm.objects.create(
        website=website,
        page_url="https://example.com/contact",
        fingerprint="f1",
        form_name="Contact",
    )

    written = apply_recipients(
        website,
        [{"name": "Contact", "to": "leads@example.com"}],
        source=DetectedForm.RecipientSource.WP_API,
    )

    form.refresh_from_db()
    assert written == 1
    assert form.recipient_source == DetectedForm.RecipientSource.WP_API
    assert form.recipients["to"] == ["leads@example.com"]


def test_a_wp_api_answer_never_overwrites_a_wp_connect_answer(website):
    form = DetectedForm.objects.create(
        website=website,
        page_url="https://example.com/contact",
        fingerprint="f1",
        form_name="Contact",
        recipients={"to": ["truth@example.com"], "cc": [], "bcc": []},
        recipient_source=DetectedForm.RecipientSource.WORDPRESS,
    )

    apply_recipients(
        website,
        [{"name": "Contact", "to": "stale@example.com"}],
        source=DetectedForm.RecipientSource.WP_API,
    )

    form.refresh_from_db()
    assert form.recipients["to"] == ["truth@example.com"]
    assert form.recipient_source == DetectedForm.RecipientSource.WORDPRESS


def test_sync_website_is_a_no_op_without_a_credential(website):
    assert wp_api_forms.sync_website(website) == 0


def test_fetch_json_treats_a_truncated_body_as_no_answer(team, website, monkeypatch):
    from apps.common.outbound import FetchResult
    from apps.credentials.wp_access import resolve_wp_credential

    _wp_credential(team, website)
    monkeypatch.setattr(
        wp_api_forms.outbound,
        "fetch",
        lambda *a, **kw: FetchResult(
            status_code=200,
            body='[{"id":1',
            headers={},
            elapsed_ms=1,
            final_url="https://example.com/",
            truncated=True,
        ),
    )

    parsed, status = wp_api_forms.fetch_json(
        website, "wp/v2/pages", resolve_wp_credential(website)
    )

    assert parsed is None
    assert status == 200
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/websites/test_wp_api_forms.py -v`
Expected: FAIL — `ModuleNotFoundError: apps.websites.wp_api_forms`.

- [ ] **Step 3: Parametrise `apply_recipients`**

In `apps/websites/wp_forms.py`, change the signature and the three places the source is referenced:

```python
def apply_recipients(website, entries: list[dict], source=None) -> int:
    """Fill in `recipients` from what the site reported. Returns rows written.

    `source` says which path answered. WP Connect reads the database directly
    through a signature-gated route; the REST readers see only what a plugin
    chose to expose, so a WP Connect answer outranks theirs and is never
    overwritten by one.
    """
    from apps.scripts.models import DetectedForm
    from apps.scripts.recipient_changes import record_recipient_change
    from apps.scripts.recipients import build_recipients, recipients_equal

    if source is None:
        source = DetectedForm.RecipientSource.WORDPRESS

    forms = list(website.detected_forms.all())
    if not forms:
        return 0
```

Inside the per-form loop, replace the skip check and the two writes:

```python
        for form in matched:
            if (
                source == DetectedForm.RecipientSource.WP_API
                and form.recipient_source == DetectedForm.RecipientSource.WORDPRESS
            ):
                continue
            if (
                recipients_equal(form.recipients, recipients)
                and form.recipient_source == source
            ):
                continue
            old_recipients = form.recipients
            old_source = form.recipient_source
            form.recipients = recipients
            form.recipient_source = source
            form.save(update_fields=["recipients", "recipient_source", "updated_at"])
            record_recipient_change(
                form,
                old_recipients=old_recipients,
                old_source=old_source,
                new_source=source,
            )
            written += 1
```

Leave `sync_website` in that module calling `apply_recipients(website, entries)` with no source, so the WP Connect path is unchanged.

- [ ] **Step 4: Write the scaffold module**

```python
# apps/websites/wp_api_forms.py
"""Read form recipients from a site's own WordPress REST API.

The WP Connect path (`wp_forms.py`) is better but needs a PHP snippet pasted
into the client's site. This one needs only a WordPress credential the agency
usually already has in the vault, at the cost of narrower coverage: WordPress
core exposes protected post meta over REST only when a plugin registers it with
an `auth_callback`, and of the four form plugins that matter, only Elementor
does. Gravity Forms is reachable through its own REST API. Contact Form 7 and
WPForms expose nothing and still require WP Connect.

Every failure here is a normal state — most sites have no credential, plenty of
hosts strip the Authorization header, and REST is often disabled outright. None
of it raises, logs at error level, or touches the site's health score.
"""
from __future__ import annotations

import base64
import json
import logging

from apps.common import outbound
from apps.common.outbound import OutboundError
from apps.common.ssrf import BlockedURLError
from apps.credentials.wp_access import WpCredential, log_system_read, resolve_wp_credential

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 20
#: Elementor returns a whole page's builder tree per row, so the 64 KB default
#: in `outbound.fetch` truncates constantly. A truncated body is treated as a
#: failed read, never as "this page has no form".
_READ_BYTES = 2_000_000


def site_base_url(website) -> str:
    """The site's origin, with a scheme, ready to append a REST path to."""
    domain = website.domain or ""
    if not domain.startswith(("http://", "https://")):
        domain = f"https://{domain}"
    return domain.rstrip("/")


def basic_auth_header(credential: WpCredential) -> dict[str, str]:
    """WordPress Application Passwords authenticate as HTTP Basic."""
    raw = f"{credential.username}:{credential.password}".encode()
    return {"Authorization": "Basic " + base64.b64encode(raw).decode()}


def fetch_json(website, path: str, credential: WpCredential, *, read_bytes: int = _READ_BYTES):
    """`(parsed, status_code)` for one authenticated REST GET.

    `parsed` is None whenever we did not get a usable answer. A status of 0
    means the request never left — SSRF guard, per-host budget, or a transport
    error. The caller needs the status to tell a rejected credential (401/403)
    apart from a plugin that simply is not installed (404).
    """
    url = f"{site_base_url(website)}/wp-json/{path.lstrip('/')}"

    try:
        resp = outbound.fetch(
            url,
            timeout=_TIMEOUT_SECONDS,
            wait_up_to=_TIMEOUT_SECONDS,
            extra_headers=basic_auth_header(credential),
            read_bytes=read_bytes,
        )
    except BlockedURLError as exc:
        logger.warning("wp_api_forms: refusing to fetch %s: %s", website.pk, exc)
        return None, 0
    except OutboundError as exc:
        logger.debug("wp_api_forms: %s deferred by outbound budget: %s", website.domain, exc)
        return None, 0
    except Exception as exc:
        logger.debug("wp_api_forms: %s unreachable: %s", website.domain, exc)
        return None, 0

    if resp.status_code != 200:
        return None, resp.status_code

    if resp.truncated:
        logger.debug("wp_api_forms: %s truncated %s at the read cap", website.domain, path)
        return None, resp.status_code

    try:
        return json.loads(resp.body), resp.status_code
    except ValueError:
        logger.debug("wp_api_forms: %s returned non-JSON for %s", website.domain, path)
        return None, resp.status_code


#: Populated by Tasks 5 and 6.
READERS: tuple = ()


def sync_website(website) -> int:
    """Read every reader this site answers to, and record what they found."""
    from apps.scripts.models import DetectedForm
    from apps.websites.wp_forms import apply_recipients

    credential = resolve_wp_credential(website)
    if credential is None:
        return 0

    entries: list[dict] = []
    for reader in READERS:
        try:
            entries.extend(reader(website, credential))
        except Exception:
            logger.debug(
                "wp_api_forms: reader %s failed for %s",
                getattr(reader, "__name__", reader),
                website.domain,
            )

    if not entries:
        return 0

    log_system_read(credential.credential_id)
    return apply_recipients(
        website, entries, source=DetectedForm.RecipientSource.WP_API
    )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/websites/test_wp_api_forms.py -v`
Expected: PASS (5 tests)

- [ ] **Step 6: Run the WP Connect suite for regressions**

Run: `pytest tests/websites/ -q`
Expected: PASS — the existing `wp_forms` tests must still pass with the new default argument.

- [ ] **Step 7: Commit**

```bash
git add apps/websites/wp_forms.py apps/websites/wp_api_forms.py tests/websites/test_wp_api_forms.py
git commit -m "feat(forms): reader scaffold for reading recipients over the WP REST API"
```

---

### Task 5: Capture a real Elementor payload and write the Elementor reader

The one detail in the design that could not be verified from source: Elementor Pro is not publicly distributed, so its email-action setting keys are unconfirmed. Capture them from a real site first, then write the reader against a fixture.

**Files:**
- Create: `tests/websites/fixtures/elementor_data.json`
- Modify: `apps/websites/wp_api_forms.py` (add reader, register in `READERS`)
- Test: `tests/websites/test_wp_api_elementor.py`

**Interfaces:**
- Consumes: `fetch_json`, `READERS` (Task 4).
- Produces: `read_elementor(website, credential) -> list[dict]` emitting entries shaped `{"plugin": "elementor", "name": <form_name>, "to": str, "cc": str, "bcc": str}`.

- [ ] **Step 1: Capture the payload from a real Elementor site**

Pick a monitored client site running Elementor Pro >= 3.27.0 with a form, create an Application Password at `/wp-admin/profile.php`, and run:

```bash
curl -sS -u 'USERNAME:APP PASSWORD' \
  'https://CLIENT-SITE/wp-json/wp/v2/pages?context=edit&_fields=id,link,meta&per_page=5' \
  -o tests/websites/fixtures/elementor_data.json
```

Then read the keys off it:

```bash
python -c "import json;d=json.load(open('tests/websites/fixtures/elementor_data.json'));print(json.dumps(d,indent=1)[:4000])" | grep -i "email\|form_name"
```

Record the actual To/Cc/Bcc key names. Trim the fixture to one page containing one form and redact the real address to `leads@example.com`.

If no such site is available, keep both candidate spellings in the key tuples below — they are harmless when absent — and open a follow-up to confirm against production.

- [ ] **Step 2: Write the failing test**

```python
# tests/websites/test_wp_api_elementor.py
import json
import pathlib

import pytest

from apps.websites import wp_api_forms

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "elementor_data.json"

pytestmark = pytest.mark.django_db


def test_reads_the_form_name_and_recipient_from_elementor_data(website, monkeypatch):
    pages = json.loads(FIXTURE.read_text())
    calls = []

    def _fake(site, path, credential, **kwargs):
        calls.append(path)
        return (pages, 200) if path.startswith("wp/v2/pages") else ([], 200)

    monkeypatch.setattr(wp_api_forms, "fetch_json", _fake)

    entries = wp_api_forms.read_elementor(website, credential=object())

    assert entries
    assert entries[0]["plugin"] == "elementor"
    assert entries[0]["to"] == "leads@example.com"
    assert entries[0]["name"]


def test_a_page_with_no_form_widget_yields_nothing(website, monkeypatch):
    page = [{
        "id": 4,
        "link": "https://example.com/about",
        "meta": {"_elementor_data": json.dumps([
            {"elType": "section", "elements": [
                {"elType": "widget", "widgetType": "heading", "settings": {"title": "Hi"}}
            ]}
        ])},
    }]
    monkeypatch.setattr(wp_api_forms, "fetch_json", lambda *a, **kw: (page, 200))

    assert wp_api_forms.read_elementor(website, credential=object()) == []


def test_a_failed_fetch_yields_nothing(website, monkeypatch):
    monkeypatch.setattr(wp_api_forms, "fetch_json", lambda *a, **kw: (None, 401))

    assert wp_api_forms.read_elementor(website, credential=object()) == []
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `pytest tests/websites/test_wp_api_elementor.py -v`
Expected: FAIL — `AttributeError: module has no attribute 'read_elementor'`.

- [ ] **Step 4: Write the reader**

```python
# apps/websites/wp_api_forms.py — append

#: Post types that can carry an Elementor form. `elementor_library` holds
#: popups and saved templates, which is where a lot of lead forms actually live.
_ELEMENTOR_POST_TYPES = ("pages", "posts", "elementor_library")
#: Each row carries a whole builder tree, so a large page size produces
#: multi-megabyte responses. Small pages, bounded count, and say what was
#: skipped rather than truncating in silence.
_ELEMENTOR_PER_PAGE = 10
_ELEMENTOR_MAX_PAGES = 10

#: Elementor Pro is not publicly distributed, so these were confirmed against a
#: real site rather than read from source. Both spellings are listed because a
#: key that is absent costs nothing.
_TO_KEYS = ("email_to",)
_CC_KEYS = ("email_cc", "email_to_cc")
_BCC_KEYS = ("email_bcc", "email_to_bcc")


def _first_value(settings: dict, keys: tuple) -> str:
    for key in keys:
        value = settings.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _walk_form_widgets(nodes, found: list) -> None:
    """Collect the settings of every `form` widget in an Elementor tree."""
    if not isinstance(nodes, list):
        return
    for node in nodes:
        if not isinstance(node, dict):
            continue
        if node.get("widgetType") == "form":
            settings = node.get("settings")
            if isinstance(settings, dict):
                found.append(settings)
        _walk_form_widgets(node.get("elements"), found)


def read_elementor(website, credential) -> list[dict]:
    """Elementor form recipients, read from `_elementor_data` post meta.

    Reachable because Elementor registers that meta with `show_in_rest` and an
    `auth_callback` (`modules/wp-rest/classes/elementor-post-meta.php`, 3.27.0+).
    Without that registration WordPress hides underscore-prefixed meta from
    every API, which is exactly why Contact Form 7 cannot be read this way.
    """
    entries: list[dict] = []

    for post_type in _ELEMENTOR_POST_TYPES:
        for page_number in range(1, _ELEMENTOR_MAX_PAGES + 1):
            path = (
                f"wp/v2/{post_type}?context=edit&_fields=id,link,meta"
                f"&per_page={_ELEMENTOR_PER_PAGE}&page={page_number}"
            )
            rows, status = fetch_json(website, path, credential)
            if not isinstance(rows, list) or not rows:
                if status == 400 and page_number > 1:
                    # WordPress answers 400 for a page past the end.
                    pass
                break

            for row in rows:
                meta = row.get("meta") if isinstance(row, dict) else None
                raw = (meta or {}).get("_elementor_data")
                if not raw:
                    continue
                try:
                    tree = json.loads(raw) if isinstance(raw, str) else raw
                except ValueError:
                    continue

                widgets: list = []
                _walk_form_widgets(tree, widgets)
                for settings in widgets:
                    to = _first_value(settings, _TO_KEYS)
                    if not to:
                        continue
                    entries.append({
                        "plugin": "elementor",
                        "name": str(settings.get("form_name") or "").strip(),
                        "to": to,
                        "cc": _first_value(settings, _CC_KEYS),
                        "bcc": _first_value(settings, _BCC_KEYS),
                    })

            if len(rows) < _ELEMENTOR_PER_PAGE:
                break
        else:
            logger.info(
                "wp_api_forms: %s stopped at %d pages of %s; later pages not read",
                website.domain,
                _ELEMENTOR_MAX_PAGES,
                post_type,
            )

    return entries
```

Register it:

```python
READERS: tuple = (read_elementor,)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/websites/test_wp_api_elementor.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
git add apps/websites/wp_api_forms.py tests/websites/test_wp_api_elementor.py tests/websites/fixtures/elementor_data.json
git commit -m "feat(forms): read Elementor form recipients over the WP REST API"
```

---

### Task 6: Gravity Forms reader

**Files:**
- Modify: `apps/websites/wp_api_forms.py` (add reader, extend `READERS`)
- Test: `tests/websites/test_wp_api_gravity.py`

**Interfaces:**
- Consumes: `fetch_json`, `READERS` (Task 4).
- Produces: `read_gravity(website, credential) -> list[dict]` emitting entries shaped `{"plugin": "gravityforms", "id_prefix": "gform_<id>", "to": str, "cc": str, "bcc": str}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/websites/test_wp_api_gravity.py
import pytest

from apps.websites import wp_api_forms

pytestmark = pytest.mark.django_db

_FORM_LIST = {"1": {"id": "1", "title": "Contact"}, "12": {"id": "12", "title": "Quote"}}


def _reply(form_id, notifications):
    return {"id": form_id, "notifications": notifications}


def test_reads_a_literal_notification_address(website, monkeypatch):
    def _fake(site, path, credential, **kwargs):
        if path == "gf/v2/forms":
            return {"1": _FORM_LIST["1"]}, 200
        return _reply("1", {"n1": {"to": "leads@example.com", "toType": "email"}}), 200

    monkeypatch.setattr(wp_api_forms, "fetch_json", _fake)

    entries = wp_api_forms.read_gravity(website, credential=object())

    assert entries == [{
        "plugin": "gravityforms",
        "id_prefix": "gform_1",
        "to": "leads@example.com",
        "cc": "",
        "bcc": "",
    }]


def test_a_field_routed_notification_is_skipped(website, monkeypatch):
    """toType "field" resolves per submission — there is no fixed recipient, and
    storing the raw value would display a field id as an email address."""
    def _fake(site, path, credential, **kwargs):
        if path == "gf/v2/forms":
            return {"1": _FORM_LIST["1"]}, 200
        return _reply("1", {"n1": {"to": "3", "toType": "field"}}), 200

    monkeypatch.setattr(wp_api_forms, "fetch_json", _fake)

    assert wp_api_forms.read_gravity(website, credential=object()) == []


def test_gravity_not_installed_yields_nothing(website, monkeypatch):
    monkeypatch.setattr(wp_api_forms, "fetch_json", lambda *a, **kw: (None, 404))

    assert wp_api_forms.read_gravity(website, credential=object()) == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/websites/test_wp_api_gravity.py -v`
Expected: FAIL — `AttributeError: module has no attribute 'read_gravity'`.

- [ ] **Step 3: Write the reader**

```python
# apps/websites/wp_api_forms.py — append

#: A site with more forms than this is pathological; the cap bounds the number
#: of per-form requests one sweep can make against a client origin.
_GRAVITY_MAX_FORMS = 100


def read_gravity(website, credential) -> list[dict]:
    """Gravity Forms notification recipients, over its own REST API v2.

    Gravity keeps forms in its own tables rather than `wp_posts`, so the post
    meta route cannot see them; its REST API has accepted WordPress Application
    Passwords over Basic auth since 2.4.21.4 and runs with the authenticated
    user's Gravity capabilities.
    """
    listing, _status = fetch_json(website, "gf/v2/forms", credential)
    if not isinstance(listing, dict):
        return []

    entries: list[dict] = []
    for form_id in list(listing.keys())[:_GRAVITY_MAX_FORMS]:
        detail, _ = fetch_json(website, f"gf/v2/forms/{form_id}", credential)
        if not isinstance(detail, dict):
            continue

        notifications = detail.get("notifications")
        if isinstance(notifications, dict):
            notifications = list(notifications.values())
        if not isinstance(notifications, list):
            continue

        for notification in notifications:
            if not isinstance(notification, dict):
                continue
            # "field" and "routing" resolve against the submission, so there is
            # no fixed destination to record.
            if str(notification.get("toType") or "email").lower() != "email":
                continue
            to = str(notification.get("to") or "").strip()
            if not to:
                continue
            entries.append({
                "plugin": "gravityforms",
                "id_prefix": f"gform_{form_id}",
                "to": to,
                "cc": str(notification.get("cc") or "").strip(),
                "bcc": str(notification.get("bcc") or "").strip(),
            })

    return entries
```

Extend the registry:

```python
READERS: tuple = (read_elementor, read_gravity)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/websites/test_wp_api_gravity.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Add the prefix-collision regression test**

`_matches_prefix` already handles this, but the reader is what produces the prefix, so pin the behaviour end to end:

```python
# tests/websites/test_wp_api_gravity.py — append
from apps.scripts.models import DetectedForm
from apps.websites.wp_forms import apply_recipients


def test_gform_1_does_not_claim_gform_12(website):
    twelve = DetectedForm.objects.create(
        website=website, page_url="https://example.com/q", fingerprint="f12",
        form_id="gform_12",
    )
    one = DetectedForm.objects.create(
        website=website, page_url="https://example.com/c", fingerprint="f1",
        form_id="gform_1",
    )

    apply_recipients(
        website,
        [{"plugin": "gravityforms", "id_prefix": "gform_1", "to": "one@example.com"}],
        source=DetectedForm.RecipientSource.WP_API,
    )

    one.refresh_from_db()
    twelve.refresh_from_db()
    assert one.recipients["to"] == ["one@example.com"]
    assert twelve.recipients.get("to", []) == []
```

Run: `pytest tests/websites/test_wp_api_gravity.py -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Commit**

```bash
git add apps/websites/wp_api_forms.py tests/websites/test_wp_api_gravity.py
git commit -m "feat(forms): read Gravity Forms notification recipients over REST"
```

---

### Task 7: Stop retrying a rejected credential

Repeated 401s from Digivault's single egress IP are how that IP gets banned, and a ban costs uptime monitoring — a far more valuable signal than a recipient address.

**Files:**
- Modify: `apps/websites/models.py` (add field), `apps/websites/wp_api_forms.py` (`sync_website`)
- Create: `apps/websites/migrations/00XX_website_wp_api_auth_failed_at.py` (generated)
- Modify: `apps/credentials/models.py` — none; the reset hangs off the credential save in Step 4
- Test: `tests/websites/test_wp_api_auth_failure.py`

**Interfaces:**
- Consumes: `sync_website`, `fetch_json` (Task 4).
- Produces: `Website.wp_api_auth_failed_at: datetime | None`, consumed by Tasks 8 and 9.

- [ ] **Step 1: Write the failing test**

```python
# tests/websites/test_wp_api_auth_failure.py
import pytest
from django.utils import timezone

from apps.credentials.models import Credential
from apps.websites import wp_api_forms

pytestmark = pytest.mark.django_db


def _wp_credential(team, website):
    cred = Credential(
        team=team, website=website, label="wp",
        credential_type=Credential.CredentialType.WORDPRESS,
    )
    cred.set_username("admin")
    cred.set_password("wrong")
    cred.save()
    return cred


def test_a_401_is_recorded_on_the_website(team, website, monkeypatch):
    _wp_credential(team, website)
    monkeypatch.setattr(wp_api_forms, "fetch_json", lambda *a, **kw: (None, 401))

    wp_api_forms.sync_website(website)

    website.refresh_from_db()
    assert website.wp_api_auth_failed_at is not None


def test_a_website_with_a_recorded_failure_is_not_retried(team, website, monkeypatch):
    _wp_credential(team, website)
    website.wp_api_auth_failed_at = timezone.now()
    website.save(update_fields=["wp_api_auth_failed_at"])

    calls = []
    monkeypatch.setattr(
        wp_api_forms, "fetch_json", lambda *a, **kw: (calls.append(1), (None, 401))[1]
    )

    assert wp_api_forms.sync_website(website) == 0
    assert calls == []


def test_a_404_is_not_an_auth_failure(team, website, monkeypatch):
    """Gravity simply not being installed must not disarm the whole site."""
    _wp_credential(team, website)
    monkeypatch.setattr(wp_api_forms, "fetch_json", lambda *a, **kw: (None, 404))

    wp_api_forms.sync_website(website)

    website.refresh_from_db()
    assert website.wp_api_auth_failed_at is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/websites/test_wp_api_auth_failure.py -v`
Expected: FAIL — `AttributeError: 'Website' object has no attribute 'wp_api_auth_failed_at'`.

- [ ] **Step 3: Add the field**

```python
# apps/websites/models.py — beside wp_sso_secret
    # When the site's WordPress API last rejected our stored credential. Set,
    # the daily sweep skips this site: repeated 401s from our single egress IP
    # are how that IP gets banned, and a ban costs uptime monitoring, which is
    # worth far more than a recipient address. Cleared when the credential is
    # edited.
    wp_api_auth_failed_at = models.DateTimeField(null=True, blank=True)
```

- [ ] **Step 4: Track auth failures in `sync_website`**

Readers need to report status, so give the module a small shared recorder rather than threading return values through every reader:

```python
# apps/websites/wp_api_forms.py — replace sync_website

#: Statuses that mean "this credential will not work", as opposed to "this
#: plugin is not installed" (404) or "this site is busy" (5xx).
_AUTH_FAILURE_STATUSES = (401, 403)


def sync_website(website) -> int:
    """Read every reader this site answers to, and record what they found."""
    from django.utils import timezone

    from apps.scripts.models import DetectedForm
    from apps.websites.wp_forms import apply_recipients

    if website.wp_api_auth_failed_at is not None:
        return 0

    credential = resolve_wp_credential(website)
    if credential is None:
        return 0

    seen_statuses: list[int] = []

    def _tracking_fetch(site, path, cred, **kwargs):
        parsed, status = fetch_json(site, path, cred, **kwargs)
        seen_statuses.append(status)
        return parsed, status

    entries: list[dict] = []
    for reader in READERS:
        try:
            entries.extend(reader(website, credential, fetch=_tracking_fetch))
        except Exception:
            logger.debug(
                "wp_api_forms: reader %s failed for %s",
                getattr(reader, "__name__", reader),
                website.domain,
            )

    if any(s in _AUTH_FAILURE_STATUSES for s in seen_statuses):
        website.wp_api_auth_failed_at = timezone.now()
        website.save(update_fields=["wp_api_auth_failed_at", "updated_at"])
        logger.debug("wp_api_forms: %s rejected our credential", website.domain)
        return 0

    if not entries:
        return 0

    log_system_read(credential.credential_id)
    return apply_recipients(
        website, entries, source=DetectedForm.RecipientSource.WP_API
    )
```

Give both readers the injectable fetch so the tracking wrapper reaches them. Change each signature and every internal call site:

```python
def read_elementor(website, credential, fetch=None) -> list[dict]:
    fetch = fetch or fetch_json
    ...
            rows, status = fetch(website, path, credential)
```

```python
def read_gravity(website, credential, fetch=None) -> list[dict]:
    fetch = fetch or fetch_json
    listing, _status = fetch(website, "gf/v2/forms", credential)
    ...
        detail, _ = fetch(website, f"gf/v2/forms/{form_id}", credential)
```

The Task 5 and 6 tests monkeypatch `wp_api_forms.fetch_json`, which the `fetch or fetch_json` default still resolves at call time — they keep passing unchanged.

- [ ] **Step 5: Clear the flag when the credential is fixed**

In `apps/credentials/models.py`, at the end of `Credential.set_password`, re-arm the site:

```python
        # A corrected credential deserves another try on the next sweep.
        if self.website_id and self.credential_type in (
            self.CredentialType.WORDPRESS,
            self.CredentialType.WORDPRESS_APP_PASSWORD,
        ):
            from apps.websites.models import Website

            Website.objects.filter(pk=self.website_id).update(
                wp_api_auth_failed_at=None
            )
```

- [ ] **Step 6: Generate and apply the migration**

```bash
python manage.py makemigrations websites
python manage.py migrate
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `pytest tests/websites/ -v --create-db`
Expected: PASS — including Tasks 4, 5 and 6's tests.

- [ ] **Step 8: Commit**

```bash
git add apps/websites/models.py apps/websites/wp_api_forms.py apps/websites/migrations/ apps/credentials/models.py tests/websites/test_wp_api_auth_failure.py
git commit -m "feat(forms): stop retrying a WordPress credential the site rejected"
```

---

### Task 8: Schedule the sweep

**Files:**
- Modify: `apps/websites/tasks.py:56-80` (add a sibling task)
- Modify: `config/settings/base.py:232-238` (add a beat entry)
- Test: `tests/websites/test_wp_api_task.py`

**Interfaces:**
- Consumes: `wp_api_forms.sync_website` (Task 4/7), `Website.wp_api_auth_failed_at` (Task 7).
- Produces: Celery task `websites.sync_wp_api_form_recipients`, consumed by the beat schedule.

- [ ] **Step 1: Write the failing test**

```python
# tests/websites/test_wp_api_task.py
import pytest

from apps.websites.tasks import sync_wp_api_form_recipients

pytestmark = pytest.mark.django_db


def test_skips_sites_with_no_detected_forms(website, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "apps.websites.wp_api_forms.sync_website",
        lambda site: calls.append(site) or 0,
    )

    assert sync_wp_api_form_recipients() == 0
    assert calls == []


def test_visits_a_site_that_has_forms(website, monkeypatch):
    from apps.scripts.models import DetectedForm

    DetectedForm.objects.create(
        website=website, page_url="https://example.com/c", fingerprint="f1"
    )
    monkeypatch.setattr("apps.websites.wp_api_forms.sync_website", lambda site: 3)

    assert sync_wp_api_form_recipients() == 3


def test_one_failing_site_does_not_stop_the_sweep(website, team, monkeypatch):
    from apps.scripts.models import DetectedForm

    DetectedForm.objects.create(
        website=website, page_url="https://example.com/c", fingerprint="f1"
    )

    def _boom(site):
        raise RuntimeError("nope")

    monkeypatch.setattr("apps.websites.wp_api_forms.sync_website", _boom)

    assert sync_wp_api_form_recipients() == 0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/websites/test_wp_api_task.py -v`
Expected: FAIL — `ImportError: cannot import name 'sync_wp_api_form_recipients'`.

- [ ] **Step 3: Write the task**

```python
# apps/websites/tasks.py — after sync_wp_form_recipients

@shared_task(name="websites.sync_wp_api_form_recipients")
def sync_wp_api_form_recipients(website_pk: str | None = None) -> int:
    """Read form recipients from sites' own WordPress APIs. Returns rows written.

    The WP-Connect-free path. Skips sites with no detected forms (nothing to
    join an answer onto) and sites whose credential was already rejected — see
    `Website.wp_api_auth_failed_at`.
    """
    from apps.websites.models import Website
    from apps.websites.wp_api_forms import sync_website

    sites = Website.objects.exclude(status=Website.Status.INACTIVE).filter(
        wp_api_auth_failed_at__isnull=True
    )
    if website_pk:
        sites = sites.filter(pk=website_pk)
    sites = sites.filter(detected_forms__isnull=False).distinct()

    written = 0
    for website in sites.iterator():
        try:
            written += sync_website(website)
        except Exception:
            logger.exception("sync_wp_api_form_recipients failed for %s", website.pk)
    logger.info("sync_wp_api_form_recipients: updated %d form(s)", written)
    return written
```

- [ ] **Step 4: Add the beat entry**

```python
# config/settings/base.py — beside sync-wp-form-recipients-daily
    # The same question for sites with no WP Connect snippet, answered from the
    # site's own REST API using a vaulted credential. Offset an hour from the
    # WP Connect sweep so the two do not contend for the same per-host budget.
    "sync-wp-api-form-recipients-daily": {
        "task": "websites.sync_wp_api_form_recipients",
        "schedule": crontab(hour=7, minute=45),
    },
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/websites/test_wp_api_task.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
git add apps/websites/tasks.py config/settings/base.py tests/websites/test_wp_api_task.py
git commit -m "feat(forms): daily sweep reading recipients over the WP REST API"
```

---

### Task 9: Make the manual sync try both paths

Turns the 409 the user reported into something either actionable or unnecessary.

**Files:**
- Modify: `apps/websites/views.py:406-430` (`sync_form_recipients`)
- Test: `tests/websites/test_sync_form_recipients_action.py`

**Interfaces:**
- Consumes: `wp_api_forms.sync_website` (Task 4/7), `resolve_wp_credential` (Task 2).
- Produces: no new symbols; changes the endpoint's response contract to include `"source"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/websites/test_sync_form_recipients_action.py
import pytest
from rest_framework import status

pytestmark = pytest.mark.django_db


def _url(website):
    return f"/api/websites/{website.pk}/sync-form-recipients/"


def test_409_when_neither_path_is_available(auth_client, website):
    resp = auth_client.post(_url(website))

    assert resp.status_code == status.HTTP_409_CONFLICT
    assert "WordPress credentials" in resp.data["detail"]


def test_falls_back_to_the_api_path_without_wp_connect(
    auth_client, website, team, monkeypatch
):
    from apps.credentials.models import Credential

    cred = Credential(
        team=team, website=website, label="wp",
        credential_type=Credential.CredentialType.WORDPRESS,
    )
    cred.set_username("admin")
    cred.set_password("pw")
    cred.save()

    monkeypatch.setattr("apps.websites.wp_api_forms.sync_website", lambda site: 2)

    resp = auth_client.post(_url(website))

    assert resp.status_code == status.HTTP_200_OK
    assert resp.data["updated"] == 2
    assert resp.data["source"] == "wp_api"


def test_wp_connect_still_wins_when_configured(auth_client, website, monkeypatch):
    website.wp_sso_secret = "s3cret"
    website.save(update_fields=["wp_sso_secret"])
    monkeypatch.setattr("apps.websites.wp_forms.sync_website", lambda site: 5)

    resp = auth_client.post(_url(website))

    assert resp.data["updated"] == 5
    assert resp.data["source"] == "wordpress"
```

Confirm the actual URL prefix against `config/urls.py` and the websites router before running — adjust `_url` if the router mounts it elsewhere.

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/websites/test_sync_form_recipients_action.py -v`
Expected: FAIL — the 409 message does not mention WordPress credentials, and `source` is absent.

- [ ] **Step 3: Rewrite the action**

```python
    @action(detail=True, methods=["post"], url_path="sync-form-recipients")
    def sync_form_recipients(self, request, pk=None):
        """Ask this site where its forms deliver, now.

        Two paths, strongest first. WP Connect reads the site's database through
        a signature-gated route and covers every form plugin. The REST readers
        need only a vaulted WordPress credential but reach Elementor and Gravity
        Forms only — Contact Form 7 and WPForms expose nothing to any API.
        """
        from apps.credentials.wp_access import resolve_wp_credential
        from apps.websites import wp_api_forms
        from apps.websites.wp_forms import sync_website

        website = self.get_object()

        if website.wp_sso_secret:
            source, runner = "wordpress", sync_website
        elif resolve_wp_credential(website) is not None:
            source, runner = "wp_api", wp_api_forms.sync_website
        else:
            return Response(
                {
                    "detail": (
                        "Add WordPress credentials for this website, or set up "
                        "WP Connect, so Digivault can read where its forms deliver."
                    )
                },
                status=status.HTTP_409_CONFLICT,
            )

        try:
            updated = runner(website)
        except Exception:
            logger.exception("sync_form_recipients failed for website %s", website.pk)
            return Response(
                {"detail": "Could not read the site's form settings."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response({"updated": updated, "source": source})
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/websites/test_sync_form_recipients_action.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add apps/websites/views.py tests/websites/test_sync_form_recipients_action.py
git commit -m "feat(forms): manual recipient sync falls back to the WP REST path"
```

---

### Task 10: Frontend — show the new source

**Files:**
- Modify: `frontend/src/lib/api.ts:441` (union type)
- Modify: `frontend/src/lib/detected-forms.ts:79` (merge precedence)
- Modify: `frontend/src/components/form-detail-dialog.tsx:61` (source label)
- Modify: `frontend/src/components/sync-form-recipients-button.tsx:32,57` (error copy)

**Interfaces:**
- Consumes: `recipient_source` value `"wp_api"` (Task 1), the `source` response key (Task 9).
- Produces: no new symbols.

These files must tolerate the backend not having shipped yet — the frontend deploys separately via pm2 while the backend deploys via `./deploy.sh`, so a frontend that ships first still has to render.

- [ ] **Step 1: Widen the type**

```typescript
// frontend/src/lib/api.ts
  recipient_source: "" | "page" | "wp_api" | "wordpress";
```

- [ ] **Step 2: Fix the merge precedence**

The current line only promotes `wordpress`. Replace it with a ranked comparison so a `wp_api` row is not silently downgraded to `page`:

```typescript
// frontend/src/lib/detected-forms.ts
      // One form's copies across pages share a destination, but not necessarily
      // a source: the site's own API fills the rows it can match, and the
      // markup fills the rest. Report the strongest of the three.
      const rank = { "": 0, page: 1, wp_api: 2, wordpress: 3 } as const;
      if (rank[f.recipient_source] > rank[existing.recipient_source]) {
        existing.recipient_source = f.recipient_source;
      }
```

- [ ] **Step 3: Label the source in the detail dialog**

Replace the boolean at line 61 with a label lookup, keeping the existing rendering below it:

```typescript
    const sourceLabel =
      form.recipient_source === "wordpress"
        ? "Reported by WordPress"
        : form.recipient_source === "wp_api"
          ? "Read from the site's WordPress API"
          : "Read from the page";
```

Use `sourceLabel` wherever `fromWordPress` currently drives the copy.

- [ ] **Step 4: Update the sync button's error copy**

The 409 message now names both options, so the toast should stop hardcoding WP Connect:

```typescript
          title: "Could not read the form settings",
          description:
            "Add WordPress credentials for this website, or set up WP Connect.",
```

Apply at both call sites (lines 32 and 57).

- [ ] **Step 5: Verify the build**

```bash
cd frontend && npm run lint && npm run build
```
Expected: no type errors on `recipient_source`.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/lib/detected-forms.ts frontend/src/components/form-detail-dialog.tsx frontend/src/components/sync-form-recipients-button.tsx
git commit -m "feat(forms): show recipients read over the site's WordPress API"
```

---

### Task 11: Document the new path

`CLAUDE.md` currently states that WordPress is the only non-page source and that the column reads "Server-side" on the sites Digivault monitors. That is now incomplete, and the next person will act on it.

**Files:**
- Modify: `CLAUDE.md` (the "A form's recipient has two sources" paragraph)

- [ ] **Step 1: Update the architecture note**

Amend that paragraph to state there are now three sources ranked `page < wp_api < wordpress`; that the REST path needs only a vaulted WordPress credential but reaches **Elementor >= 3.27.0 and Gravity Forms only**, because WordPress hides protected post meta from every API unless the plugin registers it with an `auth_callback` — which Contact Form 7 and WPForms do not; and that `_apply_page_recipients` must never overwrite either non-page source.

- [ ] **Step 2: Run the full suite**

Run: `pytest --create-db -q`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: record the WP REST recipient path and its coverage limits"
```

---

## Self-Review

**Spec coverage:** Credential storage → Task 2. Transport (`read_bytes`, Basic auth) → Tasks 3, 4. Reader registry → Task 4. Elementor reader → Task 5. Gravity reader → Task 6. Precedence + `WP_API` → Tasks 1, 4. Scheduling → Task 8. API → Task 9. Failure handling incl. auth lockout → Task 7. Audit-log resolution → Task 2. Testing → distributed per task. Frontend surfacing → Task 10. Docs → Task 11. No gaps.

**Placeholder scan:** No TBDs. The one genuinely unverified item — Elementor Pro's setting keys — is handled as a concrete capture step with a stated fallback rather than a "figure it out".

**Type consistency:** `apply_recipients(website, entries, source=None)` is used with `source=` in Tasks 4, 6, 7. `fetch_json` returns `(parsed, status)` everywhere. Readers take `(website, credential, fetch=None)` from Task 7 onward — Tasks 5 and 6 define them with two parameters and Task 7 widens both, which is why Task 7 restates each signature. `WpCredential` fields match between Tasks 2 and 4.
