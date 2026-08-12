# Form Recipient Lists, Cc/Bcc, and Change Alerts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store every address a form delivers to — multiple To recipients, plus Cc and Bcc — and announce it in the team's ClickUp channel when they change.

**Architecture:** `DetectedForm.recipient_email` (one address) becomes `DetectedForm.recipients` (a canonical `{"to": [], "cc": [], "bcc": []}` JSON dict). One new module, `apps/scripts/recipients.py`, owns parsing, normalizing and comparing that shape; every writer — page ingest, server-side scan, WP Connect fetch — goes through it. A change in the set, reported by the same source that reported it before, writes a `SiteEvent` and posts to the team's ClickUp channel.

**Tech Stack:** Django 5.1, DRF, Celery, PostgreSQL; PHP 7.4+ (the WP Connect snippet, no framework); Next.js 16 / React 19 / TypeScript frontend.

## Global Constraints

- **The migration must not lose data.** Existing rows carry a single `recipient_email`; it becomes `{"to": [that], "cc": [], "bcc": []}`. The add-and-backfill (Task 2) and the column drop (Task 8) are **separate migrations in separate deploys** — never combined.
- **No task may leave the test suite red.** Each one ends green and is independently reviewable.
- **`recipient_email` stays in the API as a read-only derived field** (`recipients["to"][0]`, else `""`). The frontend deploys separately from the backend (host-pm2 vs Docker), so a backend that dropped the key outright would blank the "Goes to" column until the frontend caught up.
- **Source precedence is unchanged and non-negotiable:** `wordpress` outranks `page`, and a page ingest must never overwrite a WordPress-sourced value or clear a stored one with an empty reading. See `_apply_page_recipient` in [tasks.py](apps/scripts/tasks.py).
- **A change is only a change within one source.** `page` → `wordpress` reporting a different address is a better *read*, not an edit to the form, and must not alert.
- **Never alert on first discovery.** Empty → populated is detection catching up, not a change.
- **Ingest stays lenient.** A malformed recipient must not 400 the payload — that would drop the scripts posted alongside it. Validation happens in the upsert, never in the ingest serializer.
- **`compute_fingerprint` must not read recipients.** It would mint a new row every time an address changed, splitting the form's submission history.
- **PHP readers stay guarded.** Every plugin reader checks `class_exists`/`post_type_exists` first; a site without that plugin contributes an empty list rather than a fatal.
- **Ship before the snippet is rolled out.** The `digivault/v1/forms` route exists in the repo but is not yet pasted on any client site. Cc/Bcc support lands in the same route, so doing this now costs one re-paste total instead of two.
- Run `pytest --create-db` after the model change, or the schema won't rebuild.

---

## File Structure

| File | Responsibility |
|---|---|
| `apps/scripts/recipients.py` | **New.** Parse, normalize, compare the `{to, cc, bcc}` shape. Pure functions, no DB. |
| `apps/scripts/models.py` | `DetectedForm.recipients` JSONField replaces `recipient_email`. |
| `apps/scripts/migrations/0026_*.py` | Add `recipients`, backfill from `recipient_email`. Additive only. |
| `apps/scripts/migrations/0027_*.py` | Drop `recipient_email`, after a release has run on the new field (Task 8). |
| `apps/site_health/models.py` | `SiteEvent.EventType.FORM_RECIPIENTS_CHANGED`. |
| `apps/scripts/tasks.py` | Page-ingest writer + the ClickUp delivery task. |
| `frontend/src/components/site-events-tab.tsx` | Icon and label for the new event type. |
| `apps/scripts/serializers.py` | Ingest accepts `recipients`; output exposes `recipients` + derived `recipient_email`. |
| `apps/scripts/tasks.py` | `_apply_page_recipient` → `_apply_page_recipients`, writing the dict. |
| `apps/scripts/snippet.js` | Read `mailto:` To/Cc/Bcc and cc/bcc hidden inputs; post `recipients`. |
| `apps/websites/wp_sso_snippet.py` | PHP readers return `to`/`cc`/`bcc` per plugin. |
| `apps/websites/wp_forms.py` | Apply the full dict; detect a change and hand it off. |
| `apps/websites/views.py` | Server-side scan extracts the same shape. |
| `apps/scripts/recipient_changes.py` | **New.** Decide whether a change is announceable, record it, notify. |
| `frontend/src/lib/detected-forms.ts` | Merge `to`/`cc`/`bcc` across pages. |
| `frontend/src/components/form-detail-dialog.tsx` | Show To / Cc / Bcc separately. |
| `frontend/src/components/forms-tab.tsx` | "Goes to" column reads the To list. |

---

## Task 1: The recipients shape

**Files:**
- Create: `apps/scripts/recipients.py`
- Test: `tests/scripts/test_recipients.py`

**Interfaces:**
- Consumes: `normalize_recipient_email` from `apps/scripts/normalize.py` (existing, unchanged).
- Produces:
  - `normalize_recipient_list(value: str | list | None) -> list[str]`
  - `build_recipients(to=..., cc=..., bcc=...) -> dict` → always `{"to": [...], "cc": [...], "bcc": [...]}`
  - `recipients_equal(a: dict, b: dict) -> bool`
  - `all_recipients(recipients: dict) -> list[str]`
  - `primary_recipient(recipients: dict) -> str`
  - ~~`EMPTY_RECIPIENTS: dict`~~ — **amended during execution.** A shared module-level dict of lists is the classic Python footgun: `MappingProxyType` only freezes the keys, and a plain dict lets any caller append into `EMPTY_RECIPIENTS["to"]` and corrupt it for the whole process. It earned too little to keep — `build_recipients()` already returns a fresh empty shape, and the one downstream use (`_format_recipients` in Task 7) only needs `{}`. Use `build_recipients()` or a literal instead.
  - `MAX_RECIPIENTS_PER_KIND: int`

- [ ] **Step 1: Write the failing tests**

Create `tests/scripts/test_recipients.py`:

```python
"""The {to, cc, bcc} recipient shape: parsing, canonicalising, comparing."""

import pytest

from apps.scripts.recipients import (
    EMPTY_RECIPIENTS,
    MAX_RECIPIENTS_PER_KIND,
    all_recipients,
    build_recipients,
    normalize_recipient_list,
    primary_recipient,
    recipients_equal,
)


class TestNormalizeRecipientList:
    def test_a_single_address(self):
        assert normalize_recipient_list("info@site.com") == ["info@site.com"]

    def test_a_comma_separated_list(self):
        """The reason this module exists.

        normalize_recipient_email rejects a comma-joined value outright, so an
        Elementor "To" holding two addresses stored nothing at all.
        """
        assert normalize_recipient_list("sales@site.com, dev@site.com") == [
            "sales@site.com",
            "dev@site.com",
        ]

    def test_semicolons_also_separate(self):
        assert normalize_recipient_list("a@site.com; b@site.com") == [
            "a@site.com",
            "b@site.com",
        ]

    def test_addresses_are_normalized_individually(self):
        assert normalize_recipient_list(" Info@Site.COM , Sales <sales@site.com>") == [
            "info@site.com",
            "sales@site.com",
        ]

    def test_duplicates_collapse_keeping_first_position(self):
        assert normalize_recipient_list("b@site.com, a@site.com, b@site.com") == [
            "b@site.com",
            "a@site.com",
        ]

    def test_junk_entries_are_dropped_not_fatal(self):
        assert normalize_recipient_list("good@site.com, not-an-email, [your-email]") == [
            "good@site.com"
        ]

    def test_a_list_input_is_accepted(self):
        """WordPress reports a JSON array; the page reports a string."""
        assert normalize_recipient_list(["A@site.com", "b@site.com"]) == [
            "a@site.com",
            "b@site.com",
        ]

    @pytest.mark.parametrize("value", ["", None, [], "   ", ",,;"])
    def test_nothing_yields_nothing(self, value):
        assert normalize_recipient_list(value) == []

    def test_a_runaway_list_is_capped(self):
        many = ", ".join(f"a{i}@site.com" for i in range(MAX_RECIPIENTS_PER_KIND + 10))
        assert len(normalize_recipient_list(many)) == MAX_RECIPIENTS_PER_KIND


class TestBuildRecipients:
    def test_all_three_keys_are_always_present(self):
        assert build_recipients(to="a@site.com") == {
            "to": ["a@site.com"],
            "cc": [],
            "bcc": [],
        }

    def test_empty_input_is_the_empty_shape(self):
        assert build_recipients() == EMPTY_RECIPIENTS
        assert build_recipients(to="", cc=None, bcc=[]) == EMPTY_RECIPIENTS

    def test_an_address_in_to_is_not_repeated_in_cc(self):
        """Elementor lets you put the same address in both; showing it twice
        reads as two destinations."""
        built = build_recipients(to="a@site.com", cc="a@site.com, b@site.com")
        assert built == {"to": ["a@site.com"], "cc": ["b@site.com"], "bcc": []}

    def test_bcc_is_deduped_against_both_to_and_cc(self):
        built = build_recipients(
            to="a@site.com", cc="b@site.com", bcc="a@site.com, b@site.com, c@site.com"
        )
        assert built["bcc"] == ["c@site.com"]

    def test_cc_without_a_to_is_still_recorded(self):
        """A form can be configured to Cc only. Dropping it would report the
        form as having no destination at all."""
        assert build_recipients(cc="watch@site.com")["cc"] == ["watch@site.com"]


class TestComparison:
    def test_the_same_set_in_a_different_order_is_equal(self):
        """Plugins reorder their own notification lists; that is not a change."""
        a = build_recipients(to="a@site.com, b@site.com")
        b = build_recipients(to="b@site.com, a@site.com")
        assert recipients_equal(a, b)

    def test_a_different_address_is_not_equal(self):
        assert not recipients_equal(
            build_recipients(to="a@site.com"), build_recipients(to="c@site.com")
        )

    def test_moving_an_address_from_to_to_cc_is_a_change(self):
        """It stops being a destination and becomes a copy — worth telling the
        team about."""
        assert not recipients_equal(
            build_recipients(to="a@site.com"), build_recipients(cc="a@site.com")
        )

    def test_an_added_bcc_is_a_change(self):
        assert not recipients_equal(
            build_recipients(to="a@site.com"),
            build_recipients(to="a@site.com", bcc="silent@site.com"),
        )

    def test_a_legacy_dict_missing_keys_compares_as_empty(self):
        """Rows written before this shape existed, and hand-edited data."""
        assert recipients_equal({}, EMPTY_RECIPIENTS)
        assert recipients_equal({"to": []}, EMPTY_RECIPIENTS)
        assert not recipients_equal({"to": ["a@site.com"]}, EMPTY_RECIPIENTS)


class TestAccessors:
    def test_all_recipients_flattens_in_to_cc_bcc_order(self):
        built = build_recipients(to="a@site.com", cc="b@site.com", bcc="c@site.com")
        assert all_recipients(built) == ["a@site.com", "b@site.com", "c@site.com"]

    def test_primary_is_the_first_to(self):
        assert primary_recipient(build_recipients(to="a@site.com, b@site.com")) == "a@site.com"

    def test_primary_falls_back_to_the_first_cc(self):
        assert primary_recipient(build_recipients(cc="b@site.com")) == "b@site.com"

    def test_primary_of_nothing_is_the_empty_string(self):
        assert primary_recipient(EMPTY_RECIPIENTS) == ""
        assert primary_recipient({}) == ""
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/scripts/test_recipients.py -q`
Expected: collection error — `ModuleNotFoundError: No module named 'apps.scripts.recipients'`

