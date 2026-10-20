# WordPress Activity Log — Phase 0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship WP Connect snippet v2 and the backend that receives, authenticates and persists everything it sends — with nothing yet surfaced in the UI except a rollout badge.

**Architecture:** The client's WordPress site buffers hook-generated events in a local table whose autoincrement `id` doubles as a delivery sequence number, then flushes batches to `POST /api/wp-activity/` signed with HMAC-SHA256 over the request body using the existing per-site `wp_sso_secret`. Django verifies the signature and a 300-second replay window, detects sequence gaps to request a resend, and persists events as `SiteEvent` rows (`source="wp_connect"`) and file-walk manifests as `FileManifest` rows. Nothing is surfaced: `source="wp_connect"` rows are filtered out of the existing Change Log until Phase 1.

**Tech Stack:** Django 5.1, DRF, Celery, PostgreSQL, pytest; PHP 7.4+ for the snippet (WordPress 5.8+ target, no Composer, no external PHP deps).

**Spec:** [docs/superpowers/specs/2026-09-01-wordpress-activity-log-design.md](../specs/2026-09-01-wordpress-activity-log-design.md)

## Global Constraints

- **Phase 0 surfaces nothing.** `SiteEvent` rows with `source="wp_connect"` MUST be excluded from the existing Change Log list view until Phase 1 (spec §5). Only the rollout badge is user-visible.
- **The snippet must be complete on the first paste** — every hook for all four families, plus the file walk. A second re-paste is the expensive thing (spec C2).
- **The snippet gains no new inbound capability.** Hooks in, signed POST out. No new remote-command routes (spec C3).
- **Fail open, fail quiet.** A collector error must never break the client's site: every hook body wrapped so a throw cannot propagate (spec C4).
- **Replay window: exactly 300 seconds.** Buffer cap: exactly **10 000** rows. `details` JSON sliced to exactly **1024** bytes. Dead-man switch: exactly **7 days**. Retention: **365 days** for categories `users`, `plugins`, `themes`, `core`, `files`; **90 days** for all others.
- **Signature scheme, verbatim:** `hash_hmac('sha256', timestamp . '.' . raw_body, wp_sso_secret)`, hex, lowercase. Headers `X-Digivault-Site`, `X-Digivault-Timestamp`, `X-Digivault-Signature`.
- **PHP symbol prefix is `dvc2_`.** Version constant `DVC_VERSION = 2`.
- **Test conventions (CLAUDE.md):** run `pytest --create-db` after any migration. Celery is eager. `response.data` is the raw payload — assert `resp.data["x"]`, not `resp.data["data"]["x"]`. The `no_network_in_tests` autouse fixture covers website creation; this feature adds no outbound calls, so no new mocks are needed.

---

## File Structure

| File | Responsibility |
|---|---|
| `apps/site_health/models.py` (modify) | `SiteEvent` new fields + index; new `FileManifest` model. |
| `apps/websites/models.py` (modify) | `Website.wp_connect_version` / `_last_ack` / `_last_seq`. |
| `apps/site_health/wp_activity_auth.py` (create) | Pure signature + replay verification. No Django imports beyond settings. |
| `apps/site_health/wp_activity_map.py` (create) | Pure WP `event_type` → (`SiteEvent.EventType`, `category`, `severity`) table. |
| `apps/site_health/wp_activity_seq.py` (create) | Pure sequence-gap detection. |
| `apps/site_health/serializers.py` (modify) | `WpActivityIngestSerializer`, `WpFileManifestIngestSerializer`. |
| `apps/site_health/views.py` (modify) | `WpActivityIngestView`; exclude `wp_connect` from the existing list view. |
| `apps/site_health/urls.py` (modify) | Route the public ingest endpoint. |
| `apps/site_health/tasks.py` (modify) | `purge_old_site_events`. |
| `config/settings/base.py` (modify) | Beat entry for the purge. |
| `apps/websites/serializers.py` (modify) | Expose `wp_connect_version` / `wp_connect_last_ack`. |
| `apps/websites/wp_sso_snippet.py` (modify) | Snippet v2: arbitration, buffer, hooks, flush, walk, dead-man. |
| `frontend/src/components/websites-client.tsx` (modify) | Rollout badge. |

The three `wp_activity_*` modules are split from `views.py` deliberately: each is a pure function with no DB or request access, testable without a database, mirroring how `apps/scripts/wp_assets.py` and `DiffEngine` are structured in this codebase.

---

### Task 1: Model extension and migration

**Files:**
- Modify: `apps/site_health/models.py`
- Modify: `apps/websites/models.py`
- Create: `apps/site_health/migrations/00XX_wp_activity.py` (generated)
- Create: `apps/websites/migrations/00XX_wp_connect_fields.py` (generated)
- Test: `tests/site_health/test_wp_activity_models.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `SiteEvent.source` / `.actor_ip` / `.actor_wp_id` / `.object_type` / `.object_id` / `.sequence` / `.category`; `SiteEvent.Source` and `SiteEvent.Category` choice classes; `FileManifest(website, walk_id, entries, walked_at, is_complete)`; `Website.wp_connect_version` (int), `.wp_connect_last_ack` (datetime|None), `.wp_connect_last_seq` (int).

- [ ] **Step 1: Write the failing test**

```python
# tests/site_health/test_wp_activity_models.py
import pytest
from django.utils import timezone

from apps.site_health.models import FileManifest, SiteEvent
from apps.websites.models import Website


@pytest.fixture
def website(db, team):
    return Website.objects.create(team=team, name="Acme", domain="acme.test")


def test_site_event_defaults_to_passive_source(website):
    event = SiteEvent.objects.create(
        website=website, event_type=SiteEvent.EventType.PAGE_DISCOVERED,
        summary="new page",
    )
    assert event.source == SiteEvent.Source.PASSIVE
    assert event.category == ""
    assert event.actor_ip is None
    assert event.actor_wp_id is None
    assert event.sequence is None


def test_site_event_accepts_wp_connect_attribution(website):
    event = SiteEvent.objects.create(
        website=website, event_type=SiteEvent.EventType.PLUGIN_UPDATED,
        summary="wp-rocket updated", source=SiteEvent.Source.WP_CONNECT,
        category=SiteEvent.Category.PLUGINS, actor="jdoe", actor_wp_id=7,
        actor_ip="41.1.2.3", object_type="plugin", object_id="wp-rocket",
        sequence=1042,
    )
    event.refresh_from_db()
    assert event.source == SiteEvent.Source.WP_CONNECT
    assert event.actor_ip == "41.1.2.3"
    assert event.sequence == 1042


def test_file_manifest_is_one_per_website_walk(website):
    FileManifest.objects.create(
        website=website, walk_id="w1", entries={"a.php": "abc"},
        is_complete=True, walked_at=timezone.now(),
    )
    assert FileManifest.objects.filter(website=website).count() == 1


def test_website_wp_connect_defaults(website):
    assert website.wp_connect_version == 0
    assert website.wp_connect_last_ack is None
    assert website.wp_connect_last_seq == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/site_health/test_wp_activity_models.py -v`
Expected: FAIL — `AttributeError: type object 'SiteEvent' has no attribute 'Source'`

- [ ] **Step 3: Extend `SiteEvent` and add `FileManifest`**

In `apps/site_health/models.py`, inside `class SiteEvent(BaseModel)`, after the
existing `Severity` class:

```python
    class Source(models.TextChoices):
        PASSIVE = "passive", "Passive detection"
        WP_CONNECT = "wp_connect", "WP Connect"
        MANUAL = "manual", "Manual entry"

    class Category(models.TextChoices):
        USERS = "users", "Users"
        PLUGINS = "plugins", "Plugins"
        THEMES = "themes", "Themes"
        CORE = "core", "WordPress core"
        CONTENT = "content", "Posts & pages"
        COMMERCE = "commerce", "WooCommerce"
        FILES = "files", "Files"
        SEO = "seo", "SEO"
        FORMS = "forms", "Forms"
        DISCOVERY = "discovery", "Discovery"
```

Add the WP Connect event types to the existing `EventType` class, after
`FORM_RECIPIENTS_CHANGED`:

```python
        # --- WP Connect (snippet v2). Attributed: these carry an actor. ---
        WP_LOGIN = "wp_login", "WP: user logged in"
        WP_LOGIN_FAILED = "wp_login_failed", "WP: login failed"
        WP_USER_CREATED = "wp_user_created", "WP: user created"
        WP_USER_UPDATED = "wp_user_updated", "WP: user updated"
        WP_USER_ROLE_CHANGED = "wp_user_role_changed", "WP: role changed"
        WP_USER_DELETED = "wp_user_deleted", "WP: user deleted"
        WP_PASSWORD_RESET = "wp_password_reset", "WP: password reset"
        WP_PLUGIN_ACTIVATED = "wp_plugin_activated", "WP: plugin activated"
        WP_PLUGIN_DEACTIVATED = "wp_plugin_deactivated", "WP: plugin deactivated"
        WP_PLUGIN_UPDATED = "wp_plugin_updated", "WP: plugin updated"
        WP_PLUGIN_DELETED = "wp_plugin_deleted", "WP: plugin deleted"
        WP_THEME_SWITCHED = "wp_theme_switched", "WP: theme switched"
        WP_THEME_UPDATED = "wp_theme_updated", "WP: theme updated"
        WP_THEME_DELETED = "wp_theme_deleted", "WP: theme deleted"
        WP_CORE_UPDATED = "wp_core_updated", "WP: core updated"
        WP_POST_PUBLISHED = "wp_post_published", "WP: post published"
        WP_POST_UPDATED = "wp_post_updated", "WP: post updated"
        WP_POST_TRASHED = "wp_post_trashed", "WP: post trashed"
        WP_POST_DELETED = "wp_post_deleted", "WP: post deleted"
        WP_ORDER_STATUS_CHANGED = "wp_order_status_changed", "WC: order status changed"
        WP_PRODUCT_UPDATED = "wp_product_updated", "WC: product updated"
        WP_ORDER_REFUNDED = "wp_order_refunded", "WC: order refunded"
        WP_BUFFER_OVERFLOW = "wp_buffer_overflow", "WP: event buffer overflowed"
```

Add the fields, after `occurred_at`:

```python
    source = models.CharField(
        max_length=20, choices=Source.choices, default=Source.PASSIVE, db_index=True
    )
    # Stored rather than derived from event_type: the enum is ~45 values and the
    # Change Log filters on category, which needs an index to stay cheap.
    category = models.CharField(max_length=20, choices=Category.choices, blank=True)
    actor_ip = models.GenericIPAddressField(null=True, blank=True)
    # WordPress user ID as well as the login, because logins get renamed and the
    # ID is what survives to link two events to the same person.
    actor_wp_id = models.IntegerField(null=True, blank=True)
    object_type = models.CharField(max_length=30, blank=True)
    object_id = models.CharField(max_length=200, blank=True)
    # The snippet buffer's autoincrement id. Gaps mean a flush was lost.
    sequence = models.BigIntegerField(null=True, blank=True)
