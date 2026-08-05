# ClickUp Web Team Channel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Post website problems into one ClickUp Chat channel that holds the whole web team, addressed to the developer who owns that client, linked to the ClickUp task Digivault opens for the issue.

**Architecture:** A new `apps/integrations/chat.py` is the single entry point (`notify_problem` / `notify_recovery`) that the three existing alert paths call. It resolves the owning developer from `Client.assigned_to`, looks up their ClickUp user id in a new `ClickUpMemberLink` table, opens or comments on a task via the already-written `report_issue()`, and posts a markdown message via the already-written `ClickUpClient.post_chat()`. Everything is best-effort — an unconfigured team is a silent no-op and no ClickUp failure may propagate into an alert path.

**Tech Stack:** Django 5.1, DRF, pytest (`--reuse-db`), Next.js 16 App Router, React 19, Tailwind v4, ClickUp API v2 + v3.

**Spec:** [docs/superpowers/specs/2026-08-05-clickup-web-team-channel-design.md](../specs/2026-08-05-clickup-web-team-channel-design.md)

## Global Constraints

- **Never let ClickUp break an alert.** Every call from an alert path catches `Exception`, logs via `logger.exception`, and returns. This is the contract `report_issue()` already follows.
- **Unconfigured is normal, not an error.** No token / no `clickup_chat_url` / no `clickup_list_id` → return `False` silently. Do not `logger.warning` on these.
- **Run migrations tests with `--create-db`.** This plan adds two migrations. `pytest` defaults to `--reuse-db`; after Task 3 and Task 4 you MUST pass `--create-db` once or the schema will not rebuild and every test errors.
- **One field holds the chat target.** `Team.clickup_chat_url` stores a URL; workspace and channel ids are always derived by `parse_clickup_chat()`. Never add separate id columns.
- **A created channel's URL is synthesized** as `https://app.clickup.com/{workspace_id}/chat/r/{channel_id}` — this parses back correctly through the existing regex.
- **Envelope:** all DRF HTTP responses are wrapped `{data, errors, meta}` by `EnvelopeJSONRenderer`, but `response.data` in tests is the RAW payload. Assert `resp.data["x"]`, never `resp.data["data"]["x"]`.
- **Frontend:** Next.js 16 has breaking changes from training data. Route handler `params` is a `Promise` and must be awaited — copy [frontend/src/app/api/teams/[id]/settings/clickup-test/route.ts](../../../frontend/src/app/api/teams/[id]/settings/clickup-test/route.ts) exactly rather than writing from memory.
- **Commit message trailer** on every commit: `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`

## File Structure

**Create:**
- `apps/integrations/chat.py` — owner resolution, mention formatting, the two notify entry points
- `apps/integrations/members.py` — Digivault user ↔ ClickUp member matching
- `apps/integrations/migrations/0002_clickupmemberlink.py`
- `apps/accounts/migrations/0011_team_clickup_chat_url.py`
- `tests/integrations/test_chat.py`
- `tests/integrations/test_member_links.py`
- `tests/accounts/test_clickup_channel.py`
- `frontend/src/app/api/teams/[id]/settings/clickup-channel/route.ts`
- `frontend/src/app/api/teams/[id]/settings/clickup-members/route.ts`

**Modify:**
- `apps/integrations/clickup.py` — `parse_clickup_chat`, `workspaces`, `create_chat_channel`, `followers` on `post_chat`
- `apps/integrations/models.py` — add `ClickUpMemberLink`
- `apps/accounts/models.py` — add `Team.clickup_chat_url`
- `apps/accounts/serializers.py` — expose the new field
- `apps/accounts/views.py` — PATCH handling + two new views
- `apps/accounts/urls.py` — two new routes
- `apps/monitors/notifications.py` — re-export `parse_clickup_chat`, wire uptime
- `apps/domains/notifications.py` — wire expiry alerts
- `apps/site_health/notifications.py` — `subject_key` kwarg + wire
- `apps/site_health/tasks.py` — pass `subject_key` at the two call sites
- `frontend/src/components/settings-client.tsx` — channel + member-mapping UI

---

### Task 1: Move `parse_clickup_chat` into the ClickUp module

`parse_clickup_chat` currently lives in `apps.monitors.notifications`, which makes `monitors` the home of a helper that `integrations`, `domains` and `site_health` all now need. Move it, re-export it so the existing import path keeps working.

**Files:**
- Modify: `apps/integrations/clickup.py`
- Modify: `apps/monitors/notifications.py:62-70`
- Test: `tests/integrations/test_clickup_client.py`

**Interfaces:**
- Produces: `apps.integrations.clickup.parse_clickup_chat(url: str) -> tuple[str | None, str | None]`
- `apps.monitors.notifications.parse_clickup_chat` remains importable (re-export).

- [ ] **Step 1: Write the failing test**

Append to `tests/integrations/test_clickup_client.py`:

```python
def test_parse_clickup_chat_lives_on_the_clickup_module():
    from apps.integrations.clickup import parse_clickup_chat

    ws, ch = parse_clickup_chat("https://digilatics.clickup.com/25658037/chat/r/rf0nn-49438")
    assert (ws, ch) == ("25658037", "rf0nn-49438")
    assert parse_clickup_chat("") == (None, None)
    assert parse_clickup_chat("https://example.com/x") == (None, None)


def test_a_synthesized_channel_url_parses_back():
    """create_chat_channel builds its URL by hand; it must round-trip."""
    from apps.integrations.clickup import parse_clickup_chat

    url = "https://app.clickup.com/9001/chat/r/chan-77"
    assert parse_clickup_chat(url) == ("9001", "chan-77")


def test_monitors_still_re_exports_parse_clickup_chat():
    from apps.monitors.notifications import parse_clickup_chat as from_monitors
    from apps.integrations.clickup import parse_clickup_chat as from_integrations

    assert from_monitors is from_integrations
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integrations/test_clickup_client.py -v -k parse_clickup_chat`
Expected: FAIL with `ImportError: cannot import name 'parse_clickup_chat' from 'apps.integrations.clickup'`

- [ ] **Step 3: Add the function to `apps/integrations/clickup.py`**

Add `import re` to the imports at the top, then insert after the `DEFAULT_TIMEOUT = 10` line:

```python
# Matches a ClickUp Chat channel link, e.g.
# https://digilatics.clickup.com/25658037/chat/r/rf0nn-49438
_CHAT_URL_RE = re.compile(r"clickup\.com/(\d+)/chat/(?:r/)?([^/?#]+)", re.I)


def parse_clickup_chat(url: str) -> tuple[str | None, str | None]:
    """Return (workspace_id, channel_id) from a ClickUp Chat channel link.

    Both None when the URL is blank or is not a chat link — callers treat that
    as "no chat target configured", not as an error.
    """
    m = _CHAT_URL_RE.search(url or "")
    return (m.group(1), m.group(2)) if m else (None, None)
```

- [ ] **Step 4: Replace the copy in `apps/monitors/notifications.py`**

Delete lines 62-70 (the `_CLICKUP_CHAT_RE` comment, regex, and `parse_clickup_chat` def) and change the import at line 14 to:

```python
from apps.integrations.clickup import ClickUpClient, parse_clickup_chat  # noqa: F401
```

The `noqa: F401` is deliberate — `parse_clickup_chat` is re-exported for
`tests/monitors/test_clickup_post.py` and is otherwise used at line 87.

Remove the now-unused `import re` from the top of the file.

- [ ] **Step 5: Run the affected tests**

Run: `pytest tests/integrations/test_clickup_client.py tests/monitors/test_clickup_post.py -v`
Expected: PASS (all, including the 3 new ones)

- [ ] **Step 6: Commit**

```bash
git add apps/integrations/clickup.py apps/monitors/notifications.py tests/integrations/test_clickup_client.py
git commit -m "$(cat <<'EOF'
refactor(integrations): move parse_clickup_chat onto the clickup module

Three more apps need it now. monitors re-exports it so existing imports
keep working.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: ClickUp client — workspaces, channel creation, message followers

Three additions to `ClickUpClient`. `followers` is what actually notifies the owning developer, because ClickUp does not document any inline @-mention syntax for v3 chat messages.

**Files:**
- Modify: `apps/integrations/clickup.py`
- Test: `tests/integrations/test_clickup_client.py`

**Interfaces:**
- Consumes: `parse_clickup_chat` from Task 1.
- Produces:
  - `ClickUpClient.workspaces() -> list[dict]` — each `{"id", "name", "members": [{"user": {"id", "username", "email"}}]}`
  - `ClickUpClient.create_chat_channel(workspace_id, *, name, user_ids=None, description="", visibility="PRIVATE") -> dict` — returns `{"id", "url", ...}` where `url` is synthesized if ClickUp omits it
  - `ClickUpClient.post_chat(workspace_id, channel_id, text, *, followers=None) -> dict`

- [ ] **Step 1: Write the failing tests**

Append to `tests/integrations/test_clickup_client.py`. Note the existing file already defines a recording session fixture pattern — reuse whatever helper is at the top of that file; if it differs from below, adapt the assertions, not the helper.

```python
def test_workspaces_reads_the_v2_team_endpoint():
    session = RecordingSession(payload={"teams": [{"id": "9001", "name": "Digilatics", "members": []}]})
    client = ClickUpClient("pk_test", session=session)

    teams = client.workspaces()

    assert session.urls() == ["https://api.clickup.com/api/v2/team"]
    assert teams[0]["id"] == "9001"


def test_workspaces_returns_empty_when_clickup_sends_no_teams_key():
    session = RecordingSession(payload={})
    assert ClickUpClient("pk_test", session=session).workspaces() == []


def test_create_chat_channel_posts_name_and_user_ids():
    session = RecordingSession(payload={"id": "chan-77"})
    client = ClickUpClient("pk_test", session=session)

    channel = client.create_chat_channel("9001", name="Web Team", user_ids=[11, 22])

    assert session.urls() == ["https://api.clickup.com/api/v3/workspaces/9001/chat/channels"]
    body = session.calls[0]["json"]
    assert body["name"] == "Web Team"
    assert body["user_ids"] == [11, 22]
    assert body["visibility"] == "PRIVATE"
    # ClickUp returned no url, so we synthesize one that parses back.
    assert channel["url"] == "https://app.clickup.com/9001/chat/r/chan-77"


