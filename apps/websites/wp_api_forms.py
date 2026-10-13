"""Read form recipients from a site's own WordPress REST API.

The WP Connect path (`wp_forms.py`) is the better answer but needs a PHP snippet
pasted into the client's site. This one needs only a WordPress credential the
agency usually already holds in the vault, at the cost of narrower coverage.

That narrowness is a property of WordPress, not of the implementation. Core
hides underscore-prefixed post meta from every API unless the owning plugin
registers it with an `auth_callback` (`map_meta_cap`'s `edit_post_meta` branch
resolves `! is_protected_meta(...)` and then lets an `auth_post_meta_{key}`
filter override it). Of the four form plugins that matter:

* **Elementor** registers `_elementor_data` that way, from 3.27.0. Reachable.
* **Gravity Forms** keeps forms in its own tables and exposes them through its
  own REST API, which has taken Application Passwords since 2.4.21.4. Reachable.
* **Contact Form 7** stores every property as `'_' . $prop` and contains no
  `register_meta` call at all; its own REST controller returns the form markup
  and additional settings, never the mail config. Unreachable.
* **WPForms** registers its CPT `public => false` with no `show_in_rest`, and
  its Abilities API integration returns an explicit "safe settings" allowlist
  that omits notifications. Unreachable.

So CF7 and WPForms sites still need WP Connect, and no amount of work here
changes that.

Every failure is a normal state — most sites have no credential, plenty of hosts
strip the Authorization header, and REST is often disabled outright. None of it
raises, logs at error level, or touches the site's health score.
"""
from __future__ import annotations

import base64
import json
import logging

from apps.common import outbound
from apps.common.outbound import OutboundError
from apps.common.ssrf import BlockedURLError
from apps.credentials.wp_access import (
    WpCredential,
    log_system_read,
    resolve_wp_credential,
)

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 20
#: Elementor returns a whole page's builder tree per row, so the 64 KB default
#: in `outbound.fetch` truncates constantly. A truncated body is treated as a
#: failed read, never as "this page has no form".
_READ_BYTES = 2_000_000
_MAX_REQUESTS_PER_SYNC = 15


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

    `parsed` is None whenever we did not get a usable answer. A status of 0 means
    the request never left — SSRF guard, per-host budget, or a transport error.
    The caller needs the status to tell a rejected credential (401/403) apart
    from a plugin that simply is not installed (404).
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
        logger.debug(
            "wp_api_forms: %s deferred by outbound budget: %s", website.domain, exc
        )
        return None, 0
    except Exception as exc:
        logger.debug("wp_api_forms: %s unreachable: %s", website.domain, exc)
        return None, 0

    if resp.status_code != 200:
        return None, resp.status_code

    if resp.truncated:
        logger.debug(
            "wp_api_forms: %s truncated %s at the read cap", website.domain, path
        )
        return None, resp.status_code

    try:
        return json.loads(resp.body), resp.status_code
    except ValueError:
        logger.debug("wp_api_forms: %s returned non-JSON for %s", website.domain, path)
        return None, resp.status_code


# ── Elementor ───────────────────────────────────────────────────────────────

#: Post types that can carry an Elementor form. `elementor_library` holds popups
#: and saved templates, which is where a lot of lead forms actually live. A site
#: whose CPT is not REST-exposed simply answers 404, which costs one request.
_ELEMENTOR_POST_TYPES = ("pages", "posts", "elementor_library")
#: Each row carries a whole builder tree, so a large page size produces
#: multi-megabyte responses. Small pages, a bounded count, and say out loud what
#: was skipped rather than truncating in silence.
_ELEMENTOR_PER_PAGE = 10
_ELEMENTOR_MAX_PAGES = 10

#: Elementor Pro is not publicly distributed, so unlike everything else in this
#: module these key names could not be read from source. Both spellings seen in
#: the wild are listed; a key that is absent costs nothing.
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


def _elementor_entries(row) -> list[dict]:
    """The recipient entries carried by one REST row's `_elementor_data`."""
    if not isinstance(row, dict):
        return []
    meta = row.get("meta")
    raw = (meta or {}).get("_elementor_data") if isinstance(meta, dict) else None
    if not raw:
        return []

    try:
        tree = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return []

    widgets: list = []
    _walk_form_widgets(tree, widgets)

    out = []
    for settings in widgets:
        to = _first_value(settings, _TO_KEYS)
        if not to:
            continue
        out.append({
            "plugin": "elementor",
            "name": str(settings.get("form_name") or "").strip(),
            "to": to,
            "cc": _first_value(settings, _CC_KEYS),
            "bcc": _first_value(settings, _BCC_KEYS),
        })
    return out


def _read_elementor_post_type(website, credential, fetch, post_type) -> list[dict]:
    out: list[dict] = []
    exhausted = False

    for page_number in range(1, _ELEMENTOR_MAX_PAGES + 1):
        path = (
            f"wp/v2/{post_type}?context=edit&_fields=id,link,meta"
            f"&per_page={_ELEMENTOR_PER_PAGE}&page={page_number}"
        )
        rows, _status = fetch(website, path, credential)
        if not isinstance(rows, list) or not rows:
            exhausted = True
            break

        for row in rows:
            out.extend(_elementor_entries(row))

        if len(rows) < _ELEMENTOR_PER_PAGE:
            exhausted = True
            break

    if not exhausted:
        logger.info(
            "wp_api_forms: %s stopped at %d pages of %s; later pages not read",
            website.domain,
            _ELEMENTOR_MAX_PAGES,
            post_type,
        )

    return out