- [ ] **Step 3: Write the implementation**

Create `apps/scripts/recipients.py`:

```python
"""The `{to, cc, bcc}` shape a detected form's destinations are stored in.

Pure functions, no DB access, so the ingest task, the server-side scan and the
WP Connect fetch can all write the same shape without duplicating the parsing.

Kept out of `normalize.py`, which is about URL and script *identity*. A recipient
list is a different concern with different rules, and `normalize_recipient_email`
there deliberately rejects a comma-joined value — one address or nothing. That is
the right answer for one field and the wrong one for a list, which is why
`normalize_recipient_list` splits first and normalizes each part.
"""
from __future__ import annotations

from apps.scripts.normalize import normalize_recipient_email

#: A form with more than this many addresses in one kind is misconfigured or
#: hostile; the cap keeps one bad plugin value out of every row and payload.
MAX_RECIPIENTS_PER_KIND = 20

_KINDS = ("to", "cc", "bcc")

#: The shape of a form with no known destination. A fresh dict every read —
#: a module-level constant would be mutated by callers through its lists.
EMPTY_RECIPIENTS: dict = {"to": [], "cc": [], "bcc": []}


def normalize_recipient_list(value) -> list[str]:
    """Every valid address in `value`, normalized, deduped, in order.

    Accepts what each source actually produces: a delimited string from page
    markup and the server-side scan, a JSON array from the WP Connect route.
    Junk entries are dropped rather than rejecting the whole list — one
    unparseable address in an Elementor "To" must not lose the others.
    """
    if not value:
        return []

    parts: list[str] = []
    if isinstance(value, (list, tuple)):
        for item in value:
            parts.extend(str(item).replace(";", ",").split(","))
    else:
        parts.extend(str(value).replace(";", ",").split(","))

    out: list[str] = []
    for part in parts:
        email = normalize_recipient_email(part)
        if email and email not in out:
            out.append(email)
        if len(out) >= MAX_RECIPIENTS_PER_KIND:
            break
    return out


def build_recipients(to=None, cc=None, bcc=None) -> dict:
    """The canonical dict, with all three keys always present.

    An address is listed once, under the strongest kind it appears in: a To is
    also a Cc on plenty of real forms, and showing it twice reads as two
    destinations rather than one.
    """
    to_list = normalize_recipient_list(to)
    cc_list = [e for e in normalize_recipient_list(cc) if e not in to_list]
    seen = set(to_list) | set(cc_list)
    bcc_list = [e for e in normalize_recipient_list(bcc) if e not in seen]
    return {"to": to_list, "cc": cc_list, "bcc": bcc_list}


def _kind(recipients, kind: str) -> list[str]:
    """One kind out of a possibly-partial dict.

    Rows predating this shape, and anything hand-edited, can be missing keys or
    not be a dict at all; every reader goes through here so none of them has to
    care.
    """
    if not isinstance(recipients, dict):
        return []
    value = recipients.get(kind)
    return [str(e) for e in value] if isinstance(value, (list, tuple)) else []


def recipients_equal(a, b) -> bool:
    """Whether two recipient dicts mean the same thing.

    Order-insensitive within a kind: plugins reorder their own notification
    lists, and re-announcing that as a change would cry wolf. Kind-sensitive
    across them: an address moved from To to Bcc has stopped being a visible
    destination, which is exactly the sort of edit the team wants to hear about.
    """
    return all(set(_kind(a, k)) == set(_kind(b, k)) for k in _KINDS)


def all_recipients(recipients) -> list[str]:
    """Every address, To then Cc then Bcc."""
    out: list[str] = []
    for kind in _KINDS:
        for email in _kind(recipients, kind):
            if email not in out:
                out.append(email)
    return out


def primary_recipient(recipients) -> str:
    """The one address to show when there is only room for one.

    Falls back to a Cc, because a Cc-only form does have a destination and
    reporting "" for it would read as "nobody receives this".
    """
    for kind in _KINDS:
        values = _kind(recipients, kind)
        if values:
            return values[0]
    return ""
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/scripts/test_recipients.py -q`
Expected: PASS (30 tests)

- [ ] **Step 5: Commit**

```bash
git add apps/scripts/recipients.py tests/scripts/test_recipients.py
git commit -m "feat(forms): a to/cc/bcc shape for a form's destinations"
```

---

## Task 2: Model field and migration

**Files:**
- Modify: `apps/scripts/models.py` (the `recipient_email` field, ~line 262)
- Create: `apps/scripts/migrations/0026_detectedform_recipients.py`
- Test: `tests/scripts/test_recipients_migration.py`

**Interfaces:**
- Consumes: nothing from Task 1 at runtime (the backfill copies a value that is already normalized).
- Produces: `DetectedForm.recipients` (JSONField, default dict), backfilled from `recipient_email`. **`recipient_email` stays as a column** — deprecated, still populated by the current writers until Task 3 moves them, and dropped only in Task 8.

> **Why the column is not dropped here.** Dropping it in the same migration would break every reader in the same commit, leaving the suite red until Task 5 and giving a reviewer nothing they could accept or reject on its own. It is also the riskier migration: additive-then-drop can be rolled back without data loss, and lets the previous release's code keep running against the new schema if the deploy has to be reverted.

- [ ] **Step 1: Write the failing migration test**

Create `tests/scripts/test_recipients_migration.py`:

```python
"""The recipient_email → recipients migration must not lose an address."""

import pytest
from django.db.migrations.executor import MigrationExecutor
from django.db import connection


@pytest.mark.django_db(transaction=True)
class TestRecipientsBackfill:
    def test_an_existing_address_becomes_a_to_list(self):
        """Rows written before this migration hold one address in a CharField.

        Dropping the column without carrying the value over would silently
        empty the Goes to column for every form Digivault had already learned.
        """
        executor = MigrationExecutor(connection)
        app = "scripts"

        # Rewind to just before the new migration.
        executor.migrate([(app, "0025_detectedform_recipient_source")])
        old = executor.loader.project_state(
            [(app, "0025_detectedform_recipient_source")]
        ).apps

        Team = old.get_model("accounts", "Team")
        Website = old.get_model("websites", "Website")
        DetectedForm = old.get_model(app, "DetectedForm")

        team = Team.objects.create(name="Backfill Team")
        website = Website.objects.create(team=team, name="S", domain="backfill.test")
        with_email = DetectedForm.objects.create(
            website=website, page_url="https://backfill.test/a",
            fingerprint="f1", recipient_email="info@site.com",
            recipient_source="page", fields=[],
        )
        without = DetectedForm.objects.create(
            website=website, page_url="https://backfill.test/b",
            fingerprint="f2", recipient_email="", fields=[],
        )

        # Apply the new migration.
        executor = MigrationExecutor(connection)
        executor.migrate([(app, "0026_detectedform_recipients")])
        new = executor.loader.project_state(
            [(app, "0026_detectedform_recipients")]
        ).apps
        Migrated = new.get_model(app, "DetectedForm")

        assert Migrated.objects.get(pk=with_email.pk).recipients == {
            "to": ["info@site.com"], "cc": [], "bcc": [],
        }
        assert Migrated.objects.get(pk=without.pk).recipients == {
            "to": [], "cc": [], "bcc": [],
        }
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/scripts/test_recipients_migration.py -q`
Expected: FAIL — `NodeNotFoundError` / `KeyError` for `0026_detectedform_recipients`

- [ ] **Step 3: Change the model**

In `apps/scripts/models.py`, add the new field **above** `recipient_email`, and mark the old one deprecated (keep `recipient_source` exactly as it is):

```python
    # Where this form's submissions are configured to go:
    # {"to": [...], "cc": [...], "bcc": [...]}. Read from form *configuration*
    # only — a mailto: action, recipient data- attributes, hidden input values,
    # or the site's own form plugin over WP Connect — never from what a visitor
    # types. Empty lists when the destination is configured server-side and no
    # WP Connect snippet has reported it.
    #
    # A dict rather than a single address because real forms have several: an
    # Elementor "To" holding "sales@x.com, dev@x.com" used to store nothing at
    # all, because a comma-joined value is not one valid address.
    recipients = models.JSONField(default=dict, blank=True)
    # Deprecated, superseded by `recipients` above. Still written by the current
    # writers until they move over, and dropped once a release has run on the
    # new field. Read through `primary_recipient(form.recipients)`, never here.
    recipient_email = models.CharField(max_length=254, blank=True, default="")
```

- [ ] **Step 4: Write the migration**

Create `apps/scripts/migrations/0026_detectedform_recipients.py`:

```python
"""recipient_email (one address) → recipients ({to, cc, bcc})."""

from django.db import migrations, models


def to_recipients(apps, schema_editor):
    """Carry each stored address into the To list of the new shape.

    Values written by earlier versions passed `normalize_recipient_email`, so
    each is already a single lowercase address or "". No re-parsing needed, and
    none is a comma-joined list — that function rejected those outright, which
    is the bug this shape fixes.
    """
    DetectedForm = apps.get_model("scripts", "DetectedForm")
    for form in DetectedForm.objects.all().iterator():
        email = (form.recipient_email or "").strip()
        form.recipients = {"to": [email] if email else [], "cc": [], "bcc": []}
        form.save(update_fields=["recipients"])


def to_recipient_email(apps, schema_editor):
    """Reverse: keep the first To so a rollback isn't a data loss."""
    DetectedForm = apps.get_model("scripts", "DetectedForm")
    for form in DetectedForm.objects.all().iterator():
        to = (form.recipients or {}).get("to") or []
        form.recipient_email = to[0][:254] if to else ""
        form.save(update_fields=["recipient_email"])


class Migration(migrations.Migration):
    dependencies = [
        ("scripts", "0025_detectedform_recipient_source"),
    ]

    # Additive only. `recipient_email` is dropped in a later migration, once a
    # release has run against `recipients` — so this one can be reverted, and the
    # previous release's code still works against the new schema.
    operations = [
        migrations.AddField(
            model_name="detectedform",
            name="recipients",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.RunPython(to_recipients, to_recipient_email),
    ]
```

