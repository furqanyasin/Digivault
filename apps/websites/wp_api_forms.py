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


#: Extended as readers land below.
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