def read_elementor(website, credential, fetch=None) -> list[dict]:
    """Elementor form recipients, read from `_elementor_data` post meta.

    Reachable because Elementor registers that meta with `show_in_rest` and an
    `auth_callback` (`modules/wp-rest/classes/elementor-post-meta.php`, 3.27.0+).
    Without such a registration WordPress hides underscore-prefixed meta from
    every API, which is exactly why Contact Form 7 cannot be read this way.

    Joined to detected rows by form name: Elementor renders the name into the
    form element's `name` attribute, which is what the snippet stores.
    """
    fetch = fetch or fetch_json

    entries: list[dict] = []
    for post_type in _ELEMENTOR_POST_TYPES:
        entries.extend(
            _read_elementor_post_type(website, credential, fetch, post_type)
        )
    return entries


# ── Gravity Forms ───────────────────────────────────────────────────────────

#: A site with more forms than this is pathological; the cap bounds how many
#: per-form requests one sweep can aim at a client origin.
_GRAVITY_MAX_FORMS = 100


def read_gravity(website, credential, fetch=None) -> list[dict]:
    """Gravity Forms notification recipients, over its own REST API v2.

    Gravity keeps forms in its own tables rather than `wp_posts`, so the post
    meta route cannot see them. Its REST API has accepted WordPress Application
    Passwords over Basic auth since 2.4.21.4 and runs with the authenticated
    user's Gravity capabilities.

    Joined to detected rows by id prefix (`gform_<id>`), which is the strong key
    `_match` prefers — and whose digit rule is what stops form 1 claiming form
    12's row.
    """
    fetch = fetch or fetch_json

    listing, _status = fetch(website, "gf/v2/forms", credential)
    if not isinstance(listing, dict):
        return []

    entries: list[dict] = []
    for form_id in list(listing.keys())[:_GRAVITY_MAX_FORMS]:
        detail, _ = fetch(website, f"gf/v2/forms/{form_id}", credential)
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
            # no fixed destination to record — and the raw value is a field id,
            # which would display as a nonsense address.
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


READERS: tuple = (read_elementor, read_gravity)


#: Statuses meaning "this credential will not work", as opposed to "this plugin
#: is not installed" (404) or "this site is busy" (5xx).
_AUTH_FAILURE_STATUSES = (401, 403)


def sync_website_detailed(website) -> dict:
    """Read recipients and return safe diagnostics, never secrets or values."""
    from django.utils import timezone

    from apps.scripts.models import DetectedForm
    from apps.websites.wp_forms import apply_recipients

    if website.wp_api_auth_failed_at is not None:
        return {"updated": 0, "source": "wp_api", "reason": "invalid_credentials"}

    credential = resolve_wp_credential(website)
    if credential is None:
        return {"updated": 0, "source": "wp_api", "reason": "no_credentials"}

    seen_statuses: list[int] = []
    request_count = 0

    def _tracking_fetch(site, path, cred, **kwargs):
        nonlocal request_count
        if request_count >= _MAX_REQUESTS_PER_SYNC:
            logger.warning("wp_api_forms: %s reached the per-sync request cap", website.domain)
            return None, 429
        request_count += 1
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

    if any(status in _AUTH_FAILURE_STATUSES for status in seen_statuses):
        website.wp_api_auth_failed_at = timezone.now()
        website.save(update_fields=["wp_api_auth_failed_at", "updated_at"])
        logger.warning("wp_api_forms: %s rejected the configured credential", website.domain)
        return {
            "updated": 0, "source": "wp_api", "reason": "invalid_credentials",
            "reported_forms": len(entries), "forms_with_recipients": len(entries),
        }

    forms = list(website.detected_forms.all())
    updated = 0
    matched = 0
    unmatched = 0
    for entry in entries:
        before = {
            tuple(form.recipients.get("to", []))
            for form in forms
            if isinstance(form.recipients, dict)
        }
        count_before = updated
        updated += apply_recipients(website, [entry], source=DetectedForm.RecipientSource.WP_API)
        if updated > count_before:
            matched += 1
        elif before or forms:
            unmatched += 1

    if not entries:
        reason = (
            "request_limit"
            if request_count >= _MAX_REQUESTS_PER_SYNC
            else "no_recipients_configured" if seen_statuses else "unsupported_plugin"
        )
    elif updated:
        reason = "completed"
    else:
        reason = "no_detected_form_match"
    log_system_read(credential.credential_id)
    return {
        "updated": updated,
        "source": "wp_api",
        "reason": reason,
        "reported_forms": len(entries),
        "forms_with_recipients": len(entries),
        "matched_forms": matched,
        "unmatched_forms": unmatched,
    }


def sync_website(website) -> int:
    """Read every reader this site answers to, and record what they found.

    A site that rejects our credential is disarmed rather than retried nightly:
    repeated 401s from a single egress IP are how that IP earns a ban, and the
    ban would cost uptime monitoring for the same client.
    """
    return sync_website_detailed(website)["updated"]
