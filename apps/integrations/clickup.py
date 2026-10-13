"""One place to talk to ClickUp.

Five modules previously hand-rolled their own urllib requests — each repeating
the auth header, the timeout and a slightly different idea of what counts as a
failure. This consolidates that: build a client with a token, call a method,
get parsed JSON back or a ClickUpError.

The token is a personal ClickUp token (`pk_…`), so anything created through
this client is attributed to whoever owns the token. Moving to OAuth would
change that, and nothing else here.
"""
from __future__ import annotations

import logging
import re

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://api.clickup.com/api"
DEFAULT_TIMEOUT = 10

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


class ClickUpError(RuntimeError):
    """A ClickUp call did not succeed.

    Carries `status_code` so callers can tell "your token is wrong" (401) from
    "ClickUp is having a bad day" (5xx) without parsing the message.
    """

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class ClickUpClient:
    def __init__(self, token: str, timeout: int = DEFAULT_TIMEOUT, session=None):
        self.token = token or ""
        self.timeout = timeout
        # Injectable so tests can record requests without patching globals.
        self._session = session or requests

    # -- plumbing ---------------------------------------------------------

    def _request(self, method: str, path: str, *, json=None, version: str = "v2"):
        if not self.token:
            raise ClickUpError("No ClickUp API token configured.")

        url = f"{BASE_URL}/{version}/{path.lstrip('/')}"
        headers = {"Authorization": self.token, "Content-Type": "application/json"}
        try:
            resp = self._session.request(
                method, url, headers=headers, json=json, timeout=self.timeout
            )
        except ClickUpError:
            raise
        except Exception as exc:  # network-level failure
            raise ClickUpError(f"Could not reach ClickUp: {exc}") from exc

        if not 200 <= resp.status_code < 300:
            detail = (getattr(resp, "text", "") or "")[:200]
            raise ClickUpError(
                f"ClickUp returned HTTP {resp.status_code}: {detail}", resp.status_code
            )
        try:
            return resp.json()
        except Exception:
            return {}

    # -- endpoints --------------------------------------------------------

    def whoami(self) -> dict:
        """The user the token belongs to — used by the connection test."""
        return self._request("GET", "user")

    def create_task(
        self,
        list_id: str,
        *,
        name: str,
        description: str = "",
        assignees: list | None = None,
        tags: list | None = None,
        due_date: int | None = None,
    ) -> dict:
        """Create a task in `list_id`. Returns ClickUp's task payload (id, url)."""
        body: dict = {"name": name}
        if description:
            body["description"] = description
        # Sent only when present — ClickUp rejects a null assignee list.
        if assignees:
            body["assignees"] = assignees
        if tags:
            body["tags"] = tags
        if due_date:
            body["due_date"] = due_date
        return self._request("POST", f"list/{list_id}/task", json=body)

    def get_task(self, task_id: str) -> dict:
        return self._request("GET", f"task/{task_id}")

    def comment(self, task_id: str, text: str) -> dict:
        return self._request("POST", f"task/{task_id}/comment", json={"comment_text": text})

    def workspaces(self) -> list:
        """The workspaces (ClickUp calls them "teams") this token can see.

        Each carries a `members` list, which is how a Stacks Monitor user is matched
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

    def post_chat(
        self,
        workspace_id: str,
        channel_id: str,
        text: str,
        *,
        followers: list | None = None,
        assignee: str | None = None,
    ) -> dict:
        """Post a markdown message to a Chat channel.

        ClickUp's Chat API supports no request-side syntax for an inline
        @-mention, so the body's "@name" is for human readers only. `assignee`
        and `followers` are the real ping: assignment lands the message in one
        person's ClickUp inbox, followers put the other managers on the thread.
        Both are omitted when empty — ClickUp rejects nulls here.
        """
        body: dict = {"type": "message", "content": text, "content_format": "text/md"}
        if followers:
            body["followers"] = followers
        if assignee:
            body["assignee"] = str(assignee)
        return self._request(
            "POST",
            f"workspaces/{workspace_id}/chat/channels/{channel_id}/messages",
            json=body,
            version="v3",
        )

    def list_custom_fields(self, list_id: str) -> list:
        """Field definitions for a list — needed to map ClickUp columns onto
        Client fields when the CSM sync lands."""
        return self._request("GET", f"list/{list_id}/field").get("fields", [])