```

Add to `SiteEvent.Meta.indexes`:

```python
            models.Index(fields=["website", "category", "-occurred_at"]),
```

Append the new model at the end of the file:

```python
class FileManifest(BaseModel):
    """One WordPress file walk: path -> md5 for wp-content.

    Stored from Phase 0, diffed from Phase 3. The snippet holds no baseline of
    its own — MalCare markets "we don't bloat your database", and keeping a
    50k-row checksum table on the client would be doing the thing they market
    against.

    `is_complete` exists because the walk arrives in slices. Diffing an
    incomplete manifest would report every not-yet-walked file as removed — the
    same failure mode that made snapshot-to-snapshot script diffing unusable.
    """

    website = models.ForeignKey(
        "websites.Website", on_delete=models.CASCADE, related_name="file_manifests"
    )
    walk_id = models.CharField(max_length=64)
    entries = models.JSONField(default=dict, blank=True)
    is_complete = models.BooleanField(default=False)
    walked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        unique_together = [("website", "walk_id")]
        indexes = [models.Index(fields=["website", "-created_at"])]

    def __str__(self) -> str:
        return f"FileManifest({self.website}, {len(self.entries)} files)"
```

In `apps/websites/models.py`, after `wp_api_auth_failed_at`:

```python
    # WP Connect snippet version pasted on this site. 0 = not installed, or a
    # pre-v2 snippet with no version reporting. Drives the rollout badge: a
    # re-paste campaign is impossible to run without knowing who is still on v1.
    wp_connect_version = models.IntegerField(default=0)
    wp_connect_last_ack = models.DateTimeField(null=True, blank=True)
    # Highest buffer row id accepted from this site. A batch starting above
    # last_seq + 1 means a flush was lost and a resend is requested.
    wp_connect_last_seq = models.BigIntegerField(default=0)
```

- [ ] **Step 4: Generate migrations**

Run: `python manage.py makemigrations site_health websites`
Expected: two migration files created.

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/site_health/test_wp_activity_models.py -v --create-db`
Expected: PASS (4 tests). `--create-db` is required — CLAUDE.md: without it the schema won't rebuild and tests error out.

- [ ] **Step 6: Commit**

```bash
git add apps/site_health/models.py apps/websites/models.py apps/site_health/migrations apps/websites/migrations tests/site_health/test_wp_activity_models.py
git commit -m "feat(site_health): SiteEvent attribution fields, FileManifest, WP Connect tracking"
```

---

### Task 2: Signature and replay verification

**Files:**
- Create: `apps/site_health/wp_activity_auth.py`
- Test: `tests/site_health/test_wp_activity_auth.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `REPLAY_WINDOW_SECONDS: int`; `verify_signature(secret: str, timestamp: str, raw_body: bytes, signature: str, now: int | None = None) -> bool`.

- [ ] **Step 1: Write the failing test**

```python
# tests/site_health/test_wp_activity_auth.py
import hashlib
import hmac

from apps.site_health.wp_activity_auth import REPLAY_WINDOW_SECONDS, verify_signature

SECRET = "s" * 32
BODY = b'{"events":[]}'


def sign(secret: str, timestamp: str, body: bytes) -> str:
    msg = timestamp.encode() + b"." + body
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


def test_valid_signature_accepted():
    assert verify_signature(SECRET, "1000", BODY, sign(SECRET, "1000", BODY), now=1000)


def test_wrong_secret_rejected():
    assert not verify_signature(SECRET, "1000", BODY, sign("other", "1000", BODY), now=1000)


def test_tampered_body_rejected():
    sig = sign(SECRET, "1000", BODY)
    assert not verify_signature(SECRET, "1000", b'{"events":[1]}', sig, now=1000)


def test_timestamp_outside_window_rejected():
    stale = 1000 - REPLAY_WINDOW_SECONDS - 1
    sig = sign(SECRET, str(stale), BODY)
    assert not verify_signature(SECRET, str(stale), BODY, sig, now=1000)


def test_timestamp_at_window_edge_accepted():
    edge = 1000 - REPLAY_WINDOW_SECONDS
    sig = sign(SECRET, str(edge), BODY)
    assert verify_signature(SECRET, str(edge), BODY, sig, now=1000)


def test_future_timestamp_outside_window_rejected():
    future = 1000 + REPLAY_WINDOW_SECONDS + 1
    sig = sign(SECRET, str(future), BODY)
    assert not verify_signature(SECRET, str(future), BODY, sig, now=1000)


def test_empty_secret_rejected():
    assert not verify_signature("", "1000", BODY, sign("", "1000", BODY), now=1000)


def test_non_numeric_timestamp_rejected():
    assert not verify_signature(SECRET, "abc", BODY, sign(SECRET, "abc", BODY), now=1000)


def test_signature_comparison_is_case_insensitive():
    sig = sign(SECRET, "1000", BODY).upper()
    assert verify_signature(SECRET, "1000", BODY, sig, now=1000)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/site_health/test_wp_activity_auth.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.site_health.wp_activity_auth'`

- [ ] **Step 3: Write the implementation**

```python
# apps/site_health/wp_activity_auth.py
"""Authentication for the WP Connect activity push.

Deliberately NOT the pattern used by `PhpErrorIngestView`, which binds on
`Origin`/`Referer`. A server-side PHP POST sends neither header, and that check
is written `if origin:` — so it passes vacuously. Acceptable for PHP warnings;
not for a payload carrying usernames, email addresses and IPs.

The per-site `wp_sso_secret` already exists on both ends, so the signed-body
scheme costs nothing new. The replay window matches MalCare's `bvTime` guard.
"""
from __future__ import annotations

import hashlib
import hmac
import time

REPLAY_WINDOW_SECONDS = 300


def verify_signature(
    secret: str,
    timestamp: str,
    raw_body: bytes,
    signature: str,
    now: int | None = None,
) -> bool:
    """True if `signature` is a valid HMAC for this body and is not stale.

    The window is two-sided: a timestamp far in the future is as suspect as one
    far in the past, and clock skew on the client's server is real, so the
    tolerance is symmetric rather than past-only.
    """
    if not secret or not signature:
        return False
    try:
        sent_at = int(timestamp)
    except (TypeError, ValueError):
        return False

    current = int(time.time()) if now is None else now
    if abs(current - sent_at) > REPLAY_WINDOW_SECONDS:
        return False

    message = timestamp.encode() + b"." + raw_body
    expected = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.strip().lower())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/site_health/test_wp_activity_auth.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add apps/site_health/wp_activity_auth.py tests/site_health/test_wp_activity_auth.py
git commit -m "feat(site_health): HMAC body signing for WP Connect activity push"
```

---

### Task 3: Event type mapping

**Files:**
- Create: `apps/site_health/wp_activity_map.py`
- Test: `tests/site_health/test_wp_activity_map.py`

**Interfaces:**
- Consumes: `SiteEvent.EventType`, `SiteEvent.Category`, `SiteEvent.Severity` (Task 1).
- Produces: `map_event(wp_type: str) -> tuple[str, str, str] | None` returning `(event_type, category, severity)`; `SUPPORTED_WP_TYPES: frozenset[str]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/site_health/test_wp_activity_map.py
from apps.site_health.models import SiteEvent
from apps.site_health.wp_activity_map import SUPPORTED_WP_TYPES, map_event


def test_maps_user_created_to_users_category():
    event_type, category, severity = map_event("user_created")
    assert event_type == SiteEvent.EventType.WP_USER_CREATED
    assert category == SiteEvent.Category.USERS
    assert severity == SiteEvent.Severity.WARNING


def test_role_change_is_warning_not_info():
    _, _, severity = map_event("user_role_changed")
    assert severity == SiteEvent.Severity.WARNING


def test_post_update_is_info():
    event_type, category, severity = map_event("post_updated")
    assert event_type == SiteEvent.EventType.WP_POST_UPDATED
    assert category == SiteEvent.Category.CONTENT
    assert severity == SiteEvent.Severity.INFO


def test_buffer_overflow_is_critical():
    _, _, severity = map_event("buffer_overflow")
    assert severity == SiteEvent.Severity.CRITICAL


def test_unknown_type_returns_none():
    assert map_event("not_a_real_hook") is None


def test_supported_types_matches_table():
    assert "plugin_activated" in SUPPORTED_WP_TYPES
    assert "not_a_real_hook" not in SUPPORTED_WP_TYPES


def test_every_supported_type_maps_to_a_real_enum_value():
    valid = {c.value for c in SiteEvent.EventType}
    for wp_type in SUPPORTED_WP_TYPES:
        event_type, _, _ = map_event(wp_type)
        assert event_type in valid, wp_type
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/site_health/test_wp_activity_map.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.site_health.wp_activity_map'`

- [ ] **Step 3: Write the implementation**