- [ ] **Step 5: Run the migration test and confirm nothing else broke**

Run: `.venv\Scripts\python.exe -m pytest tests/scripts/test_recipients_migration.py -q --create-db`
Expected: PASS

Run: `.venv\Scripts\python.exe -m pytest tests/scripts tests/websites -q`
Expected: PASS — the migration is additive, so every existing reader of `recipient_email` still works. If anything here is red, the model or the migration is wrong; do not proceed to Task 3 on a red tree.

- [ ] **Step 6: Confirm no stray model drift**

Run: `.venv\Scripts\python.exe manage.py makemigrations --check --dry-run`
Expected: "No changes detected". If it wants a migration, the model and the hand-written migration disagree — fix the migration, don't generate a second one.

- [ ] **Step 7: Commit**

```bash
git add apps/scripts/models.py apps/scripts/migrations/0026_detectedform_recipients.py tests/scripts/test_recipients_migration.py
git commit -m "feat(forms): store a form's recipients as to/cc/bcc lists"
```

---

## Task 3: Ingest and scan write the new shape

**Files:**
- Modify: `apps/scripts/serializers.py` (`IngestFormSerializer` ~line 42, `DetectedFormSerializer` ~line 170)
- Modify: `apps/scripts/tasks.py` (`_upsert_form` / `_apply_page_recipient`, ~lines 496-550)
- Modify: `apps/scripts/views.py:153` (ingest payload passthrough)
- Modify: `apps/websites/views.py:179-230` (server-side scan extraction)
- Modify: `apps/scripts/snippet.js` (`detectRecipientEmail`, ~lines 145-215)
- Test: `tests/scripts/test_form_detection.py`, `tests/websites/test_scan_forms.py`

**Interfaces:**
- Consumes: `build_recipients`, `recipients_equal`, `primary_recipient` (Task 1); `DetectedForm.recipients` (Task 2).
- Produces:
  - Ingest payload gains `recipients: {"to": [...], "cc": [...], "bcc": [...]}`; `recipient_email` is still accepted as a legacy string so a stale cached snippet keeps working.
  - `_apply_page_recipients(form, payload: dict) -> None` replaces `_apply_page_recipient`.
  - `DetectedFormSerializer` emits `recipients` **and** a read-only `recipient_email` derived from it.
  - After this task and Task 4, **nothing writes the `recipient_email` column.** It still exists, holding the pre-migration value, and Task 8 drops it.

- [ ] **Step 1: Write the failing tests**

Add to `tests/scripts/test_form_detection.py`:

```python
class TestRecipientLists:
    def test_a_comma_separated_to_stores_every_address(self, website):
        """The bug that started this: two addresses in one To stored nothing."""
        _upsert_form(website, PAGE, {
            "form_id": "multi", "detection_type": "native",
            "fields": [{"name": "email"}],
            "recipients": {"to": "sales@site.com, dev@site.com"},
        })
        form = DetectedForm.objects.get(website=website, form_id="multi")
        assert form.recipients["to"] == ["sales@site.com", "dev@site.com"]

    def test_cc_and_bcc_are_stored_separately(self, website):
        _upsert_form(website, PAGE, {
            "form_id": "copies", "detection_type": "native",
            "fields": [{"name": "email"}],
            "recipients": {
                "to": "lead@site.com", "cc": "manager@site.com",
                "bcc": "archive@site.com",
            },
        })
        form = DetectedForm.objects.get(website=website, form_id="copies")
        assert form.recipients == {
            "to": ["lead@site.com"], "cc": ["manager@site.com"],
            "bcc": ["archive@site.com"],
        }

    def test_a_legacy_recipient_email_payload_still_works(self, website):
        """The snippet is cached for 5 minutes and pasted copies live longer;
        a browser running yesterday's snippet must not lose its recipient."""
        _upsert_form(website, PAGE, {
            "form_id": "legacy", "detection_type": "native",
            "fields": [{"name": "email"}], "recipient_email": "Info@Site.com",
        })
        form = DetectedForm.objects.get(website=website, form_id="legacy")
        assert form.recipients["to"] == ["info@site.com"]

    def test_an_empty_reading_does_not_clear_stored_recipients(self, website):
        payload = {
            "form_id": "keep", "detection_type": "native",
            "fields": [{"name": "email"}],
            "recipients": {"to": "info@site.com"},
        }
        _upsert_form(website, PAGE, payload)
        _upsert_form(website, PAGE, {**payload, "recipients": {}})
        form = DetectedForm.objects.get(website=website, form_id="keep")
        assert form.recipients["to"] == ["info@site.com"]

    def test_a_junk_address_does_not_400_the_payload(self, website):
        _upsert_form(website, PAGE, {
            "form_id": "junk", "detection_type": "native",
            "fields": [{"name": "email"}],
            "recipients": {"to": "not-an-email"},
        })
        form = DetectedForm.objects.get(website=website, form_id="junk")
        assert form.recipients == {"to": [], "cc": [], "bcc": []}
```

Add to `tests/websites/test_scan_forms.py`:

```python
    def test_mailto_action_yields_to_cc_and_bcc(self):
        html = (
            '<form action="mailto:a@example.com,b@example.com'
            '?cc=c@example.com&amp;bcc=d@example.com">'
            '<input name="name"><button type="submit">Go</button></form>'
        )
        forms = _extract_forms(html, "https://example.com/")
        assert forms[0]["recipients"] == {
            "to": ["a@example.com", "b@example.com"],
            "cc": ["c@example.com"],
            "bcc": ["d@example.com"],
        }

    def test_a_mailto_without_a_query_still_yields_to(self):
        html = (
            '<form action="mailto:info@example.com">'
            '<input name="name"><button type="submit">Go</button></form>'
        )
        forms = _extract_forms(html, "https://example.com/")
        assert forms[0]["recipients"]["to"] == ["info@example.com"]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/scripts/test_form_detection.py::TestRecipientLists tests/websites/test_scan_forms.py -q`
Expected: FAIL — `KeyError: 'recipients'` / the stored dict is empty

- [ ] **Step 3: Update the ingest serializers**

In `apps/scripts/serializers.py`, add to `IngestFormSerializer` (keep `recipient_email` — it is the legacy path):

```python
class IngestRecipientsSerializer(serializers.Serializer):
    """Where a form delivers, as the snippet read it.

    Every field is a free string: the snippet sends a comma-joined list and
    validation happens in the upsert. A malformed address must not 400 the
    payload, which would drop the scripts posted alongside it.
    """

    to = serializers.CharField(max_length=2048, allow_blank=True, default="")
    cc = serializers.CharField(max_length=2048, allow_blank=True, default="")
    bcc = serializers.CharField(max_length=2048, allow_blank=True, default="")
```

and in `IngestFormSerializer`, directly under the existing `recipient_email` field:

```python
    # Superseded by `recipients` below, kept because the snippet is served with
    # Cache-Control: max-age=300 and pasted copies live far longer than that —
    # a browser running an older snippet must not lose its recipient.
    recipient_email = serializers.CharField(
        max_length=254, allow_blank=True, default=""
    )
    recipients = IngestRecipientsSerializer(required=False)
```

In the output serializer (~line 170), swap the field list and add the derived key:

```python
    # Derived, read-only, and deliberately still here: the frontend deploys
    # separately from the backend (host-pm2 vs Docker), so dropping the key
    # outright would blank the Goes to column until the frontend caught up.
    recipient_email = serializers.SerializerMethodField()

    class Meta:
        model = DetectedForm
        fields = (
            "id", "page_url", "form_id", "form_name",
            "form_action", "form_method", "fields",
            "detection_type", "provider", "recipients", "recipient_email",
            "recipient_source", "is_managed",
            "submission_count", "last_submission_at",
            "first_seen_at", "last_seen_at",
        )
        read_only_fields = fields

    def get_recipient_email(self, obj) -> str:
        from apps.scripts.recipients import primary_recipient

        return primary_recipient(obj.recipients)
```

- [ ] **Step 4: Update the upsert**

In `apps/scripts/tasks.py`, replace `_apply_page_recipient` with:

```python
def _apply_page_recipients(form: DetectedForm, form_data: dict) -> None:
    """Record the destinations the snippet read out of the page markup.

    Deliberately not part of the upsert's `defaults`, for two reasons.

    A WordPress-reported set is the form's actual configuration, while the
    markup is only a proxy for it — so an ingest must never overwrite one.
    Written through `defaults`, every pageview wiped what the WP Connect route
    had filled in (page-invisible for Elementor/CF7 forms, so the markup reads
    nothing).

    And an empty reading does not clear a stored set. A form is observed several
    times per page load, and one observation missing a `mailto:` action is not
    evidence the action is gone — the same reasoning the diff window applies to
    scripts.
    """
    raw = form_data.get("recipients") or {}
    recipients = build_recipients(
        to=raw.get("to") or form_data.get("recipient_email", ""),
        cc=raw.get("cc"),
        bcc=raw.get("bcc"),
    )
    if not any(recipients.values()):
        return
    if form.recipient_source == DetectedForm.RecipientSource.WORDPRESS:
        return
    if (
        recipients_equal(form.recipients, recipients)
        and form.recipient_source == DetectedForm.RecipientSource.PAGE
    ):
        return
    form.recipients = recipients
    form.recipient_source = DetectedForm.RecipientSource.PAGE
    form.save(update_fields=["recipients", "recipient_source", "updated_at"])
```

Update the import at the top of the file and the call in `_upsert_form`:

```python
from apps.scripts.recipients import build_recipients, recipients_equal
```

```python
    _apply_page_recipients(form, form_data)
```

- [ ] **Step 5: Pass the field through ingest**

In `apps/scripts/views.py`, in the `forms` list comprehension (~line 153), replace the `recipient_email` line with both keys:

```python
                        "recipient_email": f.get("recipient_email", ""),
                        "recipients": f.get("recipients") or {},
```

- [ ] **Step 6: Update the server-side scan**

In `apps/websites/views.py`, replace the recipient extraction. The hidden-input loop keeps a Cc/Bcc-aware collector:

```python
        fields: list[dict] = []
        hidden_to: list[str] = []
        hidden_cc: list[str] = []
        hidden_bcc: list[str] = []
```

Inside the hidden-input branch, replace the single-value capture:

```python
            if tag == "input" and ftype == "hidden":
                hidden_name = (field_attrs.get("name") or "").lower()
                hidden_value = field_attrs.get("value", "")
                if "bcc" in hidden_name:
                    hidden_bcc.append(hidden_value)
                elif "cc" in hidden_name:
                    hidden_cc.append(hidden_value)
                else:
                    hidden_to.append(hidden_value)
                continue
```

Replace the `mailto:` block and the appended dict:

