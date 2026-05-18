"""ClickUp integration for client records."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import requests
from django.conf import settings
from django.utils import timezone

if TYPE_CHECKING:
    from apps.clients.models import Client

logger = logging.getLogger(__name__)

CLICKUP_API = "https://api.clickup.com/api/v2"

_HOSTING_MAP = {
    "site ground": "siteground",
    "siteground": "siteground",
    "wpengine": "wpengine",
    "wp engine": "wpengine",
    "cloudways": "cloudways",
    "bluehost": "bluehost",
    "godaddy": "godaddy",
    "squarespace": "squarespace",
    "wix": "wix",
    "shopify": "shopify",
}


def _api_token(team=None) -> str:
    # Prefer per-team token; fall back to global env var
    if team is not None:
        token = getattr(team, "clickup_api_token", "") or ""
        if token:
            return token
    token = getattr(settings, "CLICKUP_API_TOKEN", "")
    if not token:
        raise ValueError("ClickUp API token is not configured. Add it in Settings → Integrations.")
    return token


def fetch_task(task_id: str, team=None) -> dict:
    headers = {"Authorization": _api_token(team), "Content-Type": "application/json"}
    resp = requests.get(f"{CLICKUP_API}/task/{task_id}", headers=headers, timeout=10)
    resp.raise_for_status()
    return resp.json()


def sync_client_from_clickup(client: "Client") -> bool:
    """Pull latest data from ClickUp into the Client record. Returns True on success."""
    if not client.clickup_task_id:
        return False
    try:
        task = fetch_task(client.clickup_task_id, team=getattr(client, "team", None))
    except Exception as exc:
        logger.warning("ClickUp fetch failed for task %s: %s", client.clickup_task_id, exc)
        return False

    updates: dict = {}

    if task.get("name"):
        updates["name"] = task["name"]

    for field in task.get("custom_fields", []):
        fname = (field.get("name") or "").strip().lower()
        fval = field.get("value") or ""

        if "website" in fname or "url" in fname:
            if fval:
                updates["website_url"] = str(fval).strip()
        elif "hosting platform" in fname:
            raw = str(fval).lower().strip()
            updates["hosting_platform"] = _HOSTING_MAP.get(raw, raw[:30] if raw else "")
        elif "migration status" in fname:
            raw = str(fval).lower()
            if "siteground" in raw or ("yes" in raw and "didn't" not in raw):
                updates["migration_status"] = "done_to_siteground"
            else:
                updates["migration_status"] = "not_done"
        elif "confirmation from csm" in fname or "csm" in fname:
            raw = str(fval).lower()
            if "can do" in raw or ("yes" in raw and "can't" not in raw):
                updates["csm_migration_confirmation"] = "can_do"
            elif "can't" in raw or "cannot" in raw:
                updates["csm_migration_confirmation"] = "cannot"
        elif "ppc" in fname or "ads" in fname:
            raw = str(fval).lower()
            updates["running_ppc_ads"] = "yes" if raw.startswith("yes") else ("no" if raw.startswith("no") else "")
        elif "domain" in fname or "access" in fname:
            if fval:
                updates["domain_access_location"] = str(fval).strip()[:200]
        elif "note" in fname or "ks note" in fname:
            if fval:
                updates["notes"] = str(fval).strip()
        elif "comment" in fname:
            if fval:
                updates["comments"] = str(fval).strip()

    if updates:
        updates["clickup_synced_at"] = timezone.now()
        for key, val in updates.items():
            setattr(client, key, val)
        client.save(update_fields=list(updates.keys()) + ["updated_at"])

    return True


def push_status_to_clickup(client: "Client") -> bool:
    """Update the ClickUp task status when a client is activated/deactivated."""
    if not client.clickup_task_id:
        return False
    try:
        headers = {"Authorization": _api_token(getattr(client, "team", None)), "Content-Type": "application/json"}
        status = "closed" if client.status == "inactive" else "open"
        resp = requests.put(
            f"{CLICKUP_API}/task/{client.clickup_task_id}",
            headers=headers,
            json={"status": status},
            timeout=10,
        )
        resp.raise_for_status()
        return True
    except Exception as exc:
        logger.warning("ClickUp push failed for task %s: %s", client.clickup_task_id, exc)
        return False
