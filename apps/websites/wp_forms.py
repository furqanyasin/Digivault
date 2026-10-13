"""Read form recipients from a WordPress site's Stacks Monitor Connect snippet.

Every WordPress form plugin stores the "send submissions to" address in the
database — Elementor in `_elementor_data`, Contact Form 7 in `_mail`, WPForms in
the form post's JSON, Gravity Forms in its notification config. None of it is
rendered into the page, so the tracking snippet cannot see it and the Forms tab's
"Goes to" column stays empty on exactly the sites the agency cares about.

This module asks the site instead, over the signature-gated `digivault/v1/forms`
route that ships in the WP Connect PHP snippet (`wp_sso_snippet.py`), and joins
the answer onto the `DetectedForm` rows the snippet already created.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
import uuid

from apps.common import outbound
from apps.common.outbound import OutboundError
from apps.common.ssrf import BlockedURLError

logger = logging.getLogger(__name__)

# The route answers with staff mailboxes, so tokens are short-lived for the same
# reason the SSO ones are: a leaked URL stops working almost immediately.
_TOKEN_TTL_SECONDS = 120
_TIMEOUT_SECONDS = 15
# A site with more configured forms than this is pathological; the cap keeps one
# bad response from turning into an unbounded match loop.
_MAX_ENTRIES = 500


def site_base_url(website) -> str:
    """The site's origin, with a scheme, ready to append a REST path to."""
    domain = website.domain or ""
    if not domain.startswith(("http://", "https://")):
        domain = f"https://{domain}"
    return domain.rstrip("/")


def build_signed_url(website, path: str = "forms") -> str:
    """A signed, expiring URL for one of the snippet's `digivault/v1` routes.

    Mirrors the scheme `WebsiteViewSet.wp_login` uses, and the snippet's
    `dvc_verify_token` checks: HMAC-SHA256 over the base64 payload, using the
    per-site secret.
    """
    payload = {
        "exp": int(time.time()) + _TOKEN_TTL_SECONDS,
        "jti": uuid.uuid4().hex,
    }
    raw = json.dumps(payload, separators=(",", ":")).encode()
    payload_b64 = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    sig = hmac.new(
        website.wp_sso_secret.encode(), payload_b64.encode(), hashlib.sha256
    ).hexdigest()
    return f"{site_base_url(website)}/wp-json/digivault/v1/{path}?p={payload_b64}&s={sig}"


def fetch_recipients(website) -> list[dict]:
    """What the site reports about its forms, or `[]` if it can't be asked.

    Every failure is a normal state, not an incident: most sites have never
    pasted the snippet (404), some are behind a firewall that blocks unknown
    REST routes (403), and a site can simply be down. None of that should raise,
    log at error level, or affect the site's health score.
    """
    if not website.wp_sso_secret:
        return []

    url = build_signed_url(website)

    # Through the shared client so this daily sweep draws on the same per-host
    # budget as the monitor and the SEO scan. It also inherits the SSRF guard on
    # every redirect hop, which the bare requests.get did not have.
    try:
        resp = outbound.fetch(
            url, timeout=_TIMEOUT_SECONDS, wait_up_to=_TIMEOUT_SECONDS
        )
    except BlockedURLError as exc:
        logger.warning("wp_forms: refusing to fetch %s: %s", website.pk, exc)
        return []
    except OutboundError as exc:
        logger.debug("wp_forms: %s deferred by outbound budget: %s", website.domain, exc)
        return []
    except Exception as exc:
        logger.debug("wp_forms: %s unreachable: %s", website.domain, exc)
        return []

    if resp.status_code != 200:
        logger.debug(
            "wp_forms: %s answered HTTP %s (snippet not installed?)",
            website.domain,
            resp.status_code,
        )
        return []

    try:
        body = json.loads(resp.body)
    except ValueError:
        logger.debug("wp_forms: %s returned non-JSON", website.domain)
        return []

    entries = body.get("forms") if isinstance(body, dict) else None
    if not isinstance(entries, list):
        logger.debug("wp_forms: %s returned an unexpected shape", website.domain)
        return []

    return [e for e in entries[:_MAX_ENTRIES] if isinstance(e, dict)]


def _matches_prefix(form_id: str, prefix: str) -> bool:
    """Whether a rendered form id belongs to the plugin form `prefix` names.

    A plain `startswith` would let form 1 claim form 12's row: `gform_1` is a
    prefix of `gform_12`, and `wpforms-form-3` of `wpforms-form-30`. So the
    character after the prefix must not continue the id number. Contact Form 7's
    prefix already ends in a dash (`wpcf7-f12-`), which the same rule accepts
    ahead of `p3-o1`.
    """
    if not prefix or not form_id.startswith(prefix):
        return False
    rest = form_id[len(prefix):]
    return not rest[:1].isdigit()


def _match(entry: dict, forms: list) -> list:
    """The detected rows a reported plugin form corresponds to.

    The id prefix is the strong key and wins outright when it matches anything.
    The name is the fallback, and the only key Elementor has: it renders its form
    name as the form element's `name` attribute, which is what the snippet stores.
    """
    prefix = str(entry.get("id_prefix") or "")
    if prefix:
        by_id = [f for f in forms if _matches_prefix(f.form_id or "", prefix)]
        if by_id:
            return by_id

    name = str(entry.get("name") or "").strip()
    if name:
        return [f for f in forms if (f.form_name or "").strip().casefold() == name.casefold()]

    return []


def apply_recipients(website, entries: list[dict], source=None) -> int:
    """Fill in `recipients` from what the site reported. Returns rows written.

    `source` says which path answered, and defaults to WP Connect so the caller
    below stays unchanged. WP Connect reads the database directly through a
    signature-gated route; the REST readers in `wp_api_forms` see only what a
    plugin chose to expose. So a WP Connect answer outranks theirs and is never
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
                website.domain,
                entry.get("plugin"),
                entry.get("name"),
            )
            continue

        for form in matched:
            # WP Connect read the site's database; the REST readers read what a
            # plugin chose to publish. The weaker source never displaces it.
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
            form.save(
                update_fields=["recipients", "recipient_source", "updated_at"]
            )
            record_recipient_change(
                form,
                old_recipients=old_recipients,
                old_source=old_source,
                new_source=source,
            )
            written += 1

    return written


def sync_website(website) -> int:
    """Ask one site where its forms deliver, and record it. Returns rows written."""
    entries = fetch_recipients(website)
    if not entries:
        return 0
    return apply_recipients(website, entries)