```python
# apps/site_health/wp_activity_map.py
"""WP Connect hook name -> (SiteEvent.EventType, category, severity).

An explicit table, not a derivation. The snippet's wire names are a contract
with pasted PHP that we cannot redeploy, so they are deliberately decoupled
from the Django enum values — renaming a `SiteEvent.EventType` must never
silently stop accepting events from sites already in the field.

Severity is assigned here rather than by the snippet for the same reason: it is
a product judgement that we want to be able to change without a re-paste.
"""
from __future__ import annotations

from apps.site_health.models import SiteEvent

_E = SiteEvent.EventType
_C = SiteEvent.Category
_S = SiteEvent.Severity

# wire name -> (event type, category, severity)
_TABLE: dict[str, tuple[str, str, str]] = {
    # Users. Account and role changes are WARNING, not INFO: on a client site
    # the agency did not touch, a new user is the single most useful early
    # signal that something is wrong.
    "login": (_E.WP_LOGIN, _C.USERS, _S.INFO),
    "login_failed": (_E.WP_LOGIN_FAILED, _C.USERS, _S.INFO),
    "user_created": (_E.WP_USER_CREATED, _C.USERS, _S.WARNING),
    "user_updated": (_E.WP_USER_UPDATED, _C.USERS, _S.INFO),
    "user_role_changed": (_E.WP_USER_ROLE_CHANGED, _C.USERS, _S.WARNING),
    "user_deleted": (_E.WP_USER_DELETED, _C.USERS, _S.WARNING),
    "password_reset": (_E.WP_PASSWORD_RESET, _C.USERS, _S.INFO),
    # Plugins and themes.
    "plugin_activated": (_E.WP_PLUGIN_ACTIVATED, _C.PLUGINS, _S.INFO),
    "plugin_deactivated": (_E.WP_PLUGIN_DEACTIVATED, _C.PLUGINS, _S.WARNING),
    "plugin_updated": (_E.WP_PLUGIN_UPDATED, _C.PLUGINS, _S.INFO),
    "plugin_deleted": (_E.WP_PLUGIN_DELETED, _C.PLUGINS, _S.WARNING),
    "theme_switched": (_E.WP_THEME_SWITCHED, _C.THEMES, _S.WARNING),
    "theme_updated": (_E.WP_THEME_UPDATED, _C.THEMES, _S.INFO),
    "theme_deleted": (_E.WP_THEME_DELETED, _C.THEMES, _S.WARNING),
    "core_updated": (_E.WP_CORE_UPDATED, _C.CORE, _S.INFO),
    # Content.
    "post_published": (_E.WP_POST_PUBLISHED, _C.CONTENT, _S.INFO),
    "post_updated": (_E.WP_POST_UPDATED, _C.CONTENT, _S.INFO),
    "post_trashed": (_E.WP_POST_TRASHED, _C.CONTENT, _S.INFO),
    "post_deleted": (_E.WP_POST_DELETED, _C.CONTENT, _S.WARNING),
    # Commerce.
    "order_status_changed": (_E.WP_ORDER_STATUS_CHANGED, _C.COMMERCE, _S.INFO),
    "product_updated": (_E.WP_PRODUCT_UPDATED, _C.COMMERCE, _S.INFO),
    "order_refunded": (_E.WP_ORDER_REFUNDED, _C.COMMERCE, _S.INFO),
    # Self-reported collector health. CRITICAL because it means events for this
    # site were dropped on the client and can never be recovered.
    "buffer_overflow": (_E.WP_BUFFER_OVERFLOW, _C.FILES, _S.CRITICAL),
}

SUPPORTED_WP_TYPES = frozenset(_TABLE)


def map_event(wp_type: str) -> tuple[str, str, str] | None:
    """Return (event_type, category, severity), or None for an unknown type.

    None rather than a raise: a site running a newer snippet than this backend
    is a normal state during rollout, and one unrecognised row must not reject
    the whole batch.
    """
    return _TABLE.get(wp_type)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/site_health/test_wp_activity_map.py -v --create-db`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add apps/site_health/wp_activity_map.py tests/site_health/test_wp_activity_map.py
git commit -m "feat(site_health): WP Connect hook -> SiteEvent mapping table"
```

---

### Task 4: Sequence gap detection

**Files:**
- Create: `apps/site_health/wp_activity_seq.py`
- Test: `tests/site_health/test_wp_activity_seq.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `check_sequence(last_seq: int, batch_seqs: list[int]) -> int | None` returning the sequence to resend from, or `None` when contiguous.

- [ ] **Step 1: Write the failing test**

```python
# tests/site_health/test_wp_activity_seq.py
from apps.site_health.wp_activity_seq import check_sequence


def test_contiguous_batch_has_no_gap():
    assert check_sequence(10, [11, 12, 13]) is None


def test_first_ever_batch_has_no_gap():
    assert check_sequence(0, [1, 2, 3]) is None


def test_gap_requests_resend_from_next_expected():
    assert check_sequence(10, [15, 16]) == 11


def test_replayed_batch_is_not_a_gap():
    # Already-seen rows: the ack was lost, not the batch. Accept, don't resend.
    assert check_sequence(20, [18, 19, 20]) is None


def test_partially_replayed_batch_is_not_a_gap():
    assert check_sequence(20, [19, 20, 21, 22]) is None


def test_buffer_reset_requests_resend_from_zero():
    # MalCare's offset_reset_required: MAX(id) below our stored offset means the
    # table was truncated or recreated. Ask for everything it still holds.
    assert check_sequence(500, [1, 2, 3]) == 0


def test_empty_batch_has_no_gap():
    assert check_sequence(10, []) is None


def test_batch_is_judged_on_its_minimum_not_its_first_element():
    # First element 15 looks like a gap, but 12 is present — and 12 is still
    # above the 11 we expected, so a resend is correct. What matters is that the
    # minimum drives the decision, not the arrival order.
    assert check_sequence(10, [15, 12, 14]) == 11
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/site_health/test_wp_activity_seq.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.site_health.wp_activity_seq'`

- [ ] **Step 3: Write the implementation**

```python
# apps/site_health/wp_activity_seq.py
"""Delivery-gap detection for the WP Connect push.

The snippet's buffer table uses an autoincrement primary key, so the row id is
already a per-site monotonic sequence. Comparing the batch's lowest id against
the highest we have accepted tells us whether a flush was lost — which gives a
fire-and-forget push the delivery guarantee of a polling drain, for the cost of
one integer column rather than a second transport.

Adapted from MalCare's `enforce_auto_incr_check`: when the site's MAX(id) is
below the stored offset, the table was truncated and the server responds
`offset_reset_required` rather than silently missing events.
"""
from __future__ import annotations

def check_sequence(last_seq: int, batch_seqs: list[int]) -> int | None:
    """Return the sequence to resend from, or None when nothing is missing.

    Returns 0 for a buffer reset — "send everything you still have" — because
    after a truncate there is no meaningful offset to resume from.
    """
    if not batch_seqs:
        return None

    lowest = min(batch_seqs)

    # Buffer reset. MySQL restarts an AUTO_INCREMENT at 1 after the table is
    # dropped or truncated, so id 1 arriving from a site we have already read
    # past means the table is not the one we were counting. This must be tested
    # BEFORE the replay branch below, which would otherwise swallow it — a reset
    # batch is, by definition, entirely at or below `last_seq`.
    if lowest == 1 and last_seq > 0:
        return 0

    # Rows we have already accepted: the ack was lost, not the batch. The view
    # deduplicates on (website, sequence), so taking them again is harmless.
    if lowest <= last_seq:
        return None

    # Exactly the next row we expected.
    if lowest == last_seq + 1:
        return None

    return last_seq + 1
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/site_health/test_wp_activity_seq.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add apps/site_health/wp_activity_seq.py tests/site_health/test_wp_activity_seq.py
git commit -m "feat(site_health): sequence-gap detection for WP Connect push"
```

---

### Task 5: Ingest endpoint

**Files:**
- Modify: `apps/site_health/serializers.py`
- Modify: `apps/site_health/views.py`
- Modify: `apps/site_health/urls.py`
- Test: `tests/site_health/test_wp_activity_ingest.py`

**Interfaces:**
- Consumes: `verify_signature` (Task 2), `map_event` (Task 3), `check_sequence` (Task 4), models from Task 1.
- Produces: `POST /api/wp-activity/` accepting `{"snippet_version": int, "events": [...], "manifest": {...}|null}` and returning `{"accepted": int, "resend_from": int|null}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/site_health/test_wp_activity_ingest.py
import hashlib
import hmac
import json
import time

import pytest

from apps.site_health.models import FileManifest, SiteEvent
from apps.websites.models import Website

SECRET = "s" * 32


@pytest.fixture
def website(db, team):
    return Website.objects.create(
        team=team, name="Acme", domain="acme.test", wp_sso_secret=SECRET
    )


def post(client, website, payload, secret=SECRET, timestamp=None):
    body = json.dumps(payload).encode()
    ts = timestamp or str(int(time.time()))
    sig = hmac.new(secret.encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()
    return client.post(
        "/api/wp-activity/", data=body, content_type="application/json",
        HTTP_X_DIGIVAULT_SITE=website.site_id,
        HTTP_X_DIGIVAULT_TIMESTAMP=ts,
        HTTP_X_DIGIVAULT_SIGNATURE=sig,
    )


def _event(seq, wp_type="user_created", **kw):
    base = {
        "seq": seq, "type": wp_type, "occurred_at": "2026-09-01T10:00:00Z",
        "summary": "admin user bob created", "actor_login": "jdoe",
        "actor_id": 7, "actor_ip": "41.1.2.3",
        "object_type": "user", "object_id": "42", "details": {"role": "administrator"},
    }
    base.update(kw)
    return base


def test_valid_batch_creates_attributed_site_events(api_client, website):
    resp = post(api_client, website, {"snippet_version": 2, "events": [_event(1)]})
    assert resp.status_code == 202
    assert resp.data["accepted"] == 1
    assert resp.data["resend_from"] is None

    event = SiteEvent.objects.get(website=website)
    assert event.source == SiteEvent.Source.WP_CONNECT
    assert event.category == SiteEvent.Category.USERS
    assert event.actor == "jdoe"
    assert event.actor_wp_id == 7
    assert event.actor_ip == "41.1.2.3"
    assert event.sequence == 1


def test_bad_signature_rejected(api_client, website):
    resp = post(api_client, website, {"snippet_version": 2, "events": [_event(1)]},
                secret="wrong")
    assert resp.status_code == 403
    assert SiteEvent.objects.count() == 0


def test_stale_timestamp_rejected(api_client, website):
    stale = str(int(time.time()) - 400)
    resp = post(api_client, website, {"snippet_version": 2, "events": [_event(1)]},
                timestamp=stale)
    assert resp.status_code == 403


def test_unknown_site_id_returns_404(api_client, website):
    website.site_id = "nope"
    resp = post(api_client, website, {"snippet_version": 2, "events": []})
    assert resp.status_code == 404


def test_site_without_secret_rejected(api_client, website):
    website.wp_sso_secret = ""
    website.save(update_fields=["wp_sso_secret"])
    resp = post(api_client, website, {"snippet_version": 2, "events": [_event(1)]},
                secret="")
    assert resp.status_code == 403


def test_sequence_gap_requests_resend(api_client, website):
    website.wp_connect_last_seq = 10
    website.save(update_fields=["wp_connect_last_seq"])
    resp = post(api_client, website, {"snippet_version": 2, "events": [_event(15)]})
    assert resp.status_code == 202
    assert resp.data["resend_from"] == 11


def test_replayed_batch_does_not_duplicate(api_client, website):
    payload = {"snippet_version": 2, "events": [_event(1)]}
    post(api_client, website, payload)
    post(api_client, website, payload)
    assert SiteEvent.objects.filter(website=website).count() == 1


def test_unknown_event_type_skipped_batch_still_accepted(api_client, website):
    resp = post(api_client, website, {
        "snippet_version": 2,
        "events": [_event(1, wp_type="from_the_future"), _event(2)],
    })
    assert resp.status_code == 202
    assert resp.data["accepted"] == 1
    assert SiteEvent.objects.count() == 1


def test_accepting_a_batch_records_snippet_version_and_ack(api_client, website):
    post(api_client, website, {"snippet_version": 2, "events": [_event(3)]})
    website.refresh_from_db()
    assert website.wp_connect_version == 2
    assert website.wp_connect_last_ack is not None
    assert website.wp_connect_last_seq == 3


def test_manifest_slice_stored_incomplete(api_client, website):
    post(api_client, website, {
        "snippet_version": 2, "events": [],
        "manifest": {"walk_id": "w1", "entries": {"a.php": "h1"}, "complete": False},
    })
    manifest = FileManifest.objects.get(website=website, walk_id="w1")
    assert manifest.is_complete is False
    assert manifest.entries == {"a.php": "h1"}


def test_manifest_slices_accumulate_and_complete(api_client, website):
    post(api_client, website, {
        "snippet_version": 2, "events": [],
        "manifest": {"walk_id": "w1", "entries": {"a.php": "h1"}, "complete": False},
    })
    post(api_client, website, {
        "snippet_version": 2, "events": [],
        "manifest": {"walk_id": "w1", "entries": {"b.php": "h2"}, "complete": True},
    })
    manifest = FileManifest.objects.get(website=website, walk_id="w1")
    assert manifest.entries == {"a.php": "h1", "b.php": "h2"}
    assert manifest.is_complete is True
    assert manifest.walked_at is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/site_health/test_wp_activity_ingest.py -v --create-db`