```python
        action = form_attrs.get("action", "")
        mailto_to, mailto_cc, mailto_bcc = _parse_mailto(action)
        forms.append({
            "form_id": form_attrs.get("id", ""),
            "form_name": form_attrs.get("name", ""),
            "form_action": action,
            "form_method": (form_attrs.get("method") or "post").lower(),
            "detection_type": "native",
            "provider": "",
            # A mailto: action is the form's stated destination and outranks a
            # hidden field, which is only a guess from an input's name.
            "recipients": build_recipients(
                to=mailto_to or hidden_to,
                cc=mailto_cc or hidden_cc,
                bcc=mailto_bcc or hidden_bcc,
            ),
            "fields": fields[:200],
        })
```

Add the helper above `_extract_forms` in the same file:

```python
def _parse_mailto(action: str) -> tuple[list[str], list[str], list[str]]:
    """To, Cc and Bcc out of a `mailto:` action.

    `mailto:a@x.com,b@x.com?cc=c@x.com&bcc=d@x.com` is a fully specified
    destination — the whole address list and both copy headers. Earlier code
    split on "?" and took only the first address before the first comma, so a
    form addressed to two people reported one and its Cc not at all.
    """
    if not re.match(r"^mailto:", action, re.IGNORECASE):
        return [], [], []
    body = action[len("mailto:"):]
    path, _, query = body.partition("?")
    params = parse_qs(unescape(query))
    return (
        [unescape(path)],
        params.get("cc", []),
        params.get("bcc", []),
    )
```

with these imports at the top of `apps/websites/views.py`:

```python
from html import unescape
from urllib.parse import parse_qs

from apps.scripts.recipients import build_recipients
```

- [ ] **Step 7: Update the snippet**

In `apps/scripts/snippet.js`, replace `detectRecipientEmail` with a Cc/Bcc-aware version and add the Bcc name pattern beside the existing `RECIPIENT_NAME`:

```javascript
  var CC_NAME = /(^cc$|_cc$|carbon)/i;
  var BCC_NAME = /(^bcc$|_bcc$|blind)/i;

  // Where a form's submissions are configured to go, as {to, cc, bcc} of
  // comma-joined strings. Reads form *configuration* only — the mailto: action
  // (including its ?cc= and ?bcc= parameters), data-* attributes, and hidden
  // input values, which carry server-side config and never what a visitor
  // types. A form whose destination lives server-side (Contact Form 7,
  // Formspree, Netlify) is invisible here and yields empty strings.
  function detectRecipients(formEl) {
    var out = { to: '', cc: '', bcc: '' };
    var action = formEl.getAttribute ? formEl.getAttribute('action') || '' : '';

    if (/^mailto:/i.test(action)) {
      var body = action.replace(/^mailto:/i, '');
      var q = body.indexOf('?');
      out.to = q === -1 ? body : body.slice(0, q);
      if (q !== -1) {
        var pairs = body.slice(q + 1).split('&');
        for (var p = 0; p < pairs.length; p++) {
          var kv = pairs[p].split('=');
          var key = decodeURIComponent(kv[0] || '').toLowerCase();
          var val = decodeURIComponent((kv[1] || '').replace(/\+/g, ' '));
          if (key === 'cc') out.cc = out.cc ? out.cc + ',' + val : val;
          if (key === 'bcc') out.bcc = out.bcc ? out.bcc + ',' + val : val;
        }
      }
    }

    if (formEl.getAttribute) {
      for (var a = 0; a < RECIPIENT_ATTRS.length; a++) {
        var v = formEl.getAttribute(RECIPIENT_ATTRS[a]);
        if (v && isEmailAddress(v) && !out.to) out.to = v;
      }
    }

    var hidden = formEl.querySelectorAll ? formEl.querySelectorAll('input[type="hidden"]') : [];
    var fallback = '';
    for (var h = 0; h < hidden.length; h++) {
      var value = (hidden[h].value || '').trim();
      if (!isEmailAddress(value)) continue;
      var name = (hidden[h].name || '').toLowerCase();
      if (BCC_NAME.test(name)) { out.bcc = out.bcc ? out.bcc + ',' + value : value; continue; }
      if (CC_NAME.test(name)) { out.cc = out.cc ? out.cc + ',' + value : value; continue; }
      if (RECIPIENT_NAME.test(name)) { out.to = out.to ? out.to + ',' + value : value; continue; }
      if (!fallback) fallback = value;
    }
    if (!out.to && fallback) out.to = fallback;

    return out;
  }
```

In both descriptor builders (the native branch ~line 211 and the div branch ~line 247), replace the `recipient_email` key:

```javascript
        recipients: detectRecipients(f),
```

```javascript
        recipients: detectRecipients(grp.container),
```

Bump the snippet version constant in the same file so a stale cache is identifiable in ingest records.

- [ ] **Step 8: Run the affected suites**

Run: `.venv\Scripts\python.exe -m pytest tests/scripts tests/websites -q --create-db`
Expected: PASS. Existing assertions on `form.recipient_email` must be rewritten to read `form.recipients["to"]` — that is the point of the change, not a regression to work around.

- [ ] **Step 9: Commit**

```bash
git add apps/scripts/serializers.py apps/scripts/tasks.py apps/scripts/views.py apps/scripts/snippet.js apps/websites/views.py tests/
git commit -m "feat(forms): read every To, plus Cc and Bcc, from the page"
```

---

## Task 4: WP Connect reports Cc and Bcc

**Files:**
- Modify: `apps/websites/wp_sso_snippet.py` (the four `dvc_forms_*` readers)
- Modify: `apps/websites/wp_forms.py` (`apply_recipients`, ~lines 145-195)
- Test: `tests/websites/test_wp_form_recipients.py`

**Interfaces:**
- Consumes: `build_recipients`, `recipients_equal` (Task 1); `DetectedForm.recipients` (Task 2).
- Produces: each `/forms` entry gains `"cc"` and `"bcc"` arrays beside `"recipients"`, which is **renamed to `"to"`**. `apply_recipients` writes the full dict.

> **Route shape.** The entry becomes
> `{"plugin": ..., "name": ..., "id_prefix": ..., "to": [...], "cc": [...], "bcc": [...]}`.
> `apply_recipients` must accept `"recipients"` as an alias for `"to"`, because a
> site pasted between the previous commit and this one answers with the old key.

- [ ] **Step 1: Write the failing tests**

Add to `tests/websites/test_wp_form_recipients.py`:

```python
class TestReportedCopies:
    def test_cc_and_bcc_are_stored(self, website):
        form = _elementor_form(website)
        apply_recipients(website, [{
            "plugin": "elementor", "name": "New Form",
            "to": ["website@digilatics.com"],
            "cc": ["manager@digilatics.com"],
            "bcc": ["archive@digilatics.com"],
        }])
        form.refresh_from_db()
        assert form.recipients == {
            "to": ["website@digilatics.com"],
            "cc": ["manager@digilatics.com"],
            "bcc": ["archive@digilatics.com"],
        }

    def test_every_to_address_is_stored_not_just_the_first(self, website):
        form = _elementor_form(website)
        apply_recipients(website, [{
            "name": "New Form", "to": ["first@site.com", "second@site.com"],
        }])
        form.refresh_from_db()
        assert form.recipients["to"] == ["first@site.com", "second@site.com"]

    def test_the_old_recipients_key_is_still_accepted(self, website):
        """A site pasted with the previous snippet answers with `recipients`."""
        form = _elementor_form(website)
        assert apply_recipients(website, [{
            "name": "New Form", "recipients": ["website@digilatics.com"],
        }]) == 1
        form.refresh_from_db()
        assert form.recipients["to"] == ["website@digilatics.com"]

    def test_a_reordered_report_is_not_a_write(self, website):
        _elementor_form(website)
        first = {"name": "New Form", "to": ["a@site.com", "b@site.com"]}
        assert apply_recipients(website, [first]) == 1
        assert apply_recipients(
            website, [{"name": "New Form", "to": ["b@site.com", "a@site.com"]}]
        ) == 0
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/websites/test_wp_form_recipients.py::TestReportedCopies -q`
Expected: FAIL — the stored dict has empty `cc`/`bcc`, and only the first To

- [ ] **Step 3: Update the PHP readers**

In `apps/websites/wp_sso_snippet.py`, add a helper beside `dvc_split_emails` and change each reader's returned array.

```php
/**
 * The first non-empty value among several candidate setting keys.
 *
 * Plugin setting names are not documented API and differ between versions —
 * Elementor's Cc field has been seen as both `email_cc` and `email_to_cc`.
 * Reading a candidate list costs nothing and degrades to "no Cc found" rather
 * than to a wrong answer.
 */
if ( ! function_exists( 'dvc_first_setting' ) ) {
	function dvc_first_setting( $settings, $keys ) {
		foreach ( (array) $keys as $key ) {
			if ( isset( $settings[ $key ] ) && '' !== trim( (string) $settings[ $key ] ) ) {
				return $settings[ $key ];
			}
		}
		return '';
	}
}

/** Cc/Bcc out of an RFC-822 header blob, as Contact Form 7 stores them. */
if ( ! function_exists( 'dvc_headers_copies' ) ) {
	function dvc_headers_copies( $headers ) {
		$out = array( 'cc' => array(), 'bcc' => array() );
		foreach ( preg_split( '/\r\n|\r|\n/', (string) $headers ) as $line ) {
			if ( preg_match( '/^\s*(bcc|cc)\s*:\s*(.+)$/i', $line, $m ) ) {
				$kind = strtolower( $m[1] );
				$out[ $kind ] = array_merge( $out[ $kind ], dvc_split_emails( $m[2] ) );
			}
		}
		return $out;
	}
}
```

In `dvc_walk_elementor`, replace the entry it pushes:

```php
					if ( ! empty( $to ) ) {
						$out[] = array(
							'plugin'    => 'elementor',
							'name'      => isset( $s['form_name'] ) ? (string) $s['form_name'] : '',
							'id_prefix' => '',
							'to'        => $to,
							'cc'        => dvc_split_emails( dvc_first_setting( $s, array( 'email_cc', 'email_to_cc' ) ) ),
							'bcc'       => dvc_split_emails( dvc_first_setting( $s, array( 'email_bcc', 'email_to_bcc' ) ) ),
						);
					}
```

In `dvc_forms_cf7`, read the headers alongside the recipient:

```php
			$mail = get_post_meta( $post->ID, '_mail', true );
			$to   = is_array( $mail ) && isset( $mail['recipient'] )
				? dvc_split_emails( $mail['recipient'] )
				: array();
			$copies = is_array( $mail ) && isset( $mail['additional_headers'] )
				? dvc_headers_copies( $mail['additional_headers'] )
				: array( 'cc' => array(), 'bcc' => array() );
			if ( ! empty( $to ) ) {
				$out[] = array(
					'plugin'    => 'contact-form-7',
					'name'      => $post->post_title,
					'id_prefix' => 'wpcf7-f' . $post->ID . '-',
					'to'        => $to,
					'cc'        => $copies['cc'],
					'bcc'       => $copies['bcc'],
				);
			}
```

