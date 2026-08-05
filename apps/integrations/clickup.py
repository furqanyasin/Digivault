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

    def post_chat(self, workspace_id: str, channel_id: str, text: str) -> dict:
        return self._request(
            "POST",
            f"workspaces/{workspace_id}/chat/channels/{channel_id}/messages",
            json={"type": "message", "content": text, "content_format": "text/md"},
            version="v3",
        )

    def list_custom_fields(self, list_id: str) -> list:
        """Field definitions for a list — needed to map ClickUp columns onto
        Client fields when the CSM sync lands."""
        return self._request("GET", f"list/{list_id}/field").get("fields", [])