Expected: FAIL — 404 on `/api/wp-activity/`, route not registered.

- [ ] **Step 3: Add the serializers**

Append to `apps/site_health/serializers.py`:

```python
class WpActivityEventSerializer(serializers.Serializer):
    seq = serializers.IntegerField(min_value=1)
    type = serializers.CharField(max_length=40)
    occurred_at = serializers.DateTimeField()
    summary = serializers.CharField(max_length=500, allow_blank=True)
    actor_login = serializers.CharField(max_length=200, allow_blank=True, required=False, default="")
    actor_id = serializers.IntegerField(required=False, allow_null=True, default=None)
    actor_ip = serializers.IPAddressField(required=False, allow_null=True, default=None)
    object_type = serializers.CharField(max_length=30, allow_blank=True, required=False, default="")
    object_id = serializers.CharField(max_length=200, allow_blank=True, required=False, default="")
    details = serializers.JSONField(required=False, default=dict)


class WpManifestSliceSerializer(serializers.Serializer):
    walk_id = serializers.CharField(max_length=64)
    entries = serializers.DictField(child=serializers.CharField(max_length=64))
    complete = serializers.BooleanField(default=False)


class WpActivityIngestSerializer(serializers.Serializer):
    snippet_version = serializers.IntegerField(min_value=1)
    events = WpActivityEventSerializer(many=True, required=False, default=list)
    manifest = WpManifestSliceSerializer(required=False, allow_null=True, default=None)
```

- [ ] **Step 4: Add the view**

Append to `apps/site_health/views.py`, with the imports it needs at the top of
the file:

```python
class WpActivityIngestView(APIView):
    """POST /api/wp-activity/ — WP Connect snippet v2 event push.

    Authenticated by an HMAC over the raw body, not by Origin/Referer: a
    server-side PHP POST sends neither, so the `PhpErrorIngestView` check would
    pass vacuously — tolerable for PHP warnings, not for usernames and IPs.
    """

    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    MAX_BODY_BYTES = 2 * 1024 * 1024

    def post(self, request):
        content_length = request.META.get("CONTENT_LENGTH")
        try:
            if content_length and int(content_length) > self.MAX_BODY_BYTES:
                return Response(status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        except (TypeError, ValueError):
            pass

        site_id = request.META.get("HTTP_X_DIGIVAULT_SITE", "")
        try:
            website = Website.objects.get(site_id=site_id)
        except Website.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        if not verify_signature(
            website.wp_sso_secret,
            request.META.get("HTTP_X_DIGIVAULT_TIMESTAMP", ""),
            request.body,
            request.META.get("HTTP_X_DIGIVAULT_SIGNATURE", ""),
        ):
            return Response(status=status.HTTP_403_FORBIDDEN)

        ser = WpActivityIngestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        events = data["events"]
        resend_from = check_sequence(
            website.wp_connect_last_seq, [e["seq"] for e in events]
        )

        accepted = 0
        highest = website.wp_connect_last_seq
        for entry in events:
            # Advance the offset for EVERY row received, including ones we
            # choose not to store. The snippet deletes what it sent, so leaving
            # a skipped row out of `highest` would make the next batch look like
            # it had a gap and trigger a resend the snippet cannot satisfy.
            highest = max(highest, entry["seq"])

            mapped = map_event(entry["type"])
            # An unrecognised type means the site runs a newer snippet than this
            # backend — normal during rollout. Skip the row, keep the batch.
            if mapped is None:
                continue
            event_type, category, severity = mapped
            _, created = SiteEvent.objects.get_or_create(
                website=website,
                sequence=entry["seq"],
                defaults={
                    "event_type": event_type,
                    "category": category,
                    "severity": severity,
                    "source": SiteEvent.Source.WP_CONNECT,
                    "summary": entry["summary"],
                    "details": entry["details"],
                    "actor": entry["actor_login"],
                    "actor_wp_id": entry["actor_id"],
                    "actor_ip": entry["actor_ip"],
                    "object_type": entry["object_type"],
                    "object_id": entry["object_id"],
                    "occurred_at": entry["occurred_at"],
                },
            )
            if created:
                accepted += 1

        manifest = data.get("manifest")
        if manifest:
            self._store_manifest(website, manifest)

        website.wp_connect_version = data["snippet_version"]
        website.wp_connect_last_ack = timezone.now()
        website.wp_connect_last_seq = highest
        website.save(update_fields=[
            "wp_connect_version", "wp_connect_last_ack", "wp_connect_last_seq",
        ])

        return Response(
            {"accepted": accepted, "resend_from": resend_from},
            status=status.HTTP_202_ACCEPTED,
        )

    @staticmethod
    def _store_manifest(website, slice_data):
        """Accumulate one walk slice. Diffing waits for Phase 3.

        Slices merge into one row per walk_id and are only marked complete when
        the snippet says the walk finished — diffing a partial manifest would
        report every not-yet-walked file as removed.
        """
        manifest, _ = FileManifest.objects.get_or_create(
            website=website, walk_id=slice_data["walk_id"]
        )
        merged = dict(manifest.entries)
        merged.update(slice_data["entries"])
        manifest.entries = merged
        if slice_data["complete"]:
            manifest.is_complete = True
            manifest.walked_at = timezone.now()
        manifest.save(update_fields=["entries", "is_complete", "walked_at"])
```

Add to the imports at the top of `apps/site_health/views.py`:

```python
from apps.site_health.models import FileManifest
from apps.site_health.serializers import WpActivityIngestSerializer
from apps.site_health.wp_activity_auth import verify_signature
from apps.site_health.wp_activity_map import map_event
from apps.site_health.wp_activity_seq import check_sequence
```

- [ ] **Step 5: Register the route**

In `apps/site_health/urls.py`, add `WpActivityIngestView` to the import list and
add to the public `urlpatterns`:

```python
    path("wp-activity/", WpActivityIngestView.as_view(), name="wp-activity-ingest"),
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/site_health/test_wp_activity_ingest.py -v --create-db`
Expected: PASS (11 tests)

- [ ] **Step 7: Commit**

```bash
git add apps/site_health/serializers.py apps/site_health/views.py apps/site_health/urls.py tests/site_health/test_wp_activity_ingest.py
git commit -m "feat(site_health): /api/wp-activity/ signed ingest endpoint"
```

---

### Task 6: Hide WP Connect events until Phase 1

**Files:**
- Modify: `apps/site_health/views.py` (`WebsiteSiteEventListView.get_queryset`)
- Test: `tests/site_health/test_wp_activity_hidden.py`

**Interfaces:**
- Consumes: `SiteEvent.Source` (Task 1).
- Produces: no new symbols.

- [ ] **Step 1: Write the failing test**

```python
# tests/site_health/test_wp_activity_hidden.py
import pytest

from apps.site_health.models import SiteEvent
from apps.websites.models import Website


@pytest.fixture
def website(db, team):
    return Website.objects.create(team=team, name="Acme", domain="acme.test")


def test_wp_connect_events_hidden_from_change_log(auth_client, website):
    SiteEvent.objects.create(
        website=website, event_type=SiteEvent.EventType.PAGE_DISCOVERED,
        summary="passive one", source=SiteEvent.Source.PASSIVE,
    )
    SiteEvent.objects.create(
        website=website, event_type=SiteEvent.EventType.WP_USER_CREATED,
        summary="attributed one", source=SiteEvent.Source.WP_CONNECT,
        category=SiteEvent.Category.USERS,
    )
    resp = auth_client.get(f"/api/v1/websites/{website.id}/events/")
    assert resp.status_code == 200
    summaries = [row["summary"] for row in resp.data]
    assert "passive one" in summaries
    assert "attributed one" not in summaries
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/site_health/test_wp_activity_hidden.py -v --create-db`
Expected: FAIL — `assert "attributed one" not in summaries` fails; both rows returned.

- [ ] **Step 3: Exclude the source**

In `apps/site_health/views.py`, change `WebsiteSiteEventListView.get_queryset`:

```python
        return (
            SiteEvent.objects
            .filter(website__team=team, website_id=self.kwargs["website_pk"])
            # Phase 0 persists WP Connect events but does not surface them: the
            # passive/attributed merge lands in Phase 1, and until it does a
            # plugin update would appear twice on every re-pasted site.
            .exclude(source=SiteEvent.Source.WP_CONNECT)
            .order_by("-occurred_at")[:200]
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/site_health/test_wp_activity_hidden.py -v --create-db`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/site_health/views.py tests/site_health/test_wp_activity_hidden.py
git commit -m "feat(site_health): hide WP Connect events from Change Log until Phase 1"
```

---

### Task 7: Tiered retention purge

**Files:**
- Modify: `apps/site_health/tasks.py`
- Modify: `config/settings/base.py`
- Test: `tests/site_health/test_site_event_purge.py`

**Interfaces:**
- Consumes: `SiteEvent.Category` (Task 1).
- Produces: `purge_old_site_events() -> int`, Celery task name `site_health.purge_old_site_events`; constants `SECURITY_RETENTION_DAYS = 365`, `DEFAULT_RETENTION_DAYS = 90`.

- [ ] **Step 1: Write the failing test**

```python
# tests/site_health/test_site_event_purge.py
import pytest
from django.utils import timezone
from django.utils.timezone import timedelta