In `dvc_forms_wpforms`, collect copies per notification:

```php
			$to  = array();
			$cc  = array();
			$bcc = array();
			foreach ( $notifications as $n ) {
				if ( ! is_array( $n ) ) {
					continue;
				}
				if ( isset( $n['email'] ) ) {
					$to = array_merge( $to, dvc_split_emails( $n['email'] ) );
				}
				$cc  = array_merge( $cc, dvc_split_emails( dvc_first_setting( $n, array( 'carboncopy', 'cc' ) ) ) );
				$bcc = array_merge( $bcc, dvc_split_emails( dvc_first_setting( $n, array( 'blindcarboncopy', 'bcc' ) ) ) );
			}
			$to  = array_values( array_unique( $to ) );
			$cc  = array_values( array_unique( $cc ) );
			$bcc = array_values( array_unique( $bcc ) );
			if ( ! empty( $to ) ) {
				$out[] = array(
					'plugin'    => 'wpforms',
					'name'      => $post->post_title,
					'id_prefix' => 'wpforms-form-' . $post->ID,
					'to'        => $to,
					'cc'        => $cc,
					'bcc'       => $bcc,
				);
			}
```

In `dvc_forms_gravity`, the same, from each notification's `cc`/`bcc`:

```php
			$to  = array();
			$cc  = array();
			$bcc = array();
			foreach ( (array) ( isset( $form['notifications'] ) ? $form['notifications'] : array() ) as $n ) {
				if ( ! is_array( $n ) ) {
					continue;
				}
				// A notification routed to a field carries the visitor's address,
				// not a destination the agency configured.
				if ( isset( $n['to'] ) && ( ! isset( $n['toType'] ) || 'email' === $n['toType'] ) ) {
					$to = array_merge( $to, dvc_split_emails( $n['to'] ) );
				}
				if ( isset( $n['cc'] ) ) {
					$cc = array_merge( $cc, dvc_split_emails( $n['cc'] ) );
				}
				if ( isset( $n['bcc'] ) ) {
					$bcc = array_merge( $bcc, dvc_split_emails( $n['bcc'] ) );
				}
			}
			$to  = array_values( array_unique( $to ) );
			$cc  = array_values( array_unique( $cc ) );
			$bcc = array_values( array_unique( $bcc ) );
			if ( ! empty( $to ) ) {
				$out[] = array(
					'plugin'    => 'gravity-forms',
					'name'      => isset( $form['title'] ) ? (string) $form['title'] : '',
					'id_prefix' => 'gform_' . $form['id'],
					'to'        => $to,
					'cc'        => $cc,
					'bcc'       => $bcc,
				);
			}
```

- [ ] **Step 4: Update `apply_recipients`**

In `apps/websites/wp_forms.py`, replace the body of the per-entry loop:

```python
def apply_recipients(website, entries: list[dict]) -> int:
    """Fill in `recipients` from what WordPress reported. Returns rows written."""
    from apps.scripts.models import DetectedForm
    from apps.scripts.recipients import build_recipients, recipients_equal

    forms = list(website.detected_forms.all())
    if not forms:
        return 0

    written = 0
    for entry in entries:
        # "recipients" is the pre-Cc/Bcc key name: a site pasted with the
        # previous snippet still answers with it.
        reported_to = entry.get("to")
        if reported_to is None:
            reported_to = entry.get("recipients")
        recipients = build_recipients(
            to=reported_to, cc=entry.get("cc"), bcc=entry.get("bcc")
        )
        if not any(recipients.values()):
            continue

        matched = _match(entry, forms)
        if not matched:
            logger.debug(
                "wp_forms: %s reported %s form %r with no detected row",
                website.domain, entry.get("plugin"), entry.get("name"),
            )
            continue

        for form in matched:
            if (
                recipients_equal(form.recipients, recipients)
                and form.recipient_source == DetectedForm.RecipientSource.WORDPRESS
            ):
                continue
            form.recipients = recipients
            form.recipient_source = DetectedForm.RecipientSource.WORDPRESS
            form.save(update_fields=["recipients", "recipient_source", "updated_at"])
            written += 1

    return written
```

Update the docstring at the top of the module and delete the "Only the first address is stored" note — it is no longer true.

- [ ] **Step 5: Run the tests**

Run: `.venv\Scripts\python.exe -m pytest tests/websites/test_wp_form_recipients.py -q`
Expected: PASS

- [ ] **Step 6: Syntax-check and exercise the PHP**

The snippet ships to client sites, so a syntax error is a site-wide fatal. Generate it and check:

```bash
.venv/Scripts/python.exe -c "import django,os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings.test'); django.setup(); from apps.websites.wp_sso_snippet import build_wp_sso_snippet; open('/tmp/dvc.php','w').write(build_wp_sso_snippet('test-secret'))"
php -l /tmp/dvc.php
```

Expected: "No syntax errors detected".

Then exercise the two new helpers against stubbed WordPress (`dvc_headers_copies` on a CF7-style blob, `dvc_first_setting` on a settings array with only the second candidate key present). The existing harness pattern — define `get_option`, `sanitize_email`, `is_email`, `add_action`, `register_rest_route` and friends, then `require` the generated file — is in the previous task's shell history; rebuild it in `/tmp`, do not add it to the repo.

- [ ] **Step 7: Commit**

```bash
git add apps/websites/wp_sso_snippet.py apps/websites/wp_forms.py tests/websites/test_wp_form_recipients.py
git commit -m "feat(forms): report Cc and Bcc from each WordPress form plugin"
```

---

## Task 5: Frontend shows To, Cc and Bcc

**Files:**
- Modify: `frontend/src/lib/api.ts` (`DetectedForm`, ~line 403)
- Modify: `frontend/src/lib/detected-forms.ts` (`FormRow`, `dedupeForms`)
- Modify: `frontend/src/components/forms-tab.tsx` (the "Goes to" cell, ~line 204)
- Modify: `frontend/src/components/form-detail-dialog.tsx` (`Destination`)

**Interfaces:**
- Consumes: the API's `recipients` object (Task 3).
- Produces: `FormRow.recipients: {to: string[]; cc: string[]; bcc: string[]}` merged across pages. `FormRow.recipient_emails` is **removed** — every consumer moves to `recipients.to`.

- [ ] **Step 1: Update the API type**

In `frontend/src/lib/api.ts`, replace the `recipient_email` line in `DetectedForm`:

```typescript
  /** Where this form delivers. Read from the page markup or reported by the
   *  site's own form plugin over WP Connect — see recipient_source. */
  recipients: { to: string[]; cc: string[]; bcc: string[] };
  /** Derived server-side from recipients.to[0]. Kept for compatibility with a
   *  frontend deployed ahead of the backend; prefer recipients. */
  recipient_email: string;
```

- [ ] **Step 2: Merge the shape across pages**

In `frontend/src/lib/detected-forms.ts`, replace the `recipient_emails` member of `FormRow` and its two merge sites:

```typescript
/** A form merged across every page it was found on. */
export type FormRow = DetectedForm & {
  pages: string[];
  /** Distinct destinations collected across the pages it appears on. */
  recipients: { to: string[]; cc: string[]; bcc: string[] };
};

/** Every address in one kind, tolerating a row written before the shape existed. */
function kind(f: DetectedForm, name: "to" | "cc" | "bcc"): string[] {
  const value = f.recipients?.[name];
  return Array.isArray(value) ? value : [];
}
```

In the `!existing` branch:

```typescript
      bySignature.set(sig, {
        ...f,
        pages: [f.page_url],
        recipients: {
          to: [...kind(f, "to")],
          cc: [...kind(f, "cc")],
          bcc: [...kind(f, "bcc")],
        },
      });
```

In the merge branch, replacing the `recipient_emails` block:

```typescript
      for (const name of ["to", "cc", "bcc"] as const) {
        for (const email of kind(f, name)) {
          if (!existing.recipients[name].includes(email)) {
            existing.recipients[name].push(email);
          }
        }
      }
```

Add a helper the table and dialog both use, beside the other shared row helpers:

```typescript
/** Every address a form delivers to, To first — what the "Goes to" column counts. */
export function destinationCount(f: FormRow): number {
  return f.recipients.to.length + f.recipients.cc.length + f.recipients.bcc.length;
}
```

- [ ] **Step 3: Update the table cell**

In `frontend/src/components/forms-tab.tsx`, the "Goes to" cell shows the first To and counts the rest, and the WP Connect prompt's condition moves to `destinationCount`:

```tsx
                <TableCell
                  className="font-mono text-xs text-muted-foreground max-w-[200px] truncate"
                  title={
                    destinationCount(form) > 0
                      ? [
                          ...form.recipients.to,
                          ...form.recipients.cc.map((e) => `${e} (Cc)`),
                          ...form.recipients.bcc.map((e) => `${e} (Bcc)`),
                        ].join("\n")
                      : embedded
                        ? "Handled by the form's provider — open Details"
                        : "No recipient in the page markup; set server-side — open Details"
                  }
                >
                  {destinationCount(form) > 0 ? (
                    <>
                      {form.recipients.to[0] ?? form.recipients.cc[0]}
                      {destinationCount(form) > 1 && (
                        <span className="ml-1 whitespace-nowrap font-sans">
                          +{destinationCount(form) - 1} more
                        </span>
                      )}
                    </>
                  ) : (
                    <span className="font-sans">{embedded ? "—" : "Server-side"}</span>
                  )}
                </TableCell>
```

and:

```tsx
      {isWordPress && managedForms.some((f) => destinationCount(f) === 0) && (
```

with `destinationCount` added to the import from `@/lib/detected-forms`.

- [ ] **Step 4: Update the dialog**

In `frontend/src/components/form-detail-dialog.tsx`, `Destination` lists each kind under its own label. Replace the `if (form.recipient_emails.length > 0)` branch's condition with `if (destinationCount(form) > 0)`, and its `<ul>` with:

```tsx
        {(["to", "cc", "bcc"] as const).map((kind) =>
          form.recipients[kind].length === 0 ? null : (
            <div key={kind} className="space-y-0.5">
              <p className="text-[11px] uppercase tracking-wide text-muted-foreground">
                {kind === "to" ? "To" : kind === "cc" ? "Cc" : "Bcc"}
              </p>
              <ul className="space-y-0.5">
                {form.recipients[kind].map((email) => (
                  <li key={email} className="font-mono text-xs break-all">
                    {email}
                  </li>
                ))}
              </ul>
            </div>
          )
        )}
```

Add a line to the WordPress-sourced explanation, since a Bcc is the one destination a client can add without anyone noticing:

```tsx
              Read from this site&apos;s WordPress form settings over WP Connect — the
              addresses the form plugin will actually send to, including copies.
```

