"""Emails the vault sends to people, rather than to a team channel.

Everything here is best effort and runs after commit: a password change, a
request or a broken-login report must never fail because SMTP did, and must
never announce something a rolled-back transaction did not do.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

#: A change notice goes to people who used the credential this recently.
RECENT_USE_DAYS = 30


def display_name(user) -> str:
    full = f"{user.first_name} {user.last_name}".strip()
    return full or user.email


def mail(subject: str, body: str, recipients) -> None:
    recipients = sorted({r for r in recipients if r})
    if not recipients:
        return

    def send():
        try:
            send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, recipients, fail_silently=True)
        except Exception:  # noqa: BLE001
            logger.exception("Vault email failed: %s", subject)

    transaction.on_commit(send)


def approver_emails(credential) -> set[str]:
    """Owners, managers and the credential's creator — everyone who may change it."""
    from apps.accounts.models import TeamMembership

    emails = set(
        TeamMembership.objects.filter(
            team=credential.team,
            role__in=[TeamMembership.Role.OWNER, TeamMembership.Role.MANAGER],
        ).values_list("user__email", flat=True)
    )
    if credential.created_by_id and credential.created_by.email:
        emails.add(credential.created_by.email)
    return {e for e in emails if e}


def password_changed(credential, changed_by) -> None:
    """Tell recent users that a shared password changed.

    "Recent users" are people the access log shows revealing, copying,
    autofilling or reading a code from it in the last `RECENT_USE_DAYS`, who
    can still see it. They are the ones with the old password typed into a
    browser, a client's FTP app or a deploy script; everyone else would only
    learn to ignore the email.
    """
    from apps.credentials.models import Credential, CredentialAccessLog

    since = timezone.now() - timedelta(days=RECENT_USE_DAYS)
    user_ids = set(
        CredentialAccessLog.objects.filter(
            credential=credential,
            created_at__gte=since,
            action__in=[
                CredentialAccessLog.Action.VIEWED,
                CredentialAccessLog.Action.COPIED_PASSWORD,
                CredentialAccessLog.Action.AUTOFILL,
                CredentialAccessLog.Action.TOTP_CODE,
            ],
        )
        .exclude(user=None)
        .values_list("user_id", flat=True)
    )
    user_ids.discard(getattr(changed_by, "pk", None))
    if not user_ids:
        return

    from apps.accounts.models import User

    recipients = [
        u.email
        for u in User.objects.filter(pk__in=user_ids, is_active=True)
        if Credential.objects.visible_to(u).filter(pk=credential.pk).exists()
    ]
    who = display_name(changed_by) if changed_by else "Someone"
    mail(
        f"[Stacks Monitor] The password for '{credential.label}' changed",
        f"{who} changed the password for '{credential.label}'.\n\n"
        "If you saved the old one anywhere (a browser, an FTP client, a deploy "
        "setting), update it from the vault. The previous password is kept in "
        "its history in case anything still depends on it.",
        recipients,
    )


def reported_broken(credential, reporter, note: str) -> None:
    mail(
        f"[Stacks Monitor] '{credential.label}' was reported as not working",
        f"{display_name(reporter)} ({reporter.email}) reported that '{credential.label}' "
        f"no longer works.\n\nNote: {note or '(none)'}\n\n"
        "Update the password in the vault, or mark it fixed, so nobody else "
        "locks the account out retrying it.",
        approver_emails(credential) - {reporter.email},
    )