from apps.site_health.models import SiteEvent
from apps.site_health.tasks import purge_old_site_events
from apps.websites.models import Website


@pytest.fixture
def website(db, team):
    return Website.objects.create(team=team, name="Acme", domain="acme.test")


def make(website, category, age_days):
    return SiteEvent.objects.create(
        website=website, event_type=SiteEvent.EventType.WP_USER_CREATED,
        summary="x", category=category,
        occurred_at=timezone.now() - timedelta(days=age_days),
    )


def test_security_events_survive_to_365_days(website):
    keep = make(website, SiteEvent.Category.USERS, 300)
    purge_old_site_events()
    assert SiteEvent.objects.filter(pk=keep.pk).exists()


def test_security_events_purged_past_365_days(website):
    old = make(website, SiteEvent.Category.USERS, 400)
    purge_old_site_events()
    assert not SiteEvent.objects.filter(pk=old.pk).exists()


def test_content_events_purged_past_90_days(website):
    old = make(website, SiteEvent.Category.CONTENT, 100)
    purge_old_site_events()
    assert not SiteEvent.objects.filter(pk=old.pk).exists()


def test_content_events_survive_to_90_days(website):
    keep = make(website, SiteEvent.Category.CONTENT, 30)
    purge_old_site_events()
    assert SiteEvent.objects.filter(pk=keep.pk).exists()


def test_uncategorised_legacy_events_use_default_tier(website):
    keep = make(website, "", 30)
    old = make(website, "", 100)
    purge_old_site_events()
    assert SiteEvent.objects.filter(pk=keep.pk).exists()
    assert not SiteEvent.objects.filter(pk=old.pk).exists()


def test_returns_number_deleted(website):
    make(website, SiteEvent.Category.CONTENT, 100)
    make(website, SiteEvent.Category.CONTENT, 100)
    assert purge_old_site_events() == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/site_health/test_site_event_purge.py -v --create-db`
Expected: FAIL — `ImportError: cannot import name 'purge_old_site_events'`

- [ ] **Step 3: Write the task**

Append to `apps/site_health/tasks.py`:

```python
# SiteEvent was the only event table in the codebase with no purge, which was
# survivable while it held a handful of SEO and page-discovery rows. WP Connect
# adds post, page and commerce volume across every client, so it is not
# survivable now. Security categories keep a full year because that is the
# window an agency is asked to account for; everything else keeps 90 days.
SECURITY_RETENTION_DAYS = 365
DEFAULT_RETENTION_DAYS = 90
_SECURITY_CATEGORIES = ("users", "plugins", "themes", "core", "files")


@shared_task(name="site_health.purge_old_site_events")
def purge_old_site_events() -> int:
    """Delete SiteEvent rows past their category's retention. Chunked."""
    from django.db.models import Q
    from django.utils.timezone import timedelta

    from apps.site_health.models import SiteEvent

    now = timezone.now()
    # Parenthesised explicitly. `&` binds tighter than `|` in Python, so the
    # intended grouping happens to be the default here — but relying on that is
    # how a later edit silently purges a year of security events.
    security_stale = Q(
        category__in=_SECURITY_CATEGORIES,
        occurred_at__lt=now - timedelta(days=SECURITY_RETENTION_DAYS),
    )
    other_stale = ~Q(category__in=_SECURITY_CATEGORIES) & Q(
        occurred_at__lt=now - timedelta(days=DEFAULT_RETENTION_DAYS)
    )
    stale = security_stale | other_stale

    total = 0
    chunk = 500
    while True:
        ids = list(
            SiteEvent.objects.filter(stale).values_list("pk", flat=True)[:chunk]
        )
        if not ids:
            break
        deleted, _ = SiteEvent.objects.filter(pk__in=ids).delete()
        total += deleted

    logger.info("site_health.purge_old_site_events: removed %d rows", total)
    return total
```

- [ ] **Step 4: Schedule it**

In `config/settings/base.py`, add to `CELERY_BEAT_SCHEDULE`:

```python
    # SiteEvent grew a WordPress activity feed; without a purge that table is
    # unbounded across every client. Sunday 03:30, right after the snapshot
    # purge and well clear of the 04:00-07:00 block where the SEO, scan and WP
    # sweeps contend for the per-host budget.
    "purge-old-site-events-weekly": {
        "task": "site_health.purge_old_site_events",
        "schedule": crontab(hour=3, minute=30, day_of_week="sunday"),
    },
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/site_health/test_site_event_purge.py -v --create-db`
Expected: PASS (6 tests)

- [ ] **Step 6: Commit**

```bash
git add apps/site_health/tasks.py config/settings/base.py tests/site_health/test_site_event_purge.py
git commit -m "feat(site_health): tiered SiteEvent retention purge"
```

---

### Task 8: Rollout badge API

**Files:**
- Modify: `apps/websites/serializers.py`
- Test: `tests/websites/test_wp_connect_badge.py`

**Interfaces:**
- Consumes: `Website.wp_connect_version` / `.wp_connect_last_ack` (Task 1).
- Produces: serializer fields `wp_connect_version` (int), `wp_connect_status` (str, one of `"current"` / `"outdated"` / `"stale"` / `"absent"`); `apps.websites.wp_sso_snippet.SNIPPET_VERSION = 2`, which Task 9 then uses to stamp the template.

**Note on ordering:** this task introduces `SNIPPET_VERSION` in
`wp_sso_snippet.py` even though the snippet itself is built in Task 9. One
constant, one source of truth — a separate `CURRENT_SNIPPET_VERSION` in the
serializer would drift from the version baked into the PHP the first time
either changed, and the badge would then confidently report the wrong thing.

- [ ] **Step 1: Write the failing test**

```python
# tests/websites/test_wp_connect_badge.py
import pytest
from django.utils import timezone
from django.utils.timezone import timedelta

from apps.websites.models import Website
from apps.websites.serializers import WebsiteSerializer


@pytest.fixture
def website(db, team):
    return Website.objects.create(team=team, name="Acme", domain="acme.test")


def test_absent_when_never_reported(website):
    assert WebsiteSerializer(website).data["wp_connect_status"] == "absent"


def test_current_when_latest_version_and_recent_ack(website):
    website.wp_connect_version = 2
    website.wp_connect_last_ack = timezone.now()
    assert WebsiteSerializer(website).data["wp_connect_status"] == "current"


def test_outdated_when_older_snippet_version(website):
    website.wp_connect_version = 1
    website.wp_connect_last_ack = timezone.now()
    assert WebsiteSerializer(website).data["wp_connect_status"] == "outdated"


def test_stale_when_ack_older_than_the_dead_man_window(website):
    website.wp_connect_version = 2
    website.wp_connect_last_ack = timezone.now() - timedelta(days=8)
    assert WebsiteSerializer(website).data["wp_connect_status"] == "stale"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/websites/test_wp_connect_badge.py -v --create-db`
Expected: FAIL — `KeyError: 'wp_connect_status'`

- [ ] **Step 3: Add the version constant to the snippet module**

At the top of `apps/websites/wp_sso_snippet.py`, above `_TEMPLATE`:

```python
# The version stamped into the template and reported by every flush. Task 9
# bakes this same value into the PHP; the rollout badge compares against it.
SNIPPET_VERSION = 2
```

- [ ] **Step 4: Add the serializer fields**

In `apps/websites/serializers.py`, add near the top and the field to
`WebsiteSerializer`:

```python
from apps.websites.wp_sso_snippet import SNIPPET_VERSION

# Matches the snippet's own dead-man switch: after this long with no accepted
# flush, the snippet has stopped collecting, so the dashboard must stop implying
# the site is reporting.
_SNIPPET_STALE_DAYS = 7
```

```python
    wp_connect_status = serializers.SerializerMethodField()

    def get_wp_connect_status(self, obj) -> str:
        """Where this site sits in the snippet rollout.

        Exists because a re-paste campaign across every client is impossible to
        run without knowing who is still on v1 — and nothing else user-facing
        depends on it, so it is the easiest piece to forget.
        """
        from django.utils import timezone
        from django.utils.timezone import timedelta

        if not obj.wp_connect_version or obj.wp_connect_last_ack is None:
            return "absent"
        if obj.wp_connect_last_ack < timezone.now() - timedelta(days=_SNIPPET_STALE_DAYS):
            return "stale"
        if obj.wp_connect_version < SNIPPET_VERSION:
            return "outdated"
        return "current"
```

Add `"wp_connect_version"` and `"wp_connect_status"` to the serializer's
`Meta.fields`.

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/websites/test_wp_connect_badge.py -v --create-db`
Expected: PASS (4 tests)

- [ ] **Step 6: Commit**

```bash
git add apps/websites/wp_sso_snippet.py apps/websites/serializers.py tests/websites/test_wp_connect_badge.py
git commit -m "feat(websites): expose WP Connect snippet rollout status"
```

---

### Task 9: Snippet v2 — version arbitration and buffer

**Files:**
- Modify: `apps/websites/wp_sso_snippet.py`
- Test: `tests/websites/test_wp_snippet_v2.py`

**Interfaces:**
- Consumes: `build_wp_sso_snippet(secret)` (existing); `SNIPPET_VERSION` (added in Task 8).
- Produces: `build_wp_sso_snippet(secret, site_id="", ingest_url="")` — two new optional keyword arguments, replacing `__DVC_SITE_ID__` and `__DVC_INGEST_URL__` in the template.

The snippet is PHP inside a Python string, so the tests assert on the generated
text rather than executing it. This is the same level of coverage the existing
`test_wp_sso.py` provides, and it catches the failures that actually happen:
an unreplaced placeholder, a missing guard, a leaked secret.

- [ ] **Step 1: Write the failing test**

```python
# tests/websites/test_wp_snippet_v2.py
from apps.websites.wp_sso_snippet import SNIPPET_VERSION, build_wp_sso_snippet

SECRET = "s" * 32


def build():
    return build_wp_sso_snippet(
        SECRET, site_id="site_abc", ingest_url="https://digivault.example/api/wp-activity/"
    )


def test_declares_its_version():
    assert "define( 'DVC_VERSION', 2 )" in build()
    assert SNIPPET_VERSION == 2


def test_bails_when_a_newer_snippet_is_already_loaded():
    php = build()
    # Highest version wins: a client who ADDS v2 beside v1 rather than replacing
    # it must not end up running v1's function bodies under v2's routes.
    assert "defined( 'DVC_VERSION' )" in php
    assert "DVC_VERSION >= 2" in php


def test_every_symbol_is_version_suffixed():
    php = build()
    assert "dvc_verify_token" not in php
    assert "dvc2_verify_token" in php


def test_no_placeholders_survive():
    php = build()
    assert "__DVC_" not in php


def test_secret_site_id_and_url_are_baked_in():
    php = build()
    assert SECRET in php
    assert "site_abc" in php
    assert "https://digivault.example/api/wp-activity/" in php


def test_buffer_table_is_capped():
    assert "10000" in build()


def test_details_are_sliced():
    assert "1024" in build()


def test_empty_secret_returns_nothing():
    assert build_wp_sso_snippet("", site_id="x", ingest_url="y") == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/websites/test_wp_snippet_v2.py -v`