- [ ] **Step 5: Verify the frontend**

```bash
cd frontend
npx tsc --noEmit
npm run lint
npm run build
```

Expected: `tsc` silent; `npm run lint` reports only the 5 pre-existing problems (`2fa/setup/page.tsx`, `logs/page.tsx`, `clients-client.tsx`, `reports-tab.tsx`, `theme-toggle.tsx`) and none in the files touched here; build compiles.

- [ ] **Step 6: Commit**

```bash
git add frontend/src
git commit -m "feat(forms): show every destination, with Cc and Bcc labelled"
```

---

## Task 6: Record a recipient change as a SiteEvent

**Files:**
- Create: `apps/scripts/recipient_changes.py`
- Modify: `apps/site_health/models.py` (`SiteEvent.EventType`, ~line 51)
- Create: `apps/site_health/migrations/0009_alter_siteevent_event_type.py`
- Modify: `apps/scripts/tasks.py` (`_apply_page_recipients` from Task 3)
- Modify: `apps/websites/wp_forms.py` (`apply_recipients` from Task 4)
- Test: `tests/scripts/test_recipient_changes.py`

**Interfaces:**
- Consumes: `recipients_equal`, `all_recipients` (Task 1); `DetectedForm.recipients`, `DetectedForm.recipient_source` (Task 2).
- Produces:
  - `describe_recipient_change(old: dict, new: dict) -> dict | None` — pure; `None` when there is nothing to announce. Returns `{"severity": str, "summary_verb": str, "added": [...], "removed": [...], "moved_to_bcc": [...]}`.
  - `record_recipient_change(form, *, old_recipients: dict, old_source: str, new_source: str) -> SiteEvent | None` — call **after** `form.recipients` has been assigned and saved.
  - `SiteEvent.EventType.FORM_RECIPIENTS_CHANGED = "form_recipients_changed"`.