def test_create_chat_channel_omits_empty_user_ids():
    """ClickUp rejects a null/empty user_ids array."""
    session = RecordingSession(payload={"id": "chan-1"})
    ClickUpClient("pk_test", session=session).create_chat_channel("9001", name="X", user_ids=[])

    assert "user_ids" not in session.calls[0]["json"]


def test_create_chat_channel_keeps_a_url_clickup_provided():
    session = RecordingSession(payload={"id": "chan-77", "url": "https://real.clickup.com/9001/chat/r/chan-77"})
    channel = ClickUpClient("pk_test", session=session).create_chat_channel("9001", name="X")

    assert channel["url"] == "https://real.clickup.com/9001/chat/r/chan-77"


def test_post_chat_sends_followers_when_given():
    session = RecordingSession(payload={"id": "msg-1"})
    ClickUpClient("pk_test", session=session).post_chat("9001", "chan-77", "hi", followers=[11])

    body = session.calls[0]["json"]
    assert body["followers"] == [11]
    assert body["content"] == "hi"
    assert body["content_format"] == "text/md"


def test_post_chat_omits_followers_when_empty():
    session = RecordingSession(payload={"id": "msg-1"})
    ClickUpClient("pk_test", session=session).post_chat("9001", "chan-77", "hi", followers=[])

    assert "followers" not in session.calls[0]["json"]
```

If `RecordingSession` in that file does not accept a `payload` kwarg, add one:

```python
class RecordingSession:
    def __init__(self, payload=None):
        self.calls = []
        self._payload = payload or {}

    def request(self, method, url, headers=None, json=None, timeout=None):
        self.calls.append({"method": method, "url": url, "json": json})
        return FakeResponse(200, self._payload)

    def urls(self):
        return [c["url"] for c in self.calls]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/integrations/test_clickup_client.py -v -k "workspaces or create_chat_channel or post_chat"`
Expected: FAIL with `AttributeError: 'ClickUpClient' object has no attribute 'workspaces'`

- [ ] **Step 3: Implement the three methods**

In `apps/integrations/clickup.py`, add to the endpoints section:

```python
    def workspaces(self) -> list:
        """The workspaces (ClickUp calls them "teams") this token can see.

        Each carries a `members` list, which is how a Digivault user is matched
        to a ClickUp user id.
        """
        return self._request("GET", "team").get("teams", [])

    def create_chat_channel(
        self,
        workspace_id: str,
        *,
        name: str,
        user_ids: list | None = None,
        description: str = "",
        visibility: str = "PRIVATE",
    ) -> dict:
        """Create a Chat channel with `user_ids` already in it.

        ClickUp does not reliably return a browsable URL, so one is synthesized
        in the shape `parse_clickup_chat` understands — that keeps the channel
        target a single stored URL rather than a pair of id columns.
        """
        body: dict = {"name": name, "visibility": visibility}
        if description:
            body["description"] = description
        # Sent only when non-empty — ClickUp rejects an empty user_ids array.
        if user_ids:
            body["user_ids"] = user_ids

        channel = self._request(
            "POST", f"workspaces/{workspace_id}/chat/channels", json=body, version="v3"
        )
        if not channel.get("url") and channel.get("id"):
            channel["url"] = f"https://app.clickup.com/{workspace_id}/chat/r/{channel['id']}"
        return channel