Expected: FAIL — `ImportError: cannot import name 'SNIPPET_VERSION'`

- [ ] **Step 3: Add arbitration, the buffer, and the builder signature**

At the top of `_TEMPLATE` in `apps/websites/wp_sso_snippet.py`, immediately
after the `ABSPATH` guard, insert:

```php
/**
 * Version arbitration. A client who ADDS this snippet beside an older one —
 * rather than replacing it — would otherwise get the old snippet's function
 * bodies bound to this one's route registrations, silently and with no error.
 * Every symbol below is suffixed with the version so both can coexist, and the
 * highest version present wins.
 */
if ( defined( 'DVC_VERSION' ) && DVC_VERSION >= 2 ) { return; }
define( 'DVC_VERSION', 2 );

define( 'DVC2_SECRET',     '__DVC_SECRET__' );
define( 'DVC2_SITE_ID',    '__DVC_SITE_ID__' );
define( 'DVC2_INGEST_URL', '__DVC_INGEST_URL__' );

/** Hard caps. One hot hook in a loop must not fill the client's database. */
define( 'DVC2_MAX_ROWS',    10000 );
define( 'DVC2_MAX_DETAILS', 1024 );
define( 'DVC2_DEAD_DAYS',   7 );

/** The buffer table. Created lazily; its autoincrement id is the sequence. */
if ( ! function_exists( 'dvc2_table' ) ) {
	function dvc2_table() {
		global $wpdb;
		return $wpdb->prefix . 'digivault_events';
	}
}

if ( ! function_exists( 'dvc2_ensure_table' ) ) {
	function dvc2_ensure_table() {
		if ( get_option( 'dvc2_db_version' ) === '2' ) { return; }
		global $wpdb;
		require_once ABSPATH . 'wp-admin/includes/upgrade.php';
		$table   = dvc2_table();
		$collate = $wpdb->get_charset_collate();
		dbDelta( "CREATE TABLE {$table} (
			id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
			occurred_at DATETIME NOT NULL,
			event_type VARCHAR(40) NOT NULL,
			actor_login VARCHAR(200) NOT NULL DEFAULT '',
			actor_id BIGINT NULL,
			actor_ip VARCHAR(45) NOT NULL DEFAULT '',
			object_type VARCHAR(30) NOT NULL DEFAULT '',
			object_id VARCHAR(200) NOT NULL DEFAULT '',
			summary VARCHAR(500) NOT NULL DEFAULT '',
			details TEXT NULL,
			sent_at DATETIME NULL,
			PRIMARY KEY (id),
			KEY sent_at (sent_at)
		) {$collate};" );
		update_option( 'dvc2_db_version', '2', false );
	}
}

/**
 * Record one event. Never throws: a collector fault must not break the client's
 * site, so every failure here is swallowed deliberately.
 */
if ( ! function_exists( 'dvc2_record' ) ) {
	function dvc2_record( $type, $summary, $details = array(), $object_type = '', $object_id = '' ) {
		try {
			if ( ! dvc2_is_active() ) { return; }
			dvc2_ensure_table();
			global $wpdb;
			$table = dvc2_table();

			$count = (int) $wpdb->get_var( "SELECT COUNT(*) FROM {$table}" );
			if ( $count >= DVC2_MAX_ROWS ) {
				// Drop the oldest tenth and say so, rather than silently losing
				// the newest events or growing without bound.
				$cut = (int) ( DVC2_MAX_ROWS / 10 );
				$wpdb->query( "DELETE FROM {$table} ORDER BY id ASC LIMIT {$cut}" );
				$type    = 'buffer_overflow';
				$summary = 'Event buffer overflowed; oldest events were dropped.';
				$details = array( 'dropped' => $cut );
			}

			$user = wp_get_current_user();
			$wpdb->insert( $table, array(
				'occurred_at' => gmdate( 'Y-m-d H:i:s' ),
				'event_type'  => substr( (string) $type, 0, 40 ),
				'actor_login' => $user && $user->ID ? substr( $user->user_login, 0, 200 ) : '',
				'actor_id'    => $user && $user->ID ? (int) $user->ID : null,
				'actor_ip'    => dvc2_client_ip(),
				'object_type' => substr( (string) $object_type, 0, 30 ),
				'object_id'   => substr( (string) $object_id, 0, 200 ),
				'summary'     => substr( (string) $summary, 0, 500 ),
				'details'     => substr( wp_json_encode( dvc2_redact( $details ) ), 0, DVC2_MAX_DETAILS ),
			) );
		} catch ( Exception $e ) {
			return;
		} catch ( Error $e ) {
			return;
		}
	}
}

/**
 * Drop anything not explicitly allowed through. An allowlist, not a blocklist:
 * these hooks carry password and token material, and a blocklist is one new
 * WordPress release away from leaking it.
 */
if ( ! function_exists( 'dvc2_redact' ) ) {
	function dvc2_redact( $details ) {
		$allowed = array(
			'role', 'old_role', 'new_role', 'status', 'old_status', 'new_status',
			'slug', 'version', 'old_version', 'name', 'title', 'post_type',
			'order_id', 'total', 'currency', 'dropped', 'reason',
		);
		$out = array();
		foreach ( (array) $details as $key => $value ) {
			if ( in_array( $key, $allowed, true ) && is_scalar( $value ) ) {
				$out[ $key ] = substr( (string) $value, 0, 200 );
			}
		}
		return $out;
	}
}

if ( ! function_exists( 'dvc2_client_ip' ) ) {
	function dvc2_client_ip() {
		foreach ( array( 'HTTP_CF_CONNECTING_IP', 'HTTP_X_FORWARDED_FOR', 'REMOTE_ADDR' ) as $key ) {
			if ( empty( $_SERVER[ $key ] ) ) { continue; }
			$candidate = trim( explode( ',', (string) $_SERVER[ $key ] )[0] );
			if ( filter_var( $candidate, FILTER_VALIDATE_IP ) ) { return $candidate; }
		}
		return '';
	}
}

/**
 * The dead-man switch. A snippet has no uninstall hook, so a client who cancels
 * Digivault — or a site we can no longer reach — would otherwise buffer events
 * into their database forever. MalCare does the same with bvwatchtime.
 */
if ( ! function_exists( 'dvc2_is_active' ) ) {
	function dvc2_is_active() {
		$last = (int) get_option( 'dvc2_last_ack', 0 );
		if ( 0 === $last ) {
			// Never acked yet: allow collection so the first flush has something
			// to send, but only within the grace window.
			$first = (int) get_option( 'dvc2_installed_at', 0 );
			if ( 0 === $first ) {
				update_option( 'dvc2_installed_at', time(), false );
				return true;
			}
			return ( time() - $first ) < ( DVC2_DEAD_DAYS * DAY_IN_SECONDS );
		}
		return ( time() - $last ) < ( DVC2_DEAD_DAYS * DAY_IN_SECONDS );
	}
}
```

Rename every existing `dvc_` symbol in the template to `dvc2_` (there are the
helpers documented at the top of the file plus `dvc_handle_sso` and
`dvc_handle_forms`), and update the two `register_rest_route` callbacks to
match. Replace the inline `'__DVC_SECRET__'` usage in `dvc2_verify_token` with
`DVC2_SECRET`.

At the bottom of the module, replace the builder (`SNIPPET_VERSION` is already
defined at the top of the file from Task 8):

```python
def build_wp_sso_snippet(secret: str, site_id: str = "", ingest_url: str = "") -> str:
    """Return the ready-to-paste PHP snippet with per-site values baked in."""
    if not secret:
        return ""
    return (
        _TEMPLATE
        .replace("__DVC_SECRET__", secret)
        .replace("__DVC_SITE_ID__", site_id)
        .replace("__DVC_INGEST_URL__", ingest_url)
    )
```

Update `Website.wp_sso_snippet` in `apps/websites/models.py` to pass the two new
arguments:

```python
        from django.conf import settings

        from apps.websites.wp_sso_snippet import build_wp_sso_snippet

        base = getattr(settings, "SNIPPET_CDN_URL", "").rstrip("/")
        return build_wp_sso_snippet(
            self.wp_sso_secret,
            site_id=self.site_id,
            ingest_url=f"{base}/wp-activity/",
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/websites/test_wp_snippet_v2.py tests/websites/test_wp_sso.py -v --create-db`
Expected: PASS. `test_wp_sso.py` must still pass — if it asserts on `dvc_`
symbol names, update those assertions to `dvc2_`; the rename is intentional.

- [ ] **Step 5: Commit**

```bash
git add apps/websites/wp_sso_snippet.py apps/websites/models.py tests/websites/test_wp_snippet_v2.py tests/websites/test_wp_sso.py
git commit -m "feat(websites): snippet v2 version arbitration, event buffer, redaction"
```

---

### Task 10: Snippet v2 — hooks, flush, signing

**Files:**
- Modify: `apps/websites/wp_sso_snippet.py`
- Test: `tests/websites/test_wp_snippet_hooks.py`

**Interfaces:**
- Consumes: `dvc2_record`, `dvc2_is_active`, `DVC2_*` constants (Task 9).
- Produces: no Python symbols; the PHP template gains `dvc2_flush()` and the hook registrations.

- [ ] **Step 1: Write the failing test**