> **Why a `SiteEvent` and not an `AlertRule` / `Notification`.** `AlertRule.change_types` speaks only `ScriptChange.ChangeType` values and `Notification.script_change` is a FK to `Script`-scoped changes, so `apps/alerts/` cannot represent a form event without schema work — and the team ClickUp channel does not read it anyway. The precedent to copy is [site_health/tasks.py:399-410](apps/site_health/tasks.py#L399-L410): create a `SiteEvent`, then call the ClickUp poster, with the cooldown owned by the caller. The `SiteEvent` also lands in the Change Log tab for free.

- [ ] **Step 1: Write the failing tests**

Create `tests/scripts/test_recipient_changes.py`:

```python
"""Deciding whether a recipient change is worth telling the team about."""

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.scripts.models import DetectedForm
from apps.scripts.recipients import build_recipients
from apps.scripts.recipient_changes import (
    describe_recipient_change,
    record_recipient_change,
)
from apps.site_health.models import SiteEvent
from apps.websites.models import Website

PAGE = "https://rc.test/contact"


@pytest.fixture
def website(db):
    owner = User.objects.create_user(email="rc_o@test.com", password="Pass123!")
    team = TeamService.create(name="RC Agency", owner=owner)
    return Website.objects.create(team=team, name="RC Site", domain="rc.test")


@pytest.fixture
def form(website):
    return DetectedForm.objects.create(
        website=website, page_url=PAGE, fingerprint="fp1",
        form_name="New Form", fields=[],
        recipients=build_recipients(to="old@site.com"),
        recipient_source=DetectedForm.RecipientSource.WORDPRESS,
    )


class TestDescribeRecipientChange:
    def test_an_identical_set_is_not_a_change(self):
        a = build_recipients(to="a@site.com")
        assert describe_recipient_change(a, build_recipients(to="a@site.com")) is None

    def test_a_reordered_set_is_not_a_change(self):
        assert describe_recipient_change(
            build_recipients(to="a@site.com, b@site.com"),
            build_recipients(to="b@site.com, a@site.com"),
        ) is None

    def test_first_discovery_is_not_a_change(self):
        """Empty → populated is detection catching up, not an edit to the form.

        Every form Digivault already knows about goes through this transition
        the first time WP Connect answers; announcing it would post once per
        form on the whole estate.
        """
        assert describe_recipient_change(
            build_recipients(), build_recipients(to="a@site.com")
        ) is None

    def test_a_replaced_address_is_a_warning(self):
        change = describe_recipient_change(
            build_recipients(to="old@site.com"), build_recipients(to="new@site.com")
        )
        assert change["severity"] == SiteEvent.Severity.WARNING
        assert change["added"] == ["new@site.com"]
        assert change["removed"] == ["old@site.com"]

    def test_losing_every_address_is_critical(self):
        """The form still exists and now delivers to nobody — the worst case,
        and silent from the visitor's side."""
        change = describe_recipient_change(
            build_recipients(to="lead@site.com"), build_recipients()
        )
        assert change["severity"] == SiteEvent.Severity.CRITICAL
        assert change["summary_verb"] == "no longer delivers to anyone"

    def test_an_added_bcc_is_reported_as_such(self):
        """The one destination a client can add that nobody else can see."""
        change = describe_recipient_change(
            build_recipients(to="lead@site.com"),
            build_recipients(to="lead@site.com", bcc="silent@elsewhere.com"),
        )
        assert change["severity"] == SiteEvent.Severity.WARNING
        assert change["added"] == ["silent@elsewhere.com"]
        assert change["moved_to_bcc"] == []

    def test_moving_a_to_into_bcc_is_flagged_as_a_move(self):
        """The address still receives mail, so it is neither added nor removed —
        but it has stopped being a visible destination."""
        change = describe_recipient_change(
            build_recipients(to="lead@site.com"), build_recipients(bcc="lead@site.com")
        )
        assert change["moved_to_bcc"] == ["lead@site.com"]
        assert change["severity"] == SiteEvent.Severity.WARNING

    def test_a_removed_cc_is_only_information(self):
        change = describe_recipient_change(
            build_recipients(to="lead@site.com", cc="watcher@site.com"),
            build_recipients(to="lead@site.com"),
        )
        assert change["severity"] == SiteEvent.Severity.INFO


@pytest.mark.django_db
class TestRecordRecipientChange:
    def test_a_change_within_one_source_is_recorded(self, form):
        form.recipients = build_recipients(to="new@site.com")
        form.save(update_fields=["recipients"])
        event = record_recipient_change(
            form,
            old_recipients=build_recipients(to="old@site.com"),
            old_source=DetectedForm.RecipientSource.WORDPRESS,
            new_source=DetectedForm.RecipientSource.WORDPRESS,
        )
        assert event is not None
        assert event.event_type == SiteEvent.EventType.FORM_RECIPIENTS_CHANGED
        assert event.website_id == form.website_id
        assert "New Form" in event.summary
        assert event.details["page_url"] == PAGE
        assert event.details["old"]["to"] == ["old@site.com"]
        assert event.details["new"]["to"] == ["new@site.com"]

    def test_a_source_upgrade_is_not_a_change(self, form):
        """page → wordpress reporting a different address is a better *read* of
        the same form, not an edit to it. Announcing it would fire for every
        form on the estate the first time WP Connect answers."""
        assert record_recipient_change(
            form,
            old_recipients=build_recipients(to="guessed@site.com"),
            old_source=DetectedForm.RecipientSource.PAGE,
            new_source=DetectedForm.RecipientSource.WORDPRESS,
        ) is None
        assert SiteEvent.objects.count() == 0

    def test_a_first_read_with_no_prior_source_is_not_a_change(self, form):
        assert record_recipient_change(
            form,
            old_recipients=build_recipients(),
            old_source="",
            new_source=DetectedForm.RecipientSource.WORDPRESS,
        ) is None

    def test_the_same_transition_is_suppressed_inside_the_cooldown(self, form):
        """A form flipping between two addresses must not post every night."""
        kwargs = dict(
            old_recipients=build_recipients(to="old@site.com"),
            old_source=DetectedForm.RecipientSource.WORDPRESS,
            new_source=DetectedForm.RecipientSource.WORDPRESS,
        )
        form.recipients = build_recipients(to="new@site.com")
        form.save(update_fields=["recipients"])
        assert record_recipient_change(form, **kwargs) is not None
        assert record_recipient_change(form, **kwargs) is None
        assert SiteEvent.objects.count() == 1

    def test_a_different_transition_is_not_suppressed(self, form):
        form.recipients = build_recipients(to="new@site.com")
        form.save(update_fields=["recipients"])
        record_recipient_change(
            form,
            old_recipients=build_recipients(to="old@site.com"),
            old_source=DetectedForm.RecipientSource.WORDPRESS,
            new_source=DetectedForm.RecipientSource.WORDPRESS,
        )
        form.recipients = build_recipients(to="third@site.com")
        form.save(update_fields=["recipients"])
        assert record_recipient_change(
            form,
            old_recipients=build_recipients(to="new@site.com"),
            old_source=DetectedForm.RecipientSource.WORDPRESS,
            new_source=DetectedForm.RecipientSource.WORDPRESS,
        ) is not None
        assert SiteEvent.objects.count() == 2

    def test_an_expired_cooldown_lets_the_same_transition_through(self, form):
        from datetime import timedelta

        kwargs = dict(
            old_recipients=build_recipients(to="old@site.com"),
            old_source=DetectedForm.RecipientSource.WORDPRESS,
            new_source=DetectedForm.RecipientSource.WORDPRESS,
        )
        form.recipients = build_recipients(to="new@site.com")
        form.save(update_fields=["recipients"])
        first = record_recipient_change(form, **kwargs)
        SiteEvent.objects.filter(pk=first.pk).update(
            occurred_at=timezone.now() - timedelta(days=30)
        )
        assert record_recipient_change(form, **kwargs) is not None
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/scripts/test_recipient_changes.py -q`
Expected: collection error — `ModuleNotFoundError: No module named 'apps.scripts.recipient_changes'`

- [ ] **Step 3: Add the event type**

In `apps/site_health/models.py`, add to `SiteEvent.EventType` after `SEO_META_CHANGED`:

```python
        # Where a form delivers changed. Not a "script" change — it comes from
        # the form's own configuration (a mailto: action, or the site's form
        # plugin read over WP Connect), so it has no ScriptChange to hang off
        # and lives here, on the site's timeline.
        FORM_RECIPIENTS_CHANGED = "form_recipients_changed", "Form recipients changed"
```

- [ ] **Step 4: Generate the migration**

Run: `.venv\Scripts\python.exe manage.py makemigrations site_health`
Expected: creates `0009_alter_siteevent_event_type.py` with a single `AlterField` on `event_type`. `"form_recipients_changed"` is 23 characters, inside the field's `max_length=30` — do not widen the column.

- [ ] **Step 5: Write the change module**

Create `apps/scripts/recipient_changes.py`:

```python
"""Deciding when a form's destination has really changed, and recording it.

Two writers keep `DetectedForm.recipients` current — the page ingest and the WP
Connect fetch — and each of them already compares old against new to avoid a
pointless UPDATE. This module turns that comparison into a decision about
whether a human should hear about it, which is a narrower question than "did the
bytes change".

Most differences are not news. A form Digivault has just learned about goes from
nothing to something; a plugin reorders its own notification list; a WordPress
read supersedes a guess made from the markup. Announcing any of those would post
once per form across the whole estate and train the team to ignore the channel.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.scripts.recipients import all_recipients, recipients_equal
from apps.site_health.models import SiteEvent

logger = logging.getLogger(__name__)

#: Suppress a repeat of the *same* transition for this long, matching the
#: ScriptChange cooldown. A form whose recipient flips between two addresses —
#: a staging value that gets re-applied on every deploy, say — would otherwise
#: post every night.
RECIPIENT_ALERT_COOLDOWN = timedelta(days=7)


def describe_recipient_change(old: dict, new: dict) -> dict | None:
    """What changed between two recipient sets, or `None` if it isn't news.

    Silent by design in two cases: an unchanged set (including one merely
    reordered — `recipients_equal` ignores order within a kind), and a first
    discovery, where the form had no known destination at all.
    """
    if recipients_equal(old, new):
        return None

    old_all = all_recipients(old)
    if not old_all:
        return None

    new_all = all_recipients(new)
    old_bcc = set((old or {}).get("bcc") or [])
    new_bcc = set((new or {}).get("bcc") or [])

    added = [e for e in new_all if e not in old_all]
    removed = [e for e in old_all if e not in new_all]
    # An address still receiving mail, but no longer as a visible destination.
    # Neither added nor removed, and easy to miss if not called out.
    moved_to_bcc = [e for e in new_bcc if e in old_all and e not in old_bcc]

    if not new_all:
        return {
            "severity": SiteEvent.Severity.CRITICAL,
            "summary_verb": "no longer delivers to anyone",
            "added": [], "removed": removed, "moved_to_bcc": [],
        }

    # Anything gained, lost from To, or hidden into Bcc is worth a warning.
    # Only losing a Cc is housekeeping.
    old_to = set((old or {}).get("to") or [])
    new_to = set((new or {}).get("to") or [])
    material = bool(added) or bool(moved_to_bcc) or bool(old_to - new_to)
    return {
        "severity": SiteEvent.Severity.WARNING if material else SiteEvent.Severity.INFO,
        "summary_verb": "changed where it delivers",
        "added": added, "removed": removed, "moved_to_bcc": moved_to_bcc,
    }


def form_label(form) -> str:
    """A name a human can find in the Forms tab."""
    return form.form_name or form.form_id or form.provider or "Unnamed form"


def _summary(form, change: dict) -> str:
    site = form.website.name or form.website.domain
    return f"{site} — form “{form_label(form)}” {change['summary_verb']}"[:500]


def record_recipient_change(
    form, *, old_recipients: dict, old_source: str, new_source: str
) -> SiteEvent | None:
    """Record that this form's destination changed, and queue the announcement.

    Call **after** `form.recipients` is saved. Returns the `SiteEvent`, or `None`
    when there is nothing to announce.

    A change only counts **within one source**. `page` → `wordpress` reporting
    different addresses is a better read of the same form, not an edit to it —
    the markup never had the real address to begin with. Treating it as a change
    would fire for every form on the estate the first time WP Connect answers.
    """
    if not old_source or old_source != new_source:
        return None

    change = describe_recipient_change(old_recipients, form.recipients)
    if change is None:
        return None

    summary = _summary(form, change)
    since = timezone.now() - RECIPIENT_ALERT_COOLDOWN
    if SiteEvent.objects.filter(
        website_id=form.website_id,
        event_type=SiteEvent.EventType.FORM_RECIPIENTS_CHANGED,
        summary=summary,
        occurred_at__gte=since,
    ).exists():
        return None

    event = SiteEvent.objects.create(
        website=form.website,
        event_type=SiteEvent.EventType.FORM_RECIPIENTS_CHANGED,
        severity=change["severity"],
        summary=summary,
        details={
            "form_id": str(form.pk),
            "form_label": form_label(form),
            "page_url": form.page_url,
            "source": new_source,
            "old": old_recipients,
            "new": form.recipients,
            "added": change["added"],
            "removed": change["removed"],
            "moved_to_bcc": change["moved_to_bcc"],
        },
    )

    # Posted after the surrounding transaction commits, never inside it. The
    # page-ingest writer runs inside `process_ingest_payload`'s transaction, and
    # a ClickUp call there would hold it open for the client's 10s timeout; the
    # form-error alert is split off for the same reason. on_commit also means a
    # rolled-back ingest announces nothing.
    def _queue():
        from apps.scripts.tasks import deliver_recipient_change_alert

        deliver_recipient_change_alert.delay(str(event.pk))

    transaction.on_commit(_queue)
    return event
```

- [ ] **Step 6: Run the tests**

Run: `.venv\Scripts\python.exe -m pytest tests/scripts/test_recipient_changes.py -q --create-db`
Expected: FAIL on the import of `deliver_recipient_change_alert` only if a test triggers `on_commit`; pytest-django wraps tests in a transaction that never commits, so `_queue` does not run. The 13 tests should PASS. If any fails on the missing task, add it in Task 7 and re-run.

- [ ] **Step 7: Commit**

```bash
git add apps/scripts/recipient_changes.py apps/site_health/models.py apps/site_health/migrations/0009_alter_siteevent_event_type.py tests/scripts/test_recipient_changes.py
git commit -m "feat(forms): record when a form's destination changes"
```

---

## Task 7: Announce the change in the team ClickUp channel

**Files:**
- Modify: `apps/scripts/tasks.py` (new Celery task; hook in `_apply_page_recipients`)
- Modify: `apps/websites/wp_forms.py` (hook in `apply_recipients`)
- Modify: `frontend/src/components/site-events-tab.tsx` (icon + label)
- Test: `tests/scripts/test_recipient_change_alerts.py`

**Interfaces:**
- Consumes: `record_recipient_change` (Task 6); `apps.integrations.chat.notify_problem`.
- Produces: Celery task `scripts.deliver_recipient_change_alert(event_pk: str) -> bool`.

> **The poster.** `notify_problem(website, *, subject, title, detail="", fields=None, emoji=PROBLEM_EMOJI, client=None) -> bool` in [apps/integrations/chat.py:234](apps/integrations/chat.py#L234). It **never raises** — it returns `False` when the team has no `clickup_chat_url` and logs-and-returns-`False` on any other failure. `subject` is log context only. `fields` is a list of `(label, value)` pairs; empty values are dropped. Managers are resolved and attached as followers by `_announce` itself — the caller passes none of that.

- [ ] **Step 1: Write the failing tests**

Create `tests/scripts/test_recipient_change_alerts.py`:

```python
"""The ClickUp announcement for a changed form destination."""

from unittest.mock import patch

import pytest

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.scripts.models import DetectedForm
from apps.scripts.recipients import build_recipients
from apps.scripts.tasks import deliver_recipient_change_alert
from apps.site_health.models import SiteEvent
from apps.websites.models import Website

PAGE = "https://rca.test/contact"


@pytest.fixture
def form(db):
    owner = User.objects.create_user(email="rca_o@test.com", password="Pass123!")
    team = TeamService.create(name="RCA Agency", owner=owner)
    team.clickup_chat_url = "https://app.clickup.com/9012/chat/r/abc123"
    team.save(update_fields=["clickup_chat_url"])
    website = Website.objects.create(team=team, name="RCA Site", domain="rca.test")
    return DetectedForm.objects.create(
        website=website, page_url=PAGE, fingerprint="fp1",
        form_name="New Form", fields=[],
        recipients=build_recipients(to="new@site.com"),
        recipient_source=DetectedForm.RecipientSource.WORDPRESS,
    )


def _event(form, **overrides):
    details = {
        "form_id": str(form.pk), "form_label": "New Form", "page_url": PAGE,
        "source": "wordpress",
        "old": build_recipients(to="old@site.com"),
        "new": build_recipients(to="new@site.com"),
        "added": ["new@site.com"], "removed": ["old@site.com"], "moved_to_bcc": [],
    }
    details.update(overrides.pop("details", {}))
    return SiteEvent.objects.create(
        website=form.website,
        event_type=SiteEvent.EventType.FORM_RECIPIENTS_CHANGED,
        severity=overrides.pop("severity", SiteEvent.Severity.WARNING),
        summary=overrides.pop("summary", "RCA Site — form “New Form” changed where it delivers"),
        details=details,
    )


@pytest.mark.django_db
class TestDeliverRecipientChangeAlert:
    def test_it_posts_the_old_and_new_addresses(self, form):
        event = _event(form)
        with patch("apps.integrations.chat.notify_problem", return_value=True) as post:
            assert deliver_recipient_change_alert(str(event.pk)) is True

        kwargs = post.call_args.kwargs
        fields = dict(kwargs["fields"])
        assert fields["Was"] == "old@site.com"
        assert fields["Now"] == "new@site.com"
        assert fields["Page"] == PAGE
        assert fields["Form"] == "New Form"
        assert "changed where it delivers" in kwargs["title"]
        assert str(event.pk) in kwargs["subject"]

    def test_cc_and_bcc_are_labelled_in_the_message(self, form):
        event = _event(form, details={
            "new": build_recipients(
                to="lead@site.com", cc="mgr@site.com", bcc="silent@site.com"
            ),
        })
        with patch("apps.integrations.chat.notify_problem", return_value=True) as post:
            deliver_recipient_change_alert(str(event.pk))

        now = dict(post.call_args.kwargs["fields"])["Now"]
        assert "lead@site.com" in now
        assert "mgr@site.com (Cc)" in now
        assert "silent@site.com (Bcc)" in now

    def test_delivering_to_nobody_says_so(self, form):
        event = _event(
            form,
            severity=SiteEvent.Severity.CRITICAL,
            summary="RCA Site — form “New Form” no longer delivers to anyone",
            details={"new": build_recipients(), "added": [], "removed": ["old@site.com"]},
        )
        with patch("apps.integrations.chat.notify_problem", return_value=True) as post:
            deliver_recipient_change_alert(str(event.pk))

        kwargs = post.call_args.kwargs
        assert "no longer delivers to anyone" in kwargs["title"]
        assert dict(kwargs["fields"])["Now"] == "nobody"

    def test_a_missing_event_is_not_an_error(self, form):
        """The purge or a manual delete can race the queued task."""
        with patch("apps.integrations.chat.notify_problem") as post:
            assert deliver_recipient_change_alert(
                "00000000-0000-0000-0000-000000000000"
            ) is False
        post.assert_not_called()

    def test_a_clickup_outage_does_not_raise(self, form):
        """notify_problem swallows its own failures; the task must not add one."""
        event = _event(form)
        with patch("apps.integrations.chat.notify_problem", return_value=False):
            assert deliver_recipient_change_alert(str(event.pk)) is False

    def test_an_unrelated_event_type_is_ignored(self, form):
        other = SiteEvent.objects.create(
            website=form.website, event_type=SiteEvent.EventType.DEPLOYMENT,
            summary="deployed", details={},
        )
        with patch("apps.integrations.chat.notify_problem") as post:
            assert deliver_recipient_change_alert(str(other.pk)) is False
        post.assert_not_called()


@pytest.mark.django_db
class TestWritersHookIn:
    def test_the_wordpress_fetch_records_a_change(self, form):
        """End to end through the real writer, not the helper."""
        from apps.websites.wp_forms import apply_recipients

        with patch("apps.scripts.recipient_changes.transaction.on_commit"):
            apply_recipients(form.website, [{
                "name": "New Form", "to": ["replacement@site.com"],
            }])

        assert SiteEvent.objects.filter(
            event_type=SiteEvent.EventType.FORM_RECIPIENTS_CHANGED
        ).count() == 1
        form.refresh_from_db()
        assert form.recipients["to"] == ["replacement@site.com"]

    def test_a_page_ingest_that_only_confirms_records_nothing(self, form):
        from apps.scripts.tasks import _upsert_form

        _upsert_form(form.website, PAGE, {
            "form_name": "New Form", "detection_type": "native",
            "fields": [{"name": "email"}], "recipients": {},
        })
        assert SiteEvent.objects.filter(
            event_type=SiteEvent.EventType.FORM_RECIPIENTS_CHANGED
        ).count() == 0
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/scripts/test_recipient_change_alerts.py -q`
Expected: FAIL — `ImportError: cannot import name 'deliver_recipient_change_alert'`

- [ ] **Step 3: Write the Celery task**

Add to `apps/scripts/tasks.py`, beside the existing `deliver_form_error_alert`:

```python
def _format_recipients(recipients: dict) -> str:
    """One line naming every destination, with copies labelled.

    A Bcc that reads identically to a To would hide the most interesting case
    this alert exists to surface.
    """
    recipients = recipients if isinstance(recipients, dict) else {}
    parts = list(recipients.get("to") or [])
    parts += [f"{e} (Cc)" for e in recipients.get("cc") or []]
    parts += [f"{e} (Bcc)" for e in recipients.get("bcc") or []]
    return ", ".join(parts) if parts else "nobody"


@shared_task(name="scripts.deliver_recipient_change_alert")
def deliver_recipient_change_alert(event_pk: str) -> bool:
    """Announce a changed form destination in the team's ClickUp channel.

    Queued by `record_recipient_change` on transaction commit, so the HTTP call
    never happens inside the ingest transaction. Returns whether a message was
    posted; `False` covers a team with no channel configured, which is the
    normal case for most teams and not a failure.
    """
    from apps.integrations import chat
    from apps.site_health.models import SiteEvent

    event = (
        SiteEvent.objects.filter(
            pk=event_pk,
            event_type=SiteEvent.EventType.FORM_RECIPIENTS_CHANGED,
        )
        .select_related("website", "website__team")
        .first()
    )
    if event is None:
        # A purge or a manual delete can race the queued task. Not an error.
        logger.debug("deliver_recipient_change_alert: event %s is gone", event_pk)
        return False

    details = event.details or {}
    # The summary already reads "<site> — form “X” <verb>"; the title is the
    # part after the site name, because build_message prefixes the site itself.
    verb = (
        "no longer delivers to anyone"
        if event.severity == SiteEvent.Severity.CRITICAL
        else "changed where it delivers"
    )
    label = details.get("form_label") or "a form"
    fields = [
        ("Form", label),
        ("Page", details.get("page_url", "")),
        ("Was", _format_recipients(details.get("old") or {})),
        ("Now", _format_recipients(details.get("new") or {})),
        (
            "Read from",
            "the site's WordPress form settings"
            if details.get("source") == "wordpress"
            else "the page markup",
        ),
    ]
    if details.get("moved_to_bcc"):
        # Still receiving mail, but no longer a visible destination.
        fields.append(("Moved to Bcc", ", ".join(details["moved_to_bcc"])))

    return chat.notify_problem(
        event.website,
        subject=f"form-recipients:{event.pk}",
        title=f"has a form that {verb}",
        fields=fields,
        emoji="📩",
    )
```

- [ ] **Step 4: Hook in the page-ingest writer**

In `apps/scripts/tasks.py`, `_apply_page_recipients` (from Task 3) captures the old state before writing and records afterwards. Replace its final four lines:

```python
    old_recipients = form.recipients
    old_source = form.recipient_source
    form.recipients = recipients
    form.recipient_source = DetectedForm.RecipientSource.PAGE
    form.save(update_fields=["recipients", "recipient_source", "updated_at"])
    record_recipient_change(
        form,
        old_recipients=old_recipients,
        old_source=old_source,
        new_source=DetectedForm.RecipientSource.PAGE,
    )
```

with this import at the top of the file:

```python
from apps.scripts.recipient_changes import record_recipient_change
```

- [ ] **Step 5: Hook in the WordPress writer**

In `apps/websites/wp_forms.py`, `apply_recipients` (from Task 4), replace the inner write:

```python
        for form in matched:
            if (
                recipients_equal(form.recipients, recipients)
                and form.recipient_source == DetectedForm.RecipientSource.WORDPRESS
            ):
                continue
            old_recipients = form.recipients
            old_source = form.recipient_source
            form.recipients = recipients
            form.recipient_source = DetectedForm.RecipientSource.WORDPRESS
            form.save(update_fields=["recipients", "recipient_source", "updated_at"])
            record_recipient_change(
                form,
                old_recipients=old_recipients,
                old_source=old_source,
                new_source=DetectedForm.RecipientSource.WORDPRESS,
            )
            written += 1
```

with a local import inside the function, beside the existing ones:

```python
    from apps.scripts.recipient_changes import record_recipient_change
```

- [ ] **Step 6: Label the event in the Change Log**

In `frontend/src/components/site-events-tab.tsx`, add `Mail` to the lucide import and one entry to each map (the tab already falls back for unknown types, so this is polish, not a fix):

```tsx
const EVENT_ICON: Record<string, React.ReactNode> = {
  // ...existing entries...
  form_recipients_changed: <Mail className="h-3.5 w-3.5" />,
};
```

```tsx
const EVENT_LABEL: Record<string, string> = {
  // ...existing entries...
  form_recipients_changed: "Form Recipients Changed",
};
```

- [ ] **Step 7: Run the tests**

Run: `.venv\Scripts\python.exe -m pytest tests/scripts/test_recipient_change_alerts.py tests/scripts/test_recipient_changes.py -q`
Expected: PASS

- [ ] **Step 8: Run the full suite and the frontend**

```bash
.venv\Scripts\python.exe -m pytest -q --create-db
cd frontend && npx tsc --noEmit && npm run lint && npm run build
```
Expected: full suite green; lint shows only the 5 pre-existing problems.

- [ ] **Step 9: Commit**

```bash
git add apps/scripts/tasks.py apps/websites/wp_forms.py frontend/src/components/site-events-tab.tsx tests/scripts/test_recipient_change_alerts.py
git commit -m "feat(forms): tell the team in ClickUp when a form changes where it delivers"
```

---

## Task 8: Drop the deprecated column

**Do not start this task until Tasks 2–7 have been deployed and a WP Connect read has been confirmed against a live site.** The column is the only copy of the pre-migration value; dropping it is the one step here that cannot be undone by reverting code.

**Files:**
- Modify: `apps/scripts/models.py` (remove the deprecated `recipient_email` field)
- Create: `apps/scripts/migrations/0027_remove_detectedform_recipient_email.py`

**Interfaces:**
- Consumes: nothing.
- Produces: no `recipient_email` column. The API keeps emitting the key — it is a `SerializerMethodField` over `recipients` (Task 3) and is unaffected.

- [ ] **Step 1: Prove nothing reads the column**

Run: `grep -rn "recipient_email" apps/ tests/ --include=*.py | grep -v migrations`
Expected: only `apps/scripts/serializers.py` (the `SerializerMethodField` and its `get_` method), `apps/scripts/normalize.py` (the `normalize_recipient_email` function, which stays — `normalize_recipient_list` is built on it), and `apps/scripts/models.py` (the field about to go). **Any other hit is a reader that was missed; fix it before continuing.**

- [ ] **Step 2: Remove the field**

Delete the deprecated `recipient_email` field and its comment from `apps/scripts/models.py`, leaving `recipients` and `recipient_source`.

- [ ] **Step 3: Generate the migration**

Run: `.venv\Scripts\python.exe manage.py makemigrations scripts`
Expected: `0027_remove_detectedform_recipient_email.py`, one `RemoveField`.

- [ ] **Step 4: Verify**

```bash
.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.venv\Scripts\python.exe -m pytest -q --create-db
```
Expected: "No changes detected"; full suite green.

- [ ] **Step 5: Commit**

```bash
git add apps/scripts/models.py apps/scripts/migrations/0027_remove_detectedform_recipient_email.py
git commit -m "refactor(forms): drop the superseded single-recipient column"
```

---

## Verification

- `.venv\Scripts\python.exe -m pytest -q --create-db` — full suite green (baseline: 1028 passed).
- `cd frontend && npx tsc --noEmit && npm run lint && npm run build` — lint shows only the 5 pre-existing problems.
- `php -l` on the generated snippet.
- `.venv\Scripts\python.exe manage.py makemigrations --check --dry-run` — no model drift.

## Rollout

1. Deploy Tasks 1–7 together: `./deploy.sh` for the backend, then pm2 for the frontend. The `api` entrypoint runs `migrate` on startup, so `0026` (add + backfill) and site_health `0009` apply automatically. Hard-refresh the browser afterwards — stale bundles produce "Failed to find Server Action" until reload.
2. **Re-paste the WP Connect snippet on each site.** Cc/Bcc lands in the same route as the recipient read, so a site pasted after this ships needs one paste, not two — which is the whole reason to do this before rolling the previous change out.
3. Click **Read recipients from WordPress** on a site with a known multi-recipient form and confirm the dialog lists every address under To / Cc / Bcc.
4. Confirm the channel is quiet. That first read moves rows from `page` (or nothing) to `wordpress`, which is exactly the transition Task 6 refuses to announce. **A burst of ClickUp messages here means the source gate is wrong** — stop and fix it before the nightly sweep runs.
5. Then verify the alert positively: edit a form's "To" in WordPress, click **Read recipients from WordPress**, and check both the Change Log tab and the ClickUp channel.
6. Only after that, do Task 8 in a later deploy.
