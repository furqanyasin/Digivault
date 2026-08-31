"""Which WordPress credential Digivault may use to read a site's own API.

Kept apart from the vault's request-facing code because the caller here is a
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
    burn a login-lockout budget the way a real password does. That matters more
    than usual here, because everything leaves from one IP.

    A credential whose ciphertext will not decrypt (key rotated, row copied
    between environments) is skipped rather than raised — this sweep's job is to
    fill in what it can, not to fail the site.
    """
    from apps.credentials.models import Credential

    order = (
        Credential.CredentialType.WORDPRESS_APP_PASSWORD,
        Credential.CredentialType.WORDPRESS,
    )
    by_type: dict[str, Credential] = {}
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