```python
# tests/websites/test_wp_snippet_hooks.py
import pytest

from apps.websites.wp_sso_snippet import build_wp_sso_snippet

SECRET = "s" * 32


@pytest.fixture
def php():
    return build_wp_sso_snippet(SECRET, site_id="s1", ingest_url="https://x.test/api/wp-activity/")


@pytest.mark.parametrize("hook", [
    "wp_login", "wp_login_failed", "user_register", "profile_update",
    "set_user_role", "delete_user", "password_reset",
    "activated_plugin", "deactivated_plugin", "upgrader_process_complete",
    "switch_theme", "deleted_plugin", "deleted_theme",
    "transition_post_status", "before_delete_post", "wp_trash_post",
    "woocommerce_order_status_changed", "woocommerce_update_product",
    "woocommerce_order_refunded",
])
def test_hook_is_registered(php, hook):
    assert f"'{hook}'" in php


def test_flush_runs_on_shutdown_and_on_cron(php):
    assert "add_action( 'shutdown'" in php
    assert "wp_schedule_event" in php
    assert "dvc2_cron_flush" in php


def test_flush_signs_the_body_not_the_url(php):
    # The signature must cover the payload; a URL-only signature would let a
    # captured request be replayed with a different body.
    assert "hash_hmac( 'sha256', $ts . '.' . $body, DVC2_SECRET )" in php


def test_flush_sends_the_three_auth_headers(php):
    assert "X-Digivault-Site" in php
    assert "X-Digivault-Timestamp" in php
    assert "X-Digivault-Signature" in php


def test_flush_records_the_ack_timestamp(php):
    assert "dvc2_last_ack" in php


def test_flush_honours_a_resend_request(php):
    assert "resend_from" in php


def test_acked_rows_are_deleted_not_just_marked(php):
    assert "DELETE FROM" in php
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/websites/test_wp_snippet_hooks.py -v`
Expected: FAIL — `assert "'wp_login_failed'" in php`

- [ ] **Step 3: Add the flush and the hooks**

Append inside `_TEMPLATE`, before the closing `"""`:

```php
/**
 * Send buffered events. Batched rather than one POST per hook: a request to
 * Digivault inside `user_register` would put our latency on the client's admin.
 */
if ( ! function_exists( 'dvc2_flush' ) ) {
	function dvc2_flush( $resend_from = null ) {
		try {
			if ( '' === DVC2_INGEST_URL || '' === DVC2_SITE_ID ) { return; }
			global $wpdb;
			$table = dvc2_table();
			if ( $wpdb->get_var( $wpdb->prepare( 'SHOW TABLES LIKE %s', $table ) ) !== $table ) { return; }

			$where = null === $resend_from ? '' : $wpdb->prepare( 'WHERE id >= %d', (int) $resend_from );
			$rows  = $wpdb->get_results( "SELECT * FROM {$table} {$where} ORDER BY id ASC LIMIT 200", ARRAY_A );
			$manifest = get_option( 'dvc2_pending_manifest', null );
			if ( empty( $rows ) && empty( $manifest ) ) { return; }

			$events = array();
			foreach ( (array) $rows as $row ) {
				$events[] = array(
					'seq'         => (int) $row['id'],
					'type'        => $row['event_type'],
					'occurred_at' => gmdate( 'c', strtotime( $row['occurred_at'] . ' UTC' ) ),
					'summary'     => $row['summary'],
					'actor_login' => $row['actor_login'],
					'actor_id'    => null === $row['actor_id'] ? null : (int) $row['actor_id'],
					'actor_ip'    => '' === $row['actor_ip'] ? null : $row['actor_ip'],
					'object_type' => $row['object_type'],
					'object_id'   => $row['object_id'],
					'details'     => json_decode( (string) $row['details'], true ),
				);
			}

			$payload = array( 'snippet_version' => DVC_VERSION, 'events' => $events );
			if ( ! empty( $manifest ) ) { $payload['manifest'] = $manifest; }

			$body = wp_json_encode( $payload );
			$ts   = (string) time();
			$sig  = hash_hmac( 'sha256', $ts . '.' . $body, DVC2_SECRET );

			$response = wp_remote_post( DVC2_INGEST_URL, array(
				'timeout'  => 5,
				'blocking' => true,
				'headers'  => array(
					'Content-Type'          => 'application/json',
					'X-Digivault-Site'      => DVC2_SITE_ID,
					'X-Digivault-Timestamp' => $ts,
					'X-Digivault-Signature' => $sig,
				),
				'body'     => $body,
			) );

			if ( is_wp_error( $response ) || 202 !== (int) wp_remote_retrieve_response_code( $response ) ) {
				return;
			}

			// Acked. Delete rather than mark sent: unacked rows must survive to
			// be re-sent, and the autoincrement keeps advancing past deletions
			// so the sequence stays monotonic.
			if ( ! empty( $rows ) ) {
				$highest = (int) $rows[ count( $rows ) - 1 ]['id'];
				$wpdb->query( $wpdb->prepare( "DELETE FROM {$table} WHERE id <= %d", $highest ) );
			}
			delete_option( 'dvc2_pending_manifest' );
			update_option( 'dvc2_last_ack', time(), false );

			$decoded = json_decode( (string) wp_remote_retrieve_body( $response ), true );
			$data    = isset( $decoded['data'] ) ? $decoded['data'] : $decoded;
			if ( is_array( $data ) && isset( $data['resend_from'] ) && null !== $data['resend_from'] ) {
				dvc2_flush( (int) $data['resend_from'] );
			}
		} catch ( Exception $e ) {
			return;
		} catch ( Error $e ) {
			return;
		}
	}
}

add_action( 'shutdown', 'dvc2_flush', 999 );

/**
 * Cron safety net. A low-traffic site may not fire enough shutdowns to matter;
 * a high-traffic one must not flush on every request. WP-cron is itself
 * traffic-driven, which matches how the rest of Digivault collects.
 */
add_action( 'dvc2_cron_flush', 'dvc2_flush' );
add_action( 'init', function () {
	if ( ! wp_next_scheduled( 'dvc2_cron_flush' ) ) {
		wp_schedule_event( time() + 300, 'dvc2_five_minutes', 'dvc2_cron_flush' );
	}
} );
add_filter( 'cron_schedules', function ( $schedules ) {
	$schedules['dvc2_five_minutes'] = array( 'interval' => 300, 'display' => 'Every 5 minutes' );
	return $schedules;
} );

/* ---------------------------------------------------------------------------
 * Hooks. Every callback is a thin call into dvc2_record, which swallows its own
 * failures — a collector fault must never break the client's site.
 * ------------------------------------------------------------------------- */

add_action( 'wp_login', function ( $login, $user ) {
	dvc2_record( 'login', sprintf( '%s logged in', $login ), array(), 'user', $user ? $user->ID : '' );
}, 10, 2 );

add_action( 'wp_login_failed', function ( $login ) {
	dvc2_record( 'login_failed', sprintf( 'Failed login for %s', $login ), array(), 'user', '' );
} );

add_action( 'user_register', function ( $user_id ) {
	$user = get_userdata( $user_id );
	$role = $user && ! empty( $user->roles ) ? $user->roles[0] : '';
	dvc2_record( 'user_created', sprintf( 'User %s created (%s)', $user ? $user->user_login : $user_id, $role ),
		array( 'role' => $role ), 'user', $user_id );
} );

add_action( 'profile_update', function ( $user_id ) {
	$user = get_userdata( $user_id );
	dvc2_record( 'user_updated', sprintf( 'User %s updated', $user ? $user->user_login : $user_id ),
		array(), 'user', $user_id );
} );

add_action( 'set_user_role', function ( $user_id, $role, $old_roles ) {
	$user = get_userdata( $user_id );
	dvc2_record( 'user_role_changed',
		sprintf( 'User %s role changed to %s', $user ? $user->user_login : $user_id, $role ),
		array( 'new_role' => $role, 'old_role' => is_array( $old_roles ) && $old_roles ? $old_roles[0] : '' ),
		'user', $user_id );
}, 10, 3 );

add_action( 'delete_user', function ( $user_id ) {
	$user = get_userdata( $user_id );
	dvc2_record( 'user_deleted', sprintf( 'User %s deleted', $user ? $user->user_login : $user_id ),
		array(), 'user', $user_id );
} );

add_action( 'password_reset', function ( $user ) {
	dvc2_record( 'password_reset', sprintf( 'Password reset for %s', $user->user_login ),
		array(), 'user', $user->ID );
} );

add_action( 'activated_plugin', function ( $plugin ) {
	dvc2_record( 'plugin_activated', sprintf( 'Plugin %s activated', $plugin ),
		array( 'slug' => $plugin ), 'plugin', $plugin );
} );

add_action( 'deactivated_plugin', function ( $plugin ) {
	dvc2_record( 'plugin_deactivated', sprintf( 'Plugin %s deactivated', $plugin ),
		array( 'slug' => $plugin ), 'plugin', $plugin );
} );

add_action( 'deleted_plugin', function ( $plugin ) {
	dvc2_record( 'plugin_deleted', sprintf( 'Plugin %s deleted', $plugin ),
		array( 'slug' => $plugin ), 'plugin', $plugin );
} );

add_action( 'switch_theme', function ( $name, $theme ) {
	dvc2_record( 'theme_switched', sprintf( 'Theme switched to %s', $name ),
		array( 'name' => $name, 'version' => $theme ? $theme->get( 'Version' ) : '' ), 'theme', $name );
}, 10, 2 );

add_action( 'deleted_theme', function ( $stylesheet ) {
	dvc2_record( 'theme_deleted', sprintf( 'Theme %s deleted', $stylesheet ),
		array( 'slug' => $stylesheet ), 'theme', $stylesheet );
} );

add_action( 'upgrader_process_complete', function ( $upgrader, $extra ) {
	$type = isset( $extra['type'] ) ? $extra['type'] : '';
	if ( 'plugin' === $type ) {
		foreach ( (array) ( isset( $extra['plugins'] ) ? $extra['plugins'] : array() ) as $slug ) {
			dvc2_record( 'plugin_updated', sprintf( 'Plugin %s updated', $slug ),
				array( 'slug' => $slug ), 'plugin', $slug );
		}
	} elseif ( 'theme' === $type ) {
		foreach ( (array) ( isset( $extra['themes'] ) ? $extra['themes'] : array() ) as $slug ) {
			dvc2_record( 'theme_updated', sprintf( 'Theme %s updated', $slug ),
				array( 'slug' => $slug ), 'theme', $slug );
		}
	} elseif ( 'core' === $type ) {
		dvc2_record( 'core_updated', 'WordPress core updated',
			array( 'version' => get_bloginfo( 'version' ) ), 'core', 'wordpress' );
	}
}, 10, 2 );

add_action( 'transition_post_status', function ( $new, $old, $post ) {
	if ( ! in_array( $post->post_type, array( 'post', 'page' ), true ) ) { return; }
	if ( $new === $old ) { return; }
	if ( 'trash' === $new ) {
		dvc2_record( 'post_trashed', sprintf( 'Trashed: %s', $post->post_title ),
			array( 'post_type' => $post->post_type ), $post->post_type, $post->ID );
	} elseif ( 'publish' === $new && 'publish' !== $old ) {
		dvc2_record( 'post_published', sprintf( 'Published: %s', $post->post_title ),
			array( 'post_type' => $post->post_type ), $post->post_type, $post->ID );
	} elseif ( 'publish' === $new ) {
		dvc2_record( 'post_updated', sprintf( 'Updated: %s', $post->post_title ),
			array( 'post_type' => $post->post_type ), $post->post_type, $post->ID );
	}
}, 10, 3 );

add_action( 'before_delete_post', function ( $post_id ) {
	$post = get_post( $post_id );
	if ( ! $post || ! in_array( $post->post_type, array( 'post', 'page' ), true ) ) { return; }
	dvc2_record( 'post_deleted', sprintf( 'Deleted: %s', $post->post_title ),
		array( 'post_type' => $post->post_type ), $post->post_type, $post_id );
} );

add_action( 'wp_trash_post', function ( $post_id ) {
	$post = get_post( $post_id );
	if ( ! $post || ! in_array( $post->post_type, array( 'post', 'page' ), true ) ) { return; }
	dvc2_record( 'post_trashed', sprintf( 'Trashed: %s', $post->post_title ),
		array( 'post_type' => $post->post_type ), $post->post_type, $post_id );
} );

add_action( 'woocommerce_order_status_changed', function ( $order_id, $from, $to ) {
	dvc2_record( 'order_status_changed', sprintf( 'Order #%s: %s to %s', $order_id, $from, $to ),
		array( 'old_status' => $from, 'new_status' => $to, 'order_id' => $order_id ), 'order', $order_id );
}, 10, 3 );

add_action( 'woocommerce_update_product', function ( $product_id ) {
	dvc2_record( 'product_updated', sprintf( 'Product #%s updated', $product_id ),
		array(), 'product', $product_id );
} );

add_action( 'woocommerce_order_refunded', function ( $order_id, $refund_id ) {
	dvc2_record( 'order_refunded', sprintf( 'Order #%s refunded', $order_id ),
		array( 'order_id' => $order_id ), 'order', $order_id );
}, 10, 2 );
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/websites/test_wp_snippet_hooks.py -v`
Expected: PASS (25 tests — 19 parametrised plus 6)