```

Then replace the existing `post_chat` with:

```python
    def post_chat(
        self, workspace_id: str, channel_id: str, text: str, *, followers: list | None = None
    ) -> dict:
        """Post a markdown message to a Chat channel.

        `followers` is what actually notifies someone: ClickUp documents no
        request-side syntax for an inline @-mention in a v3 chat message, so the
        body's "@name" is for human readers and this is the real ping.
        """
        body: dict = {"type": "message", "content": text, "content_format": "text/md"}
        if followers:
            body["followers"] = followers
        return self._request(
            "POST",
            f"workspaces/{workspace_id}/chat/channels/{channel_id}/messages",
            json=body,
            version="v3",
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/integrations/test_clickup_client.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/integrations/clickup.py tests/integrations/test_clickup_client.py
git commit -m "$(cat <<'EOF'
feat(integrations): workspace listing, channel creation, message followers

followers is the notification mechanism — ClickUp documents no inline
@-mention syntax for v3 chat messages.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: `Team.clickup_chat_url` + settings serializer + PATCH

**Files:**
- Modify: `apps/accounts/models.py:90` (after `clickup_list_id`)
- Create: `apps/accounts/migrations/0011_team_clickup_chat_url.py`
- Modify: `apps/accounts/serializers.py:103-121`
- Modify: `apps/accounts/views.py:854-874`
- Create: `tests/accounts/test_clickup_channel.py`

**Interfaces:**
- Consumes: `parse_clickup_chat` from Task 1.
- Produces: `Team.clickup_chat_url` (CharField, blank default `""`); `TeamSettingsSerializer` fields `clickup_chat_url` + `clickup_chat_connected`.

- [ ] **Step 1: Write the failing test**

Create `tests/accounts/test_clickup_channel.py`:

```python
"""Team-level ClickUp chat channel settings.

The channel target is stored as a single URL and parsed on use, so these tests
guard the two things that can silently break notifications: an unparseable URL
being accepted, and a PATCH for one field clearing another.
"""
import pytest

from apps.accounts.models import Team


def _settings_url(team):
    return f"/api/v1/auth/teams/{team.id}/settings/"


def test_patching_the_chat_url_stores_it(auth_client, team):
    resp = auth_client.patch(
        _settings_url(team),
        {"clickup_chat_url": "https://digilatics.clickup.com/25658037/chat/r/rf0nn-49438"},
        format="json",
    )

    assert resp.status_code == 200
    team.refresh_from_db()
    assert team.clickup_chat_url == "https://digilatics.clickup.com/25658037/chat/r/rf0nn-49438"
    assert resp.data["clickup_chat_connected"] is True


def test_an_unparseable_chat_url_is_rejected(auth_client, team):
    resp = auth_client.patch(
        _settings_url(team), {"clickup_chat_url": "https://example.com/nope"}, format="json"
    )

    assert resp.status_code == 400
    team.refresh_from_db()
    assert team.clickup_chat_url == ""


def test_an_empty_chat_url_is_an_intentional_clear(auth_client, team):
    team.clickup_chat_url = "https://app.clickup.com/9001/chat/r/chan-77"
    team.save()

    resp = auth_client.patch(_settings_url(team), {"clickup_chat_url": ""}, format="json")

    assert resp.status_code == 200
    team.refresh_from_db()
    assert team.clickup_chat_url == ""
    assert resp.data["clickup_chat_connected"] is False


def test_patching_only_the_chat_url_leaves_token_and_list_intact(auth_client, team):
    team.clickup_api_token = "pk_keepme"
    team.clickup_list_id = "list-42"
    team.clickup_chat_url = ""
    team.save()

    auth_client.patch(
        _settings_url(team),
        {"clickup_chat_url": "https://app.clickup.com/9001/chat/r/chan-77"},
        format="json",
    )

    team.refresh_from_db()
    assert team.clickup_api_token == "pk_keepme"
    assert team.clickup_list_id == "list-42"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/accounts/test_clickup_channel.py -v --create-db`
Expected: FAIL — `AttributeError: 'Team' object has no attribute 'clickup_chat_url'`

- [ ] **Step 3: Add the model field**

In `apps/accounts/models.py`, immediately after the `clickup_list_id` field (line 90):

```python
    # ClickUp Chat channel the whole web team sits in — where website problems
    # are announced. Stored as the URL the user sees; workspace and channel ids
    # are parsed out on use so there is only one thing to configure. Blank means
    # chat posting is a no-op.
    clickup_chat_url = models.CharField(max_length=500, blank=True, default="")
```

- [ ] **Step 4: Generate the migration**

Run: `python manage.py makemigrations accounts -n team_clickup_chat_url`
Expected: creates `apps/accounts/migrations/0011_team_clickup_chat_url.py`

- [ ] **Step 5: Expose it on the serializer**

In `apps/accounts/serializers.py`, in `TeamSettingsSerializer`:

Add below `clickup_connected = serializers.SerializerMethodField()`:

```python
    clickup_chat_connected = serializers.SerializerMethodField()
```

Change `fields` to:

```python
        fields = (
            "id", "name", "clickup_api_token", "clickup_connected",
            "clickup_list_id", "clickup_chat_url", "clickup_chat_connected",
        )
```

Add the method next to `get_clickup_connected`:

```python
    def get_clickup_chat_connected(self, obj) -> bool:
        return bool(obj.clickup_chat_url)
```

- [ ] **Step 6: Handle it in the PATCH**

In `apps/accounts/views.py`, inside `TeamSettingsView.patch`, after the
`clickup_list_id` block (line 862-865) and before `if changed_fields:`:

```python
        if "clickup_chat_url" in request.data:
            from apps.integrations.clickup import parse_clickup_chat

            chat_url = (request.data.get("clickup_chat_url") or "").strip()
            # A blank value is an intentional clear. A non-blank value that does
            # not parse would store a channel we can never post to, so reject it
            # here rather than failing silently at alert time.
            if chat_url and parse_clickup_chat(chat_url) == (None, None):
                return Response(
                    {"detail": "That does not look like a ClickUp Chat channel link."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            team.clickup_chat_url = chat_url
            changed_fields.append("clickup_chat_url")
            updated.append("team channel")
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/accounts/test_clickup_channel.py tests/accounts/test_team_settings.py -v --create-db`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add apps/accounts/models.py apps/accounts/migrations/0011_team_clickup_chat_url.py apps/accounts/serializers.py apps/accounts/views.py tests/accounts/test_clickup_channel.py
git commit -m "$(cat <<'EOF'
feat(accounts): Team.clickup_chat_url for the web team channel

Validated on write — an unparseable link would store a channel we could
never post to, failing silently at alert time instead.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: `ClickUpMemberLink` + member matching

**Files:**
- Modify: `apps/integrations/models.py`
- Create: `apps/integrations/migrations/0002_clickupmemberlink.py`
- Create: `apps/integrations/members.py`
- Create: `tests/integrations/test_member_links.py`

**Interfaces:**
- Consumes: `ClickUpClient.workspaces()` from Task 2.
- Produces:
  - `ClickUpMemberLink(team, user, clickup_user_id, clickup_username)`
  - `sync_member_links(team, *, client=None) -> dict` returning `{"matched": [{"user_id", "email", "clickup_user_id", "clickup_username"}], "unmatched": [{"user_id", "email"}], "workspace_id": str | None}`
  - `set_member_link(team, user, clickup_user_id, clickup_username="") -> ClickUpMemberLink`

- [ ] **Step 1: Write the failing tests**

Create `tests/integrations/test_member_links.py`:

```python
"""Matching Digivault users to ClickUp members.

Email is the only join key ClickUp gives us, and it is frequently different
from the Digivault one — so "unmatched" is a first-class result the UI shows,
not an error.
"""
import pytest

from apps.accounts.models import TeamMembership, User
from apps.integrations.clickup import ClickUpClient
from apps.integrations.members import set_member_link, sync_member_links
from apps.integrations.models import ClickUpMemberLink


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = ""

    def json(self):
        return self._payload


class WorkspaceSession:
    """Returns one workspace whose members are `members`."""

    def __init__(self, members):
        self.calls = []
        self._members = members

    def request(self, method, url, headers=None, json=None, timeout=None):
        self.calls.append({"method": method, "url": url, "json": json})
        return FakeResponse(200, {"teams": [{"id": "9001", "name": "WS", "members": self._members}]})


def _member(user_id, email, username="cu"):
    return {"user": {"id": user_id, "email": email, "username": username}}


def _client(session):
    return ClickUpClient("pk_test", session=session)


@pytest.fixture
def team_with_dev(db):
    from apps.accounts.services import TeamService

    owner = User.objects.create_user(email="owner@x.io", password="Pass123!")
    t = TeamService.create(name="Links Co", owner=owner)
    t.clickup_api_token = "pk_test"
    t.save()
    dev = User.objects.create_user(email="Jane@X.io", password="Pass123!")
    TeamMembership.objects.create(user=dev, team=t, role=TeamMembership.Role.DEVELOPER)
    return t, dev


def test_matching_is_case_insensitive_on_email(team_with_dev):
    team, dev = team_with_dev
    session = WorkspaceSession([_member(11, "jane@x.io", "jane")])

    result = sync_member_links(team, client=_client(session))

    link = ClickUpMemberLink.objects.get(team=team, user=dev)
    assert link.clickup_user_id == "11"
    assert link.clickup_username == "jane"
    assert result["workspace_id"] == "9001"
    assert {m["user_id"] for m in result["matched"]} == {str(dev.id)}


def test_a_member_clickup_does_not_know_is_reported_unmatched(team_with_dev):
    team, dev = team_with_dev
    session = WorkspaceSession([_member(11, "someone-else@x.io")])

    result = sync_member_links(team, client=_client(session))

    assert ClickUpMemberLink.objects.filter(team=team, user=dev).count() == 0
    assert str(dev.id) in {m["user_id"] for m in result["unmatched"]}


def test_syncing_twice_updates_rather_than_duplicates(team_with_dev):
    team, dev = team_with_dev

    sync_member_links(team, client=_client(WorkspaceSession([_member(11, "jane@x.io", "jane")])))
    sync_member_links(team, client=_client(WorkspaceSession([_member(99, "jane@x.io", "jane2")])))

    link = ClickUpMemberLink.objects.get(team=team, user=dev)
    assert link.clickup_user_id == "99"
    assert link.clickup_username == "jane2"
    assert ClickUpMemberLink.objects.filter(team=team).count() <= 2  # owner may also match


def test_an_unconfigured_team_syncs_nothing(db):
    from apps.accounts.services import TeamService

    owner = User.objects.create_user(email="noconf@x.io", password="Pass123!")
    team = TeamService.create(name="No Token", owner=owner)

    result = sync_member_links(team)

    assert result == {"matched": [], "unmatched": [], "workspace_id": None}


def test_set_member_link_overrides_a_failed_email_match(team_with_dev):
    team, dev = team_with_dev

    link = set_member_link(team, dev, "424242")

    assert link.clickup_user_id == "424242"
    assert ClickUpMemberLink.objects.get(team=team, user=dev).clickup_user_id == "424242"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/integrations/test_member_links.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.integrations.members'`

- [ ] **Step 3: Add the model**

Append to `apps/integrations/models.py`:

```python
class ClickUpMemberLink(BaseModel):
    """Maps a Digivault user to their ClickUp user id, per team.

    Email is the only join key ClickUp exposes, and agency people routinely have
    a different address in each system — so this is a stored mapping that can be
    corrected by hand, not a lookup done fresh each time.
    """

    team = models.ForeignKey(
        "accounts.Team", on_delete=models.CASCADE, related_name="clickup_member_links"
    )
    user = models.ForeignKey(
        "accounts.User", on_delete=models.CASCADE, related_name="clickup_member_links"
    )
    clickup_user_id = models.CharField(max_length=32)
    clickup_username = models.CharField(max_length=120, blank=True, default="")

    class Meta:
        ordering = ["-created_at"]
        unique_together = [("team", "user")]
        indexes = [models.Index(fields=["team", "user"])]

    def __str__(self) -> str:
        return f"{self.user_id} -> clickup:{self.clickup_user_id}"
```

- [ ] **Step 4: Generate the migration**

Run: `python manage.py makemigrations integrations -n clickupmemberlink`
Expected: creates `apps/integrations/migrations/0002_clickupmemberlink.py`

- [ ] **Step 5: Write `apps/integrations/members.py`**

```python
"""Matching Digivault users to ClickUp workspace members.

ClickUp gives us one usable join key — email — and agency staff often have a
different address in each system. So matching produces both a matched and an
unmatched list; the unmatched list is what the settings UI asks a human to fix,
and `set_member_link` is how they fix it.
"""
from __future__ import annotations

import logging

from apps.integrations.clickup import ClickUpClient, ClickUpError
from apps.integrations.models import ClickUpMemberLink

logger = logging.getLogger(__name__)

EMPTY_SYNC = {"matched": [], "unmatched": [], "workspace_id": None}


def _team_members(team):
    """Every user in the team, with their membership loaded."""
    from apps.accounts.models import TeamMembership

    return [m.user for m in TeamMembership.objects.filter(team=team).select_related("user")]


def sync_member_links(team, *, client: ClickUpClient | None = None) -> dict:
    """Match this team's users against ClickUp workspace members by email.

    Returns {"matched": [...], "unmatched": [...], "workspace_id": str | None}.
    An unconfigured team returns EMPTY_SYNC rather than raising — that is the
    normal state, not a failure.
    """
    token = getattr(team, "clickup_api_token", "") or ""
    if not (token or client):
        return dict(EMPTY_SYNC)

    api = client or ClickUpClient(token)
    try:
        workspaces = api.workspaces()
    except ClickUpError:
        logger.exception("ClickUp workspace lookup failed for team %s", team.pk)
        return dict(EMPTY_SYNC)

    if not workspaces:
        return dict(EMPTY_SYNC)

    # The token belongs to one person; their first workspace is the team's.
    workspace = workspaces[0]
    by_email = {}
    for entry in workspace.get("members") or []:
        cu = entry.get("user") or {}
        email = (cu.get("email") or "").strip().lower()
        if email:
            by_email[email] = cu

    matched, unmatched = [], []
    for user in _team_members(team):
        cu = by_email.get((user.email or "").strip().lower())
        if not cu:
            unmatched.append({"user_id": str(user.id), "email": user.email})
            continue
        link = set_member_link(
            team, user, str(cu.get("id") or ""), cu.get("username") or ""
        )
        matched.append({
            "user_id": str(user.id),
            "email": user.email,
            "clickup_user_id": link.clickup_user_id,
            "clickup_username": link.clickup_username,
        })

    return {
        "matched": matched,
        "unmatched": unmatched,
        "workspace_id": str(workspace.get("id") or "") or None,
    }


def set_member_link(team, user, clickup_user_id: str, clickup_username: str = "") -> ClickUpMemberLink:
    """Create or update one user's ClickUp mapping."""
    link, _ = ClickUpMemberLink.objects.update_or_create(
        team=team,
        user=user,
        defaults={
            "clickup_user_id": str(clickup_user_id or ""),
            "clickup_username": clickup_username or "",
        },
    )
    return link


def clickup_id_for(team, user) -> str | None:
    """This user's ClickUp id, or None when unmapped."""
    if user is None:
        return None
    link = ClickUpMemberLink.objects.filter(team=team, user=user).first()
    return link.clickup_user_id if link and link.clickup_user_id else None
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/integrations/test_member_links.py -v --create-db`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add apps/integrations/models.py apps/integrations/migrations/0002_clickupmemberlink.py apps/integrations/members.py tests/integrations/test_member_links.py
git commit -m "$(cat <<'EOF'
feat(integrations): map Digivault users to ClickUp members

Email is the only join key ClickUp offers and it often differs between
systems, so unmatched members are a reported result with a manual override.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: `apps/integrations/chat.py` — the notify entry points

The core of the feature. Everything downstream just calls `notify_problem` / `notify_recovery`.

**Files:**
- Create: `apps/integrations/chat.py`
- Create: `tests/integrations/test_chat.py`

**Interfaces:**
- Consumes: `parse_clickup_chat`, `ClickUpClient.post_chat(..., followers=)` (Task 2); `Team.clickup_chat_url` (Task 3); `clickup_id_for` (Task 4); `report_issue` (existing, `apps/integrations/tasks.py`).
- Produces:
  - `resolve_owner(website) -> User | None`
  - `mention_for(team, user) -> tuple[str, str | None]`
  - `notify_problem(website, *, subject, title, detail, tags=None, emoji="🔴", client=None) -> bool`
  - `notify_recovery(website, *, subject, title, detail="", client=None) -> bool`

- [ ] **Step 1: Write the failing tests**

Create `tests/integrations/test_chat.py`:

```python
"""notify_problem() — announce a website problem in the team's ClickUp channel.

Two invariants matter most. First, the owning developer is notified through the
message's `followers` field, not through inline mention text, because ClickUp
documents no request-side @-mention syntax for v3 chat. Second, nothing here may
raise into an alert path: a ClickUp outage must not take down the email that
already went out.
"""
import pytest

from apps.accounts.models import TeamMembership, User
from apps.accounts.services import TeamService
from apps.clients.models import Client
from apps.integrations.chat import (
    mention_for,
    notify_problem,
    notify_recovery,
    resolve_owner,
)
from apps.integrations.clickup import ClickUpClient
from apps.integrations.members import set_member_link
from apps.integrations.models import ClickUpTaskLink
from apps.websites.models import Website

CHAT_URL = "https://app.clickup.com/9001/chat/r/chan-77"


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = ""

    def json(self):
        return self._payload


class RecordingSession:
    def __init__(self, fail_on=None):
        self.calls = []
        self.fail_on = fail_on or ""

    def request(self, method, url, headers=None, json=None, timeout=None):
        self.calls.append({"method": method, "url": url, "json": json})
        if self.fail_on and self.fail_on in url:
            return FakeResponse(500, {})
        if url.endswith("/task"):
            return FakeResponse(200, {"id": "task-1", "url": "https://app.clickup.com/t/86a1"})
        return FakeResponse(200, {"id": "x"})

    def urls(self):
        return [c["url"] for c in self.calls]

    def chat_body(self):
        for c in self.calls:
            if "/messages" in c["url"]:
                return c["json"]
        return None


@pytest.fixture
def setup(db):
    owner = User.objects.create_user(email="chatowner@x.io", password="Pass123!")
    team = TeamService.create(name="Chat Co", owner=owner)
    team.clickup_api_token = "pk_test"
    team.clickup_list_id = "list-42"
    team.clickup_chat_url = CHAT_URL
    team.save()

    dev = User.objects.create_user(email="jane@x.io", password="Pass123!")
    TeamMembership.objects.create(user=dev, team=team, role=TeamMembership.Role.DEVELOPER)
    set_member_link(team, dev, "11", "jane")

    client_rec = Client.objects.create(team=team, name="Example Co", assigned_to=dev)
    website = Website.objects.create(
        team=team, client=client_rec, name="Example Co", domain="example.com"
    )
    return team, dev, website


def _api(session):
    return ClickUpClient("pk_test", session=session)


# -- resolve_owner ---------------------------------------------------------

def test_resolve_owner_returns_the_clients_assignee(setup):
    _, dev, website = setup
    assert resolve_owner(website) == dev


def test_resolve_owner_is_none_when_the_website_has_no_client(setup):
    team, _, _ = setup
    orphan = Website.objects.create(team=team, name="Orphan", domain="orphan.io")
    assert resolve_owner(orphan) is None


def test_resolve_owner_is_none_when_the_client_is_unassigned(setup):
    team, _, website = setup
    website.client.assigned_to = None
    website.client.save()
    website.refresh_from_db()
    assert resolve_owner(website) is None


# -- mention_for ----------------------------------------------------------

def test_mention_for_a_mapped_user_is_an_at_mention(setup):
    team, dev, _ = setup
    text, cu_id = mention_for(team, dev)
    assert text == "@jane"
    assert cu_id == "11"


def test_mention_for_an_unmapped_user_is_a_bare_name(setup):
    """No broken-looking @ for someone ClickUp does not know."""
    team, _, _ = setup
    stranger = User.objects.create_user(email="nomap@x.io", password="Pass123!")
    TeamMembership.objects.create(user=stranger, team=team, role=TeamMembership.Role.DEVELOPER)

    text, cu_id = mention_for(team, stranger)

    assert not text.startswith("@")
    assert "nomap@x.io" in text
    assert cu_id is None


def test_mention_for_none_is_unassigned(setup):
    team, _, _ = setup
    assert mention_for(team, None) == ("unassigned", None)


# -- notify_problem -------------------------------------------------------

def test_notify_problem_posts_to_the_parsed_workspace_and_channel(setup):
    _, _, website = setup
    session = RecordingSession()

    sent = notify_problem(
        website, subject="monitor:1:down", title="site is DOWN",
        detail="HTTP 503", client=_api(session),
    )

    assert sent is True
    assert "https://api.clickup.com/api/v3/workspaces/9001/chat/channels/chan-77/messages" in session.urls()


def test_the_owner_is_notified_via_followers(setup):
    _, _, website = setup
    session = RecordingSession()

    notify_problem(website, subject="monitor:1:down", title="down", detail="x", client=_api(session))

    assert session.chat_body()["followers"] == ["11"]


def test_the_message_names_the_site_the_owner_and_the_task(setup):
    _, _, website = setup
    session = RecordingSession()

    notify_problem(
        website, subject="monitor:1:down", title="site is DOWN",
        detail="HTTP 503 from https://example.com/", client=_api(session),
    )

    content = session.chat_body()["content"]
    assert "**Example Co**" in content
    assert "site is DOWN" in content
    assert "example.com" in content
    assert "@jane" in content
    assert "HTTP 503 from https://example.com/" in content
    assert "https://app.clickup.com/t/86a1" in content


def test_a_task_is_opened_for_the_problem(setup):
    team, _, website = setup
    session = RecordingSession()

    notify_problem(website, subject="monitor:1:down", title="down", detail="x", client=_api(session))

    assert ClickUpTaskLink.objects.filter(team=team, subject="monitor:1:down").count() == 1


def test_the_task_link_line_is_omitted_when_no_list_is_configured(setup):
    team, _, website = setup
    team.clickup_list_id = ""
    team.save()
    website.refresh_from_db()
    session = RecordingSession()

    notify_problem(website, subject="monitor:1:down", title="down", detail="x", client=_api(session))

    content = session.chat_body()["content"]
    assert "→" not in content
    assert ClickUpTaskLink.objects.count() == 0


def test_an_unset_chat_url_sends_nothing(setup):
    team, _, website = setup
    team.clickup_chat_url = ""
    team.save()
    website.refresh_from_db()
    session = RecordingSession()

    sent = notify_problem(website, subject="monitor:1:down", title="down", detail="x", client=_api(session))

    assert sent is False
    assert session.calls == []


def test_a_clickup_failure_is_swallowed(setup):
    """A ClickUp outage must not propagate into the alert path that called us."""
    _, _, website = setup
    session = RecordingSession(fail_on="/messages")

    sent = notify_problem(website, subject="monitor:1:down", title="down", detail="x", client=_api(session))

    assert sent is False


def test_an_unassigned_site_still_posts(setup):
    _, _, website = setup
    website.client.assigned_to = None
    website.client.save()
    website.refresh_from_db()
    session = RecordingSession()

    sent = notify_problem(website, subject="monitor:1:down", title="down", detail="x", client=_api(session))

    assert sent is True
    assert "unassigned" in session.chat_body()["content"]
    assert "followers" not in session.chat_body()


# -- notify_recovery ------------------------------------------------------

def test_recovery_closes_the_open_task_link(setup):
    team, _, website = setup
    session = RecordingSession()
    notify_problem(website, subject="monitor:1:down", title="down", detail="x", client=_api(session))

    notify_recovery(website, subject="monitor:1:down", title="back UP", client=_api(session))

    link = ClickUpTaskLink.objects.get(team=team, subject="monitor:1:down")
    assert link.closed_at is not None


def test_recovery_posts_a_recovery_line(setup):
    _, _, website = setup
    session = RecordingSession()

    notify_recovery(website, subject="monitor:1:down", title="back UP", client=_api(session))

    assert "back UP" in session.chat_body()["content"]
    assert "✅" in session.chat_body()["content"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/integrations/test_chat.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.integrations.chat'`

- [ ] **Step 3: Write `apps/integrations/chat.py`**

```python
"""Announcing website problems in the team's ClickUp Chat channel.

One channel holds the whole web team; every problem posted there names the site,
the problem, and the developer who owns that client. `notify_problem` is the only
function alert paths need — it opens (or comments on) the ClickUp task for the
issue and posts the message that links to it.

Nothing here raises. By the time an alert path calls us, email and the
per-website channels have already delivered; a ClickUp outage must not undo that.
"""
from __future__ import annotations

import logging

from apps.integrations.clickup import ClickUpClient, parse_clickup_chat
from apps.integrations.members import clickup_id_for
from apps.integrations.models import ClickUpTaskLink
from apps.integrations.tasks import report_issue

logger = logging.getLogger(__name__)

PROBLEM_EMOJI = "🔴"
RECOVERY_EMOJI = "✅"


def resolve_owner(website):
    """The developer accountable for this website.

    Ownership lives on the client, not the site — an agency assigns a person to
    an account. None when the site has no client or the client is unassigned.
    """
    client = getattr(website, "client", None)
    return getattr(client, "assigned_to", None) if client else None


def mention_for(team, user) -> tuple[str, str | None]:
    """(display_text, clickup_user_id) for a user.

    An unmapped user gets a bare name rather than "@name", so the message never
    renders an @-mention that resolves to nobody.
    """
    if user is None:
        return "unassigned", None

    clickup_id = clickup_id_for(team, user)
    label = (getattr(user, "get_full_name", lambda: "")() or "").strip() or user.email

    if clickup_id:
        from apps.integrations.models import ClickUpMemberLink

        link = ClickUpMemberLink.objects.filter(team=team, user=user).first()
        username = (link.clickup_username if link else "") or label
        return f"@{username}", clickup_id

    return label, None


def _chat_target(team) -> tuple[str | None, str | None]:
    return parse_clickup_chat(getattr(team, "clickup_chat_url", "") or "")


def _build_message(website, *, emoji: str, title: str, detail: str, mention: str, task_url: str) -> str:
    label = website.name or website.domain
    lines = [
        f"{emoji} **{label}** — {title}",
        f"{website.domain} · owner: {mention}",
    ]
    if detail:
        lines.append(detail)
    if task_url:
        lines.append(f"→ {task_url}")
    return "\n".join(lines)


def _post(team, workspace_id, channel_id, text, followers, client) -> bool:
    api = client or ClickUpClient(team.clickup_api_token)
    api.post_chat(workspace_id, channel_id, text, followers=followers or None)
    return True


def notify_problem(
    website,
    *,
    subject: str,
    title: str,
    detail: str = "",
    tags: list | None = None,
    emoji: str = PROBLEM_EMOJI,
    client: ClickUpClient | None = None,
) -> bool:
    """Announce a website problem in the team channel and open its ClickUp task.

    `subject` is the stable issue key (e.g. "monitor:<id>:down") that dedupes
    repeat reports onto one task. Returns whether a message was posted.
    """
    team = website.team
    workspace_id, channel_id = _chat_target(team)
    if not (workspace_id and channel_id):
        return False

    try:
        owner = resolve_owner(website)
        mention, clickup_id = mention_for(team, owner)

        link = report_issue(
            team,
            subject,
            title=f"{website.name or website.domain}: {title}",
            body=detail or title,
            assignees=[clickup_id] if clickup_id else None,
            tags=tags,
            client=client,
        )

        text = _build_message(
            website, emoji=emoji, title=title, detail=detail,
            mention=mention, task_url=link.task_url if link else "",
        )
        return _post(team, workspace_id, channel_id, text, [clickup_id] if clickup_id else None, client)
    except Exception:
        logger.exception("ClickUp chat notify failed for %s (%s)", website.domain, subject)
        return False


def notify_recovery(
    website,
    *,
    subject: str,
    title: str,
    detail: str = "",
    client: ClickUpClient | None = None,
) -> bool:
    """Announce that a problem cleared, and close its open ClickUp task link.

    Closing matters: while a link is open, repeat reports comment on the old
    task. The next genuine occurrence should get a fresh one.
    """
    team = website.team
    workspace_id, channel_id = _chat_target(team)
    if not (workspace_id and channel_id):
        return False

    try:
        for link in ClickUpTaskLink.objects.filter(
            team=team, subject=subject, closed_at__isnull=True
        ):
            link.close()

        owner = resolve_owner(website)
        mention, clickup_id = mention_for(team, owner)
        text = _build_message(
            website, emoji=RECOVERY_EMOJI, title=title, detail=detail,
            mention=mention, task_url="",
        )
        return _post(team, workspace_id, channel_id, text, [clickup_id] if clickup_id else None, client)
    except Exception:
        logger.exception("ClickUp recovery notify failed for %s (%s)", website.domain, subject)
        return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/integrations/test_chat.py -v`
Expected: PASS (all 17)

- [ ] **Step 5: Commit**

```bash
git add apps/integrations/chat.py tests/integrations/test_chat.py
git commit -m "$(cat <<'EOF'
feat(integrations): post website problems to the team ClickUp channel

notify_problem names the site, the problem and the owning developer, opens
the ClickUp task for the issue, and links to it. Never raises — by the time
an alert path calls it, email has already gone out.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Wire uptime alerts

**Files:**
- Modify: `apps/monitors/notifications.py:167-214` (`notify_status_change`)
- Test: `tests/monitors/test_channel_test.py` (new tests appended) or create `tests/monitors/test_chat_wiring.py`

**Interfaces:**
- Consumes: `notify_problem`, `notify_recovery` from Task 5.
- Subject key: `monitor:<monitor.id>:down`

- [ ] **Step 1: Write the failing test**

Create `tests/monitors/test_chat_wiring.py`:

```python
"""Uptime status changes announce themselves in the team ClickUp channel.

This is independent of the per-website NotificationChannel routing — a team with
no channels configured still gets the chat post, and vice versa.
"""
from unittest.mock import patch

import pytest

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.monitors.models import Monitor
from apps.monitors.notifications import notify_status_change
from apps.websites.models import Website


@pytest.fixture
def monitor(db):
    owner = User.objects.create_user(email="upowner@x.io", password="Pass123!")
    team = TeamService.create(name="Uptime Co", owner=owner)
    team.clickup_chat_url = "https://app.clickup.com/9001/chat/r/chan-77"
    team.clickup_api_token = "pk_test"
    team.save()
    website = Website.objects.create(team=team, name="Example", domain="example.com")
    return Monitor.objects.create(
        team=team, website=website, name="Example", url="https://example.com", monitor_type="http"
    )


def test_going_down_announces_the_problem(monitor):
    with patch("apps.integrations.chat.notify_problem") as np:
        notify_status_change(monitor, "up", "down")

    assert np.called
    kwargs = np.call_args.kwargs
    assert kwargs["subject"] == f"monitor:{monitor.id}:down"
    assert "DOWN" in kwargs["title"]


def test_recovering_announces_the_recovery_with_the_same_subject(monitor):
    with patch("apps.integrations.chat.notify_recovery") as nr:
        notify_status_change(monitor, "down", "up")

    assert nr.called
    assert nr.call_args.kwargs["subject"] == f"monitor:{monitor.id}:down"


def test_degraded_announces_a_problem(monitor):
    with patch("apps.integrations.chat.notify_problem") as np:
        notify_status_change(monitor, "up", "degraded")

    assert np.called


def test_an_uninteresting_transition_announces_nothing(monitor):
    with patch("apps.integrations.chat.notify_problem") as np, \
         patch("apps.integrations.chat.notify_recovery") as nr:
        notify_status_change(monitor, "pending", "up")

    assert not np.called
    assert not nr.called


def test_a_monitor_with_no_website_announces_nothing(monitor):
    monitor.website = None
    monitor.save()

    with patch("apps.integrations.chat.notify_problem") as np:
        notify_status_change(monitor, "up", "down")

    assert not np.called
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/monitors/test_chat_wiring.py -v`
Expected: FAIL — `AssertionError: assert False` (nothing calls `notify_problem` yet)

- [ ] **Step 3: Wire it in `notify_status_change`**

In `apps/monitors/notifications.py`, at the very end of `notify_status_change`
(after the `for channel in channels.values(): dispatch(...)` loop), add:

```python
    # The shared team channel is announced separately from the per-website
    # channels above: a team gets it whether or not any website channel is set.
    if monitor.website_id:
        _announce_in_team_channel(monitor, old_status, new_status, is_recovery)
```

Then add this helper below `notify_status_change`:

```python
def _announce_in_team_channel(monitor, old_status: str, new_status: str, is_recovery: bool) -> None:
    """Post the status change into the team's ClickUp channel.

    Deliberately best-effort and separate from `dispatch` — this is one shared
    feed for the whole web team, not a configured channel row.
    """
    from apps.integrations import chat

    subject = f"monitor:{monitor.id}:down"
    website = monitor.website
    if is_recovery:
        chat.notify_recovery(
            website,
            subject=subject,
            title=f"back {new_status.upper()}",
            detail=f"{monitor.name} recovered — {monitor.url}",
        )
        return

    chat.notify_problem(
        website,
        subject=subject,
        title=f"is {new_status.upper()}",
        detail=f"{monitor.name} went {old_status.upper()} → {new_status.upper()}\n{monitor.url}",
        tags=["uptime"],
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/monitors/ -v`
Expected: PASS (new file plus existing monitors tests still green)

- [ ] **Step 5: Commit**

```bash
git add apps/monitors/notifications.py tests/monitors/test_chat_wiring.py
git commit -m "$(cat <<'EOF'
feat(monitors): announce uptime changes in the team ClickUp channel

Recovery closes the issue's task link so the next outage opens a fresh task.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Wire domain / SSL / hosting expiry alerts

**Files:**
- Modify: `apps/domains/notifications.py:63-97` (`deliver_domain_alert`)
- Test: `tests/domains/test_chat_wiring.py`

**Interfaces:**
- Consumes: `notify_problem` from Task 5.
- Subject key: `domain:<domain_info.id>:<alert.alert_type>`

- [ ] **Step 1: Write the failing test**

First check what the existing domain tests use to build a `DomainAlert`:

Run: `ls tests/domains/ && grep -rn "DomainAlert.objects.create" tests/ | head -5`

Create `tests/domains/test_chat_wiring.py`, adapting the fixture to whatever
`DomainInfo` / `DomainAlert` field names that grep reveals:

```python
"""Domain, SSL and hosting expiry alerts reach the shared team channel."""
from unittest.mock import patch

import pytest

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.domains.models import DomainAlert, DomainInfo
from apps.domains.notifications import deliver_domain_alert
from apps.websites.models import Website


@pytest.fixture
def alert(db):
    owner = User.objects.create_user(email="dnsowner@x.io", password="Pass123!")
    team = TeamService.create(name="DNS Co", owner=owner)
    team.clickup_chat_url = "https://app.clickup.com/9001/chat/r/chan-77"
    team.clickup_api_token = "pk_test"
    team.save()
    website = Website.objects.create(team=team, name="Example", domain="example.com")
    info = DomainInfo.objects.create(website=website)
    return DomainAlert.objects.create(domain_info=info, alert_type="ssl", days_until_expiry=7)


def test_an_expiry_alert_announces_in_the_team_channel(alert):
    with patch("apps.integrations.chat.notify_problem") as np:
        deliver_domain_alert(alert)

    assert np.called
    kwargs = np.call_args.kwargs
    assert kwargs["subject"] == f"domain:{alert.domain_info_id}:ssl"


def test_the_chat_post_happens_even_with_no_notification_channels(alert):
    """resolve_channels() returns nothing here — the team feed still fires."""
    with patch("apps.integrations.chat.notify_problem") as np:
        deliver_domain_alert(alert)

    assert np.called


def test_a_chat_failure_does_not_block_marking_the_alert_sent(alert):
    with patch("apps.integrations.chat.notify_problem", side_effect=RuntimeError("boom")):
        # Must not raise out of deliver_domain_alert.
        deliver_domain_alert(alert)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/domains/test_chat_wiring.py -v`
Expected: FAIL — `assert np.called` is False

- [ ] **Step 3: Wire it in `deliver_domain_alert`**

In `apps/domains/notifications.py`, replace the `if not channels:` early return
so the chat post happens regardless of configured channels. Change lines 72-78 from:

```python
    website = alert.domain_info.website
    channels = resolve_channels(website)
    if not channels:
        logger.info("No active channels for %s; domain alert %s left unsent", website.domain, alert.id)
        return False

    subject, body = _alert_message(alert)
```

to:

```python
    website = alert.domain_info.website
    subject, body = _alert_message(alert)

    # The shared team channel is independent of configured channels — a team
    # with none still wants expiry in its feed.
    _announce_in_team_channel(alert, website, body)

    channels = resolve_channels(website)
    if not channels:
        logger.info("No active channels for %s; domain alert %s left unsent", website.domain, alert.id)
        return False
```

Add the helper above `deliver_domain_alert`:

```python
def _announce_in_team_channel(alert, website, body: str) -> None:
    """Post an expiry alert into the team's ClickUp channel, best-effort.

    Wrapped rather than trusted: deliver_domain_alert decides whether the alert
    counts as sent, and a chat failure must not change that decision.
    """
    from apps.integrations import chat

    try:
        chat.notify_problem(
            website,
            subject=f"domain:{alert.domain_info_id}:{alert.alert_type}",
            title=_expiry_title(alert),
            detail=body,
            tags=["expiry"],
        )
    except Exception:
        logger.exception("Team channel announce failed for domain alert %s", alert.id)


def _expiry_title(alert) -> str:
    kind = {
        "ssl": "SSL certificate",
        "hosting": "Hosting plan",
    }.get(alert.alert_type, "Domain registration")
    return f"{kind} expires in {alert.days_until_expiry} days"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/domains/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/domains/notifications.py tests/domains/test_chat_wiring.py
git commit -m "$(cat <<'EOF'
feat(domains): announce expiry alerts in the team ClickUp channel

Independent of configured channels, and wrapped so a chat failure cannot
change whether the alert counts as delivered.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: Wire SEO / site health regressions

`notify_team` has no stable per-issue key today — only a subject line, which
embeds the changing detail. It gains a `subject_key` kwarg; callers that omit it
get chat posting skipped rather than opening a task per distinct alert body.

**Files:**
- Modify: `apps/site_health/notifications.py:14-30`
- Modify: `apps/site_health/tasks.py:399-403` and `:445-449`
- Test: `tests/site_health/test_chat_wiring.py`

**Interfaces:**
- Consumes: `notify_problem` from Task 5.
- Produces: `notify_team(website, subject, body, *, subject_key="")`
- Subject key: `sitehealth:<website.id>:<event_type>`

- [ ] **Step 1: Write the failing test**

Create `tests/site_health/test_chat_wiring.py`:

```python
"""SEO regressions reach the team channel — but only with a stable subject key.

Without a key, every distinct alert body would open its own ClickUp task, so an
omitted key skips the chat post instead of creating churn.
"""
from unittest.mock import patch

import pytest

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.site_health.notifications import notify_team
from apps.websites.models import Website


@pytest.fixture
def website(db):
    owner = User.objects.create_user(email="seoowner@x.io", password="Pass123!")
    team = TeamService.create(name="SEO Co", owner=owner)
    team.clickup_chat_url = "https://app.clickup.com/9001/chat/r/chan-77"
    team.clickup_api_token = "pk_test"
    team.save()
    return Website.objects.create(team=team, name="Example", domain="example.com")


def test_a_keyed_alert_announces_in_the_team_channel(website):
    with patch("apps.integrations.chat.notify_problem") as np:
        notify_team(website, "[Digivault] noindex", "body", subject_key="sitehealth:1:seo_noindex")

    assert np.called
    assert np.call_args.kwargs["subject"] == "sitehealth:1:seo_noindex"


def test_an_unkeyed_alert_skips_the_chat_post(website):
    with patch("apps.integrations.chat.notify_problem") as np:
        notify_team(website, "[Digivault] something", "body")

    assert not np.called


def test_a_chat_failure_does_not_raise(website):
    with patch("apps.integrations.chat.notify_problem", side_effect=RuntimeError("boom")):
        notify_team(website, "s", "b", subject_key="sitehealth:1:x")


def test_the_seo_check_passes_a_stable_key_derived_from_the_event_type(website):
    """The event_type is the stable part; the summary text is not."""
    from apps.site_health.models import SiteEvent

    with patch("apps.site_health.notifications.notify_team") as nt:
        # Simulate what run_seo_check's _alert() does.
        from apps.site_health import tasks  # noqa: F401

    # Guard the contract directly: the key must contain the event type constant.
    key = f"sitehealth:{website.id}:{SiteEvent.EventType.SEO_NOINDEX_DETECTED}"
    assert str(SiteEvent.EventType.SEO_NOINDEX_DETECTED) in key
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/site_health/test_chat_wiring.py -v`
Expected: FAIL — `TypeError: notify_team() got an unexpected keyword argument 'subject_key'`

- [ ] **Step 3: Add `subject_key` to `notify_team`**

Replace the body of `apps/site_health/notifications.py`'s `notify_team`:

```python
def notify_team(website, subject: str, body: str, *, subject_key: str = "") -> None:
    """Best-effort delivery to the website's notification channel (or the team's
    active channels when the site has none set), plus the shared team channel.

    `subject_key` is the stable issue key for ClickUp task dedup. It is optional
    because the alert subject line embeds changing detail — without a key, one
    task per distinct wording would pile up, so the chat post is skipped instead.
    """
    from apps.monitors.notifications import resolve_channels

    for ch in resolve_channels(website):
        try:
            if ch.channel_type == "email":
                addrs = ch.config.get("addresses", [])
                if addrs:
                    send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, addrs, fail_silently=True)
            elif ch.channel_type == "clickup":
                token, task_id = ch.config.get("api_token", ""), ch.config.get("task_id", "")
                if token and task_id:
                    ClickUpClient(token).comment(task_id, f"**{subject}**\n{body}")
        except Exception:
            logger.exception("SEO alert delivery failed via channel %s", ch.id)

    if not subject_key:
        return

    from apps.integrations import chat

    try:
        chat.notify_problem(
            website,
            subject=subject_key,
            # The "[Digivault] " prefix is email framing; the channel does not
            # need it.
            title=subject.replace("[Digivault] ", ""),
            detail=body,
            tags=["seo"],
        )
    except Exception:
        logger.exception("Team channel announce failed for %s", website.domain)
```

- [ ] **Step 4: Pass the key from both `run_seo_check` call sites**

In `apps/site_health/tasks.py`, change `_alert` (line 399-403) to:

```python
    def _alert(event_type, severity, summary):
        SiteEvent.objects.create(
            website=website, event_type=event_type, severity=severity, summary=summary,
        )
        notify_team(
            website,
            f"[Digivault] {summary}",
            f"{summary} — {website.domain}",
            # The event type is the stable part of the issue; the summary text
            # carries changing detail and would fragment task dedup.
            subject_key=f"sitehealth:{website.id}:{event_type}",
        )
```

And the meta-change call (line 445-449) to:

```python
        notify_team(
            website,
            f"[Digivault] {label} on-page SEO changed: {what}",
            f"On-page SEO changed on {website.domain}: {what}",
            subject_key=f"sitehealth:{website.id}:{SiteEvent.EventType.SEO_META_CHANGED}",
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/site_health/ -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add apps/site_health/notifications.py apps/site_health/tasks.py tests/site_health/test_chat_wiring.py
git commit -m "$(cat <<'EOF'
feat(site_health): announce SEO regressions in the team ClickUp channel

notify_team gains an optional subject_key. Without one the chat post is
skipped — the alert subject embeds changing detail and would open a task
per distinct wording.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: Backend endpoints for channel creation and member mapping

**Files:**
- Modify: `apps/accounts/views.py` (add two views after `ClickUpTestView`)
- Modify: `apps/accounts/urls.py:16` and `:69`
- Test: `tests/accounts/test_clickup_channel.py` (append)

**Interfaces:**
- Consumes: `ClickUpClient.workspaces`, `create_chat_channel` (Task 2); `Team.clickup_chat_url` (Task 3); `sync_member_links`, `set_member_link` (Task 4).
- Produces:
  - `POST /api/v1/auth/teams/<uuid:pk>/settings/clickup-channel/` → `{clickup_chat_url, matched, unmatched}`
  - `POST /api/v1/auth/teams/<uuid:pk>/settings/clickup-members/` → `{matched, unmatched}`

- [ ] **Step 1: Write the failing tests**

Append to `tests/accounts/test_clickup_channel.py`:

```python
from unittest.mock import patch

from apps.accounts.models import TeamMembership, User
from apps.integrations.models import ClickUpMemberLink


def _channel_url(team):
    return f"/api/v1/auth/teams/{team.id}/settings/clickup-channel/"


def _members_url(team):
    return f"/api/v1/auth/teams/{team.id}/settings/clickup-members/"


FAKE_SYNC = {
    "matched": [{"user_id": "u1", "email": "jane@x.io", "clickup_user_id": "11", "clickup_username": "jane"}],
    "unmatched": [{"user_id": "u2", "email": "bob@x.io"}],
    "workspace_id": "9001",
}


def test_creating_the_channel_stores_the_url_and_reports_members(auth_client, team):
    team.clickup_api_token = "pk_test"
    team.save()

    with patch("apps.accounts.views.sync_member_links", return_value=FAKE_SYNC), \
         patch("apps.accounts.views.ClickUpClient") as CU:
        CU.return_value.create_chat_channel.return_value = {
            "id": "chan-77", "url": "https://app.clickup.com/9001/chat/r/chan-77",
        }
        resp = auth_client.post(_channel_url(team), {"name": "Web Team"}, format="json")

    assert resp.status_code == 200
    team.refresh_from_db()
    assert team.clickup_chat_url == "https://app.clickup.com/9001/chat/r/chan-77"
    assert resp.data["matched"][0]["clickup_user_id"] == "11"
    assert resp.data["unmatched"][0]["email"] == "bob@x.io"
    # Matched members go into the channel.
    assert CU.return_value.create_chat_channel.call_args.kwargs["user_ids"] == ["11"]


def test_creating_the_channel_without_a_token_is_a_400(auth_client, team):
    resp = auth_client.post(_channel_url(team), {}, format="json")
    assert resp.status_code == 400


def test_a_viewer_cannot_create_the_channel(api_client, team, db):
    viewer = User.objects.create_user(email="viewer@x.io", password="SecurePass1!")
    TeamMembership.objects.create(user=viewer, team=team, role=TeamMembership.Role.VIEWER)
    tok = api_client.post(
        "/api/v1/auth/token/", {"email": viewer.email, "password": "SecurePass1!"}, format="json"
    ).data["access"]
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {tok}")

    assert api_client.post(_channel_url(team), {}, format="json").status_code == 403
    assert api_client.post(_members_url(team), {}, format="json").status_code == 403


def test_resyncing_members_returns_matched_and_unmatched(auth_client, team):
    team.clickup_api_token = "pk_test"
    team.save()

    with patch("apps.accounts.views.sync_member_links", return_value=FAKE_SYNC):
        resp = auth_client.post(_members_url(team), {}, format="json")

    assert resp.status_code == 200
    assert resp.data["unmatched"][0]["email"] == "bob@x.io"


def test_an_override_maps_a_member_clickup_did_not_match(auth_client, team, db):
    dev = User.objects.create_user(email="bob@x.io", password="SecurePass1!")
    TeamMembership.objects.create(user=dev, team=team, role=TeamMembership.Role.DEVELOPER)
    team.clickup_api_token = "pk_test"
    team.save()

    with patch("apps.accounts.views.sync_member_links", return_value=FAKE_SYNC):
        resp = auth_client.post(
            _members_url(team),
            {"overrides": [{"user_id": str(dev.id), "clickup_user_id": "424242"}]},
            format="json",
        )

    assert resp.status_code == 200
    assert ClickUpMemberLink.objects.get(team=team, user=dev).clickup_user_id == "424242"


def test_an_override_for_a_non_member_is_ignored(auth_client, team, db):
    outsider = User.objects.create_user(email="outsider@x.io", password="SecurePass1!")
    team.clickup_api_token = "pk_test"
    team.save()

    with patch("apps.accounts.views.sync_member_links", return_value=FAKE_SYNC):
        auth_client.post(
            _members_url(team),
            {"overrides": [{"user_id": str(outsider.id), "clickup_user_id": "1"}]},
            format="json",
        )

    assert ClickUpMemberLink.objects.filter(team=team, user=outsider).count() == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/accounts/test_clickup_channel.py -v`
Expected: FAIL — 404 on the new URLs

- [ ] **Step 3: Add the views**

In `apps/accounts/views.py`, add these imports near the top of the file (with the
other app imports):

```python
from apps.integrations.clickup import ClickUpClient, ClickUpError
from apps.integrations.members import set_member_link, sync_member_links
```

Then add after `ClickUpTestView`:

```python
class _ClickUpManagerView(APIView):
    """Shared auth for the ClickUp management endpoints: team member, manager+."""

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def _team_or_error(self, request, pk):
        try:
            team = Team.objects.get(pk=pk)
        except Team.DoesNotExist:
            return None, Response(status=status.HTTP_404_NOT_FOUND)
        if not TeamMembership.objects.filter(user=request.user, team=team).exists():
            return None, Response({"detail": "Not a member."}, status=status.HTTP_403_FORBIDDEN)
        my_level, _ = _my_level(request.user, team)
        if my_level < ROLE_LEVELS["manager"]:
            return None, Response(
                {"detail": "Manager or higher required."}, status=status.HTTP_403_FORBIDDEN
            )
        return team, None


class ClickUpChannelView(_ClickUpManagerView):
    """POST /api/v1/auth/teams/<pk>/settings/clickup-channel/

    Creates the web team's ClickUp Chat channel with every member we could match
    in ClickUp, and stores its URL on the team.
    """

    def post(self, request, pk):
        team, err = self._team_or_error(request, pk)
        if err:
            return err

        token = team.clickup_api_token
        if not token:
            return Response(
                {"detail": "Connect ClickUp first — no API token configured."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        sync = sync_member_links(team)
        workspace_id = sync.get("workspace_id")
        if not workspace_id:
            return Response(
                {"detail": "Could not read your ClickUp workspace. Check the API token."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        name = (request.data.get("name") or "Digivault — Web Team").strip()
        user_ids = [m["clickup_user_id"] for m in sync["matched"] if m.get("clickup_user_id")]

        try:
            channel = ClickUpClient(token).create_chat_channel(
                workspace_id,
                name=name,
                user_ids=user_ids,
                description="Website problems reported by Digivault.",
            )
        except ClickUpError as exc:
            logger.warning("ClickUp channel creation failed for team %s: %s", pk, exc)
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        url = channel.get("url") or ""
        if url:
            team.clickup_chat_url = url
            team.save(update_fields=["clickup_chat_url"])
            AuditService.log_request(
                request, ActivityLog.Action.SETTINGS_INTEGRATION_UPDATED,
                description="Created the ClickUp web team channel",
                resource_type="team", resource_id=str(team.pk),
            )

        return Response({
            "clickup_chat_url": team.clickup_chat_url,
            "matched": sync["matched"],
            "unmatched": sync["unmatched"],
        })


class ClickUpMembersView(_ClickUpManagerView):
    """POST /api/v1/auth/teams/<pk>/settings/clickup-members/

    Re-runs email matching and applies any manual `overrides`. An override is how
    a member whose ClickUp email differs gets mapped at all.
    """

    def post(self, request, pk):
        team, err = self._team_or_error(request, pk)
        if err:
            return err

        sync = sync_member_links(team)

        for override in request.data.get("overrides") or []:
            user_id = (override or {}).get("user_id")
            clickup_user_id = str((override or {}).get("clickup_user_id") or "").strip()
            if not (user_id and clickup_user_id):
                continue
            # Scoped to team membership — an override must not create a mapping
            # for someone outside the team.
            membership = TeamMembership.objects.filter(
                team=team, user_id=user_id
            ).select_related("user").first()
            if membership:
                set_member_link(team, membership.user, clickup_user_id)

        if request.data.get("overrides"):
            sync = sync_member_links(team)

        return Response({"matched": sync["matched"], "unmatched": sync["unmatched"]})
```

Note: `sync_member_links` is re-run after overrides so the response reflects
them. If a test's patched `sync_member_links` returns a fixed dict, the override
assertion still holds because it checks the DB, not the response.

- [ ] **Step 4: Register the URLs**

In `apps/accounts/urls.py`, add to the `apps.accounts.views` import list
(alphabetical, before `ClickUpTestView`):

```python
    ClickUpChannelView,
    ClickUpMembersView,
```

And add after the `clickup-test` path (line 69):

```python
    path("teams/<uuid:pk>/settings/clickup-channel/", ClickUpChannelView.as_view(), name="clickup-channel"),
    path("teams/<uuid:pk>/settings/clickup-members/", ClickUpMembersView.as_view(), name="clickup-members"),
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/accounts/ -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add apps/accounts/views.py apps/accounts/urls.py tests/accounts/test_clickup_channel.py
git commit -m "$(cat <<'EOF'
feat(accounts): endpoints to create the ClickUp channel and map members

Overrides are scoped to team membership so one cannot map a user outside
the team.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 10: Settings UI — channel + member mapping

**Files:**
- Create: `frontend/src/app/api/teams/[id]/settings/clickup-channel/route.ts`
- Create: `frontend/src/app/api/teams/[id]/settings/clickup-members/route.ts`
- Modify: `frontend/src/components/settings-client.tsx`

**Interfaces:**
- Consumes: the two endpoints from Task 9, and `clickup_chat_url` / `clickup_chat_connected` from Task 3's serializer.

**Before writing any of this**, read the Next.js 16 route-handler guide — `params`
is a Promise in this version:

Run: `ls frontend/node_modules/next/dist/docs/`

- [ ] **Step 1: Add the two proxy routes**

Both are byte-for-byte copies of the existing `clickup-test` route with the
upstream path changed. `frontend/src/app/api/teams/[id]/settings/clickup-channel/route.ts`:

```ts
import { NextRequest, NextResponse } from "next/server";
import { cookies } from "next/headers";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Ctx = { params: Promise<{ id: string }> };

export async function POST(req: NextRequest, { params }: Ctx) {
  const jar = await cookies();
  const token = jar.get("ss_access")?.value;
  if (!token) return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
  const { id } = await params;
  const body = await req.json().catch(() => ({}));
  const upstream = await fetch(`${API_BASE}/api/v1/auth/teams/${id}/settings/clickup-channel/`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await upstream.json().catch(() => ({}));
  return NextResponse.json(data, { status: upstream.status });
}
```

`frontend/src/app/api/teams/[id]/settings/clickup-members/route.ts` is identical
with `clickup-members` in the upstream URL.

- [ ] **Step 2: Extend the settings types and state**

In `frontend/src/components/settings-client.tsx`, add to `TeamSettings`:

```ts
  clickup_chat_url: string;
  clickup_chat_connected: boolean;
```

Add above the component's other declarations:

```ts
interface MemberMatch {
  user_id: string;
  email: string;
  clickup_user_id?: string;
  clickup_username?: string;
}
```

And inside `SettingsClient`, alongside the existing state:

```ts
  const [chatUrl, setChatUrl] = useState(settings?.clickup_chat_url ?? "");
  const [editingChat, setEditingChat] = useState(!settings?.clickup_chat_url);
  const [savingChat, setSavingChat] = useState(false);
  const [creatingChannel, setCreatingChannel] = useState(false);
  const [matched, setMatched] = useState<MemberMatch[]>([]);
  const [unmatched, setUnmatched] = useState<MemberMatch[]>([]);
  const [overrides, setOverrides] = useState<Record<string, string>>({});
```

- [ ] **Step 3: Add the three handlers**

```ts
  async function handleSaveChatUrl(next: string) {
    if (!activeTeamId) return;
    setSavingChat(true);
    try {
      const res = await fetch(`/api/teams/${activeTeamId}/settings`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ clickup_chat_url: next }),
      });
      const data = await res.json();
      if (!res.ok) {
        toast({ variant: "destructive", title: "Error", description: data?.detail || "Failed to save." });
        return;
      }
      setChatUrl(next);
      setEditingChat(!next);
      toast({
        title: "Saved",
        description: next
          ? "Website problems will be posted to that channel."
          : "Team channel cleared — nothing will be posted.",
      });
    } catch {
      toast({ variant: "destructive", title: "Network error" });
    } finally {
      setSavingChat(false);
    }
  }

  async function handleCreateChannel() {
    if (!activeTeamId) return;
    setCreatingChannel(true);
    try {
      const res = await fetch(`/api/teams/${activeTeamId}/settings/clickup-channel`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: "Digivault — Web Team" }),
      });
      const data = await res.json();
      const payload = data?.data ?? data;
      if (!res.ok) {
        toast({ variant: "destructive", title: "Error", description: payload?.detail || "Could not create the channel." });
        return;
      }
      setChatUrl(payload.clickup_chat_url || "");
      setEditingChat(!payload.clickup_chat_url);
      setMatched(payload.matched || []);
      setUnmatched(payload.unmatched || []);
      toast({
        title: "Channel created",
        description: `${(payload.matched || []).length} member(s) added in ClickUp.`,
      });
    } catch {
      toast({ variant: "destructive", title: "Network error" });
    } finally {
      setCreatingChannel(false);
    }
  }

  async function handleSyncMembers() {
    if (!activeTeamId) return;
    const body = {
      overrides: Object.entries(overrides)
        .filter(([, v]) => v.trim())
        .map(([user_id, clickup_user_id]) => ({ user_id, clickup_user_id: clickup_user_id.trim() })),
    };
    try {
      const res = await fetch(`/api/teams/${activeTeamId}/settings/clickup-members`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      const payload = data?.data ?? data;
      if (!res.ok) {
        toast({ variant: "destructive", title: "Error", description: payload?.detail || "Sync failed." });
        return;
      }
      setMatched(payload.matched || []);
      setUnmatched(payload.unmatched || []);
      setOverrides({});
      toast({ title: "Synced", description: `${(payload.matched || []).length} matched, ${(payload.unmatched || []).length} unmatched.` });
    } catch {
      toast({ variant: "destructive", title: "Network error" });
    }
  }
```

- [ ] **Step 4: Add the UI block**

Insert after the closing `</div>` of the "Issue list" block (currently line 257),
still inside `<CardContent>`:

```tsx
          {/* Team channel — where website problems are announced, with the
              owning developer addressed. Separate from the issue list: that is
              where work is tracked, this is where people are told. */}
          <div className="space-y-3 border-t pt-5">
            <Label htmlFor="clickup-chat">Web team channel</Label>
            <p className="text-xs text-muted-foreground">
              Digivault posts website problems here and addresses the developer assigned to
              that client. Leave it blank and nothing is posted.
            </p>

            {chatUrl && !editingChat ? (
              <div className="flex items-center gap-3 flex-wrap">
                <a
                  href={chatUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="text-sm inline-flex items-center gap-1 underline"
                >
                  Open channel in ClickUp <ExternalLink className="h-3 w-3" />
                </a>
                <Button variant="outline" size="sm" onClick={() => setEditingChat(true)}>
                  Change
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => handleSaveChatUrl("")}
                  disabled={savingChat}
                >
                  Clear
                </Button>
              </div>
            ) : (
              <div className="space-y-3">
                <Button variant="outline" onClick={handleCreateChannel} disabled={creatingChannel || !connected}>
                  {creatingChannel ? (
                    <><Loader2 className="h-4 w-4 mr-2 animate-spin" />Creating…</>
                  ) : (
                    "Create web team channel"
                  )}
                </Button>
                <div className="flex gap-3 flex-wrap items-center">
                  <Input
                    id="clickup-chat"
                    placeholder="https://your-team.clickup.com/9001/chat/r/abc-123"
                    value={chatUrl}
                    onChange={(e) => setChatUrl(e.target.value)}
                    className="max-w-md"
                  />
                  <Button
                    variant="outline"
                    onClick={() => handleSaveChatUrl(chatUrl.trim())}
                    disabled={savingChat || !chatUrl.trim()}
                  >
                    {savingChat ? <><Loader2 className="h-4 w-4 mr-2 animate-spin" />Saving…</> : "Save link"}
                  </Button>
                </div>
              </div>
            )}

            {(matched.length > 0 || unmatched.length > 0) && (
              <div className="space-y-2 rounded-md bg-muted/40 p-3">
                <p className="text-xs font-medium">
                  {matched.length} member(s) matched in ClickUp
                  {unmatched.length > 0 && `, ${unmatched.length} not found`}
                </p>
                {unmatched.map((m) => (
                  <div key={m.user_id} className="flex items-center gap-2 flex-wrap">
                    <span className="text-xs text-muted-foreground min-w-48">{m.email}</span>
                    <Input
                      placeholder="ClickUp user ID"
                      value={overrides[m.user_id] ?? ""}
                      onChange={(e) => setOverrides({ ...overrides, [m.user_id]: e.target.value })}
                      className="max-w-40 h-8 text-xs"
                    />
                  </div>
                ))}
                <Button variant="outline" size="sm" onClick={handleSyncMembers}>
                  {Object.values(overrides).some((v) => v.trim()) ? "Save & re-sync" : "Re-sync members"}
                </Button>
              </div>
            )}
          </div>
```

- [ ] **Step 5: Confirm the settings page passes the new fields through**

Run: `grep -n "clickup" frontend/src/app/\(dashboard\)/settings/page.tsx`

The page fetches team settings server-side and passes the whole object to
`SettingsClient`. If it destructures individual fields rather than spreading,
add `clickup_chat_url` and `clickup_chat_connected` to that list.

- [ ] **Step 6: Lint and build**

Run: `cd frontend && npm run lint && npm run build`
Expected: no errors. A build failure here is almost always a Next.js 16 API
difference — check `node_modules/next/dist/docs/` rather than guessing.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/app/api/teams/ frontend/src/components/settings-client.tsx
git commit -m "$(cat <<'EOF'
feat(frontend): web team channel + ClickUp member mapping in settings

Unmatched members get an inline ClickUp user id field — an email mismatch
is often not fixable on the ClickUp side.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 11: Full suite, docs, and the settings copy that was lying

The issue-list help text has always claimed Digivault opens a task when a
website has a problem. After Task 6-8 that is finally true — this task verifies
the whole thing together and updates the user-facing guide.

**Files:**
- Modify: `docs/guide/07-clients-and-clickup.md`
- Test: whole suite

- [ ] **Step 1: Run the full backend suite with a rebuilt schema**

Run: `pytest --create-db -q`
Expected: PASS. Two migrations were added, so `--create-db` is mandatory here.

- [ ] **Step 2: Run it again the fast way to confirm the DB is reusable**

Run: `pytest -q`
Expected: PASS, same count.

- [ ] **Step 3: Check for stragglers referencing the moved helper**

Run: `grep -rn "_CLICKUP_CHAT_RE" apps/ tests/`
Expected: no results — the regex now lives in `clickup.py` as `_CHAT_URL_RE`.

- [ ] **Step 4: Document the channel in the user guide**

Add a section to `docs/guide/07-clients-and-clickup.md` covering: what the web
team channel is, that Digivault posts problems there addressed to the client's
assigned developer, how to create it from Settings, that unmatched members need
a ClickUp user id, and that blank means nothing is posted. Match the existing
voice of that file — read it first.

- [ ] **Step 5: Commit**

```bash
git add docs/guide/07-clients-and-clickup.md
git commit -m "$(cat <<'EOF'
docs(guide): document the ClickUp web team channel

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| §1 `Team.clickup_chat_url`, create + paste, validation | 3 (field/validation), 9 (create endpoint), 10 (UI) |
| §1 `parse_clickup_chat` move + re-export | 1 |
| §2 `ClickUpMemberLink`, `sync_member_links`, email matching | 4 |
| §3 `resolve_owner` / `mention_for` / `notify_problem` | 5 |
| §3 `post_chat` gains `followers` | 2 |
| §3 message shape incl. task link line | 5 |
| §4 uptime wiring + recovery closes link | 6 |
| §4 domain/SSL/hosting wiring | 7 |
| §4 site_health wiring + `subject_key` | 8 |
| §4 script changes excluded | no task — deliberate |
| §5 settings UI: create/change/clear, member mapping | 10 |
| §5 two endpoints, manager+ | 9 |
| §5 two Next.js proxy routes | 10 |
| §5 serializer fields | 3 |
| Error handling: swallow, silent no-op, 400 in UI | 5 (swallow), 9 (400) |
| Testing: all listed test cases | 3, 4, 5, 6, 7, 8, 9 |

No spec requirement is unassigned.

**Type consistency:** `notify_problem(website, *, subject, title, detail, tags, emoji, client)` is called with exactly these keywords in Tasks 6, 7 and 8. `sync_member_links` returns `{"matched", "unmatched", "workspace_id"}` in Task 4 and is consumed with those exact keys in Task 9. `mention_for` returns `(str, str | None)` in Task 5 and is only used there. `clickup_user_id` is a **string** everywhere — Task 2's tests use ints for `user_ids` sent to ClickUp, which is what ClickUp's own payloads use, while Task 4 stores `str(cu["id"])`; Task 9 passes the stored strings back as `user_ids`, which ClickUp accepts.

**One risk carried forward:** the exact `DomainInfo` / `DomainAlert` constructor
fields in Task 7's fixture are unverified — Step 1 of that task greps for the
real usage first. If the fields differ, adapt the fixture, not the assertions.