- [ ] **Step 5: Commit**

```bash
git add apps/websites/wp_sso_snippet.py tests/websites/test_wp_snippet_hooks.py
git commit -m "feat(websites): snippet v2 hooks, batched flush, signed transport"
```

---

### Task 11: Snippet v2 — file walk

**Files:**
- Modify: `apps/websites/wp_sso_snippet.py`
- Test: `tests/websites/test_wp_snippet_walk.py`

**Interfaces:**
- Consumes: `dvc2_is_active`, `DVC2_*` (Task 9); `dvc2_flush` (Task 10).
- Produces: no Python symbols; the template gains `dvc2_walk()` and its daily cron.

- [ ] **Step 1: Write the failing test**

```python
# tests/websites/test_wp_snippet_walk.py
import pytest

from apps.websites.wp_sso_snippet import build_wp_sso_snippet


@pytest.fixture
def php():
    return build_wp_sso_snippet("s" * 32, site_id="s1", ingest_url="https://x.test/api/wp-activity/")


def test_walk_is_scheduled_daily(php):
    assert "dvc2_cron_walk" in php
    assert "'daily'" in php


def test_walk_covers_the_three_wp_content_roots(php):
    assert "plugins" in php and "themes" in php and "mu-plugins" in php


def test_walk_is_chunked_with_a_cursor(php):
    # A 50k-file site cannot be walked in one cron tick without timing out.
    assert "dvc2_walk_cursor" in php
    assert "dvc2_walk_id" in php


def test_walk_marks_completion_explicitly(php):
    # Digivault must not diff a partial manifest: every unwalked file would read
    # as removed.
    assert "'complete'" in php


def test_walk_only_hashes_code_extensions(php):
    # Asserting on the literal list, not on the substring "php" — the whole
    # template is PHP, so a substring check here would pass no matter what.
    assert "array( 'php', 'js', 'htaccess' )" in php


def test_walk_skips_files_over_the_size_cap(php):
    assert "DVC2_MAX_FILE_BYTES" in php
    assert "2097152" in php
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/websites/test_wp_snippet_walk.py -v`
Expected: FAIL — `assert "dvc2_cron_walk" in php`

- [ ] **Step 3: Add the walk**

Append inside `_TEMPLATE`, before the closing `"""`:

```php
/** Files above this are not code and hashing them wastes the tick. */
define( 'DVC2_MAX_FILE_BYTES', 2097152 );
define( 'DVC2_WALK_SLICE',     400 );

/**
 * One slice of the daily wp-content walk.
 *
 * Chunked with a cursor because a 50k-file site cannot be walked inside one
 * cron tick. No baseline is kept here — Digivault holds it and diffs. Storing a
 * checksum table on the client would be the database bloat MalCare markets
 * against, and the diff belongs in Python where it can be tested.
 */
if ( ! function_exists( 'dvc2_walk' ) ) {
	function dvc2_walk() {
		try {
			if ( ! dvc2_is_active() ) { return; }

			$walk_id = get_option( 'dvc2_walk_id', '' );
			$cursor  = (int) get_option( 'dvc2_walk_cursor', 0 );
			if ( '' === $walk_id ) {
				$walk_id = uniqid( 'w', true );
				$cursor  = 0;
				update_option( 'dvc2_walk_id', $walk_id, false );
			}

			$roots = array(
				WP_CONTENT_DIR . '/plugins',
				WP_CONTENT_DIR . '/themes',
				WP_CONTENT_DIR . '/mu-plugins',
			);

			$paths = array();
			foreach ( $roots as $root ) {
				if ( ! is_dir( $root ) ) { continue; }
				$iterator = new RecursiveIteratorIterator(
					new RecursiveDirectoryIterator( $root, FilesystemIterator::SKIP_DOTS ),
					RecursiveIteratorIterator::LEAVES_ONLY
				);
				foreach ( $iterator as $file ) {
					if ( ! $file->isFile() ) { continue; }
					$ext = strtolower( $file->getExtension() );
					if ( ! in_array( $ext, array( 'php', 'js', 'htaccess' ), true ) ) { continue; }
					if ( $file->getSize() > DVC2_MAX_FILE_BYTES ) { continue; }
					$paths[] = $file->getPathname();
				}
			}
			sort( $paths );

			$slice   = array_slice( $paths, $cursor, DVC2_WALK_SLICE );
			$entries = array();
			foreach ( $slice as $path ) {
				$hash = @md5_file( $path );
				if ( false === $hash ) { continue; }
				$entries[ ltrim( str_replace( WP_CONTENT_DIR, '', $path ), '/\\' ) ] = $hash;
			}

			$next     = $cursor + DVC2_WALK_SLICE;
			$complete = $next >= count( $paths );

			update_option( 'dvc2_pending_manifest', array(
				'walk_id'  => $walk_id,
				'entries'  => $entries,
				'complete' => $complete,
			), false );

			if ( $complete ) {
				delete_option( 'dvc2_walk_id' );
				update_option( 'dvc2_walk_cursor', 0, false );
			} else {
				update_option( 'dvc2_walk_cursor', $next, false );
			}

			dvc2_flush();
		} catch ( Exception $e ) {
			return;
		} catch ( Error $e ) {
			return;
		}
	}
}

add_action( 'dvc2_cron_walk', 'dvc2_walk' );
add_action( 'init', function () {
	if ( ! wp_next_scheduled( 'dvc2_cron_walk' ) ) {
		wp_schedule_event( time() + 3600, 'daily', 'dvc2_cron_walk' );
	}
} );
```

**Note on slice cadence:** one slice per daily tick means a 50k-file site takes
months to complete a walk. That is acceptable in Phase 0, which only stores
manifests. Phase 3, which diffs them, must raise `DVC2_WALK_SLICE` or run the
walk cron more often — record this as a known Phase 3 prerequisite.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/websites/test_wp_snippet_walk.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Run the whole suite**

Run: `pytest --create-db -q`
Expected: PASS. Existing `test_wp_sso.py`, `test_wp_form_recipients.py` and
`test_verify_snippet.py` exercise the same template and must still pass.

- [ ] **Step 6: Commit**

```bash
git add apps/websites/wp_sso_snippet.py tests/websites/test_wp_snippet_walk.py
git commit -m "feat(websites): snippet v2 chunked wp-content file walk"
```

---

### Task 12: Rollout badge in the UI

**Files:**
- Modify: `frontend/src/lib/api.ts:131` (`export interface Website`)
- Modify: `frontend/src/components/websites-client.tsx`

**Interfaces:**
- Consumes: `wp_connect_status` from Task 8.
- Produces: no exported symbols.

- [ ] **Step 1: Extend the Website type**

In `frontend/src/lib/api.ts`, inside `export interface Website` (line 131), add:

```typescript
  /** Snippet rollout state. Optional: the frontend deploys separately from the
   *  backend, so a frontend that ships first must still render. */
  wp_connect_version?: number;
  wp_connect_status?: "current" | "outdated" | "stale" | "absent";
```

- [ ] **Step 2: Add the badge**

In `frontend/src/components/websites-client.tsx`, beside the existing per-site
badges:

```tsx
{site.wp_connect_status === "outdated" && (
  <Badge variant="destructive" title="This site runs an older WP Connect snippet. Re-paste to enable activity tracking.">
    Snippet v{site.wp_connect_version}
  </Badge>
)}
{site.wp_connect_status === "stale" && (
  <Badge variant="outline" title="No events received for over 7 days — the snippet has stopped collecting.">
    Snippet silent
  </Badge>
)}
```

The `absent` state renders nothing: most sites have never pasted the snippet,
and a badge on all of them is noise rather than a signal.

- [ ] **Step 3: Verify the build**

Run: `cd frontend && npm run lint && npm run build`
Expected: both pass.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/websites-client.tsx frontend/src/lib/api.ts
git commit -m "feat(frontend): WP Connect snippet rollout badge"
```

---

## Done criteria

- [ ] `pytest --create-db -q` passes.
- [ ] `cd frontend && npm run lint && npm run build` passes.
- [ ] A signed POST to `/api/wp-activity/` creates `SiteEvent` rows with `source="wp_connect"`.
- [ ] Those rows do **not** appear in `GET /api/v1/websites/{id}/events/`.
- [ ] `build_wp_sso_snippet()` output contains no `__DVC_` placeholders.
- [ ] The websites list shows a badge for sites on an outdated or silent snippet.

## Known follow-ups (not Phase 0)

- `DVC2_WALK_SLICE` must rise before Phase 3 diffs manifests — one 400-file slice per day is too slow for a real site.
- `SNIPPET_CDN_URL` must be set in `.env.production` for the ingest URL to be baked in correctly (CLAUDE.md already lists it as required).
- Re-paste campaign: the badge from Task 8/12 is the instrument; the campaign itself is an operational task, not a code one.
