"""Credential vault business logic.

All reads and writes to encrypted fields go through this service so that
encryption, access logging, and role enforcement are centralised.
"""

from __future__ import annotations

from django.db import transaction

from apps.accounts.models import TeamMembership
from apps.common.exceptions import ForbiddenError, NotFoundError
from apps.credentials.models import Credential, CredentialAccessLog


class CredentialService:

    # Roles that may reveal (decrypt) credentials. Member-level roles (developer,
    # editor, seo) can reveal only the credentials shared with them — visibility
    # is enforced separately by Credential.objects.visible_to().
    _REVEAL_ROLES = {
        TeamMembership.Role.OWNER,
        TeamMembership.Role.MANAGER,
        TeamMembership.Role.DEVELOPER,
        TeamMembership.Role.EDITOR,
        TeamMembership.Role.SEO,
    }

    @staticmethod
    @transaction.atomic
    def create(
        label: str,
        credential_type: str,
        login_url: str,
        username: str,
        password: str,
        notes: str,
        created_by,
        team=None,
        website=None,
    ) -> Credential:
        if team is None:
            if website is None:
                raise ValueError("Either team or website must be provided.")
            team = website.team
        credential = Credential(
            team=team,
            website=website,
            label=label,
            credential_type=credential_type,
            login_url=login_url,
            created_by=created_by,
        )
        credential.set_username(username)
        credential.set_password(password)
        credential.set_notes(notes)
        credential.save()
        return credential

    @staticmethod
    @transaction.atomic
    def update(
        credential: Credential,
        label: str | None = None,
        credential_type: str | None = None,
        login_url: str | None = None,
        username: str | None = None,
        password: str | None = None,
        notes: str | None = None,
        updated_by=None,
    ) -> Credential:
        if label is not None:
            credential.label = label
        if credential_type is not None:
            credential.credential_type = credential_type
        if login_url is not None:
            credential.login_url = login_url
        if username is not None:
            credential.set_username(username)
        if password is not None:
            credential.set_password(password)
        if notes is not None:
            credential.set_notes(notes)
        credential.save()

        if updated_by:
            CredentialAccessLog.objects.create(
                credential=credential,
                user=updated_by,
                action=CredentialAccessLog.Action.EDITED,
            )
        return credential

    @classmethod
    def can_view_password(cls, credential: Credential, user) -> bool:
        """Whether `user` may see this credential's plaintext password.

        Always True for owners, managers, and the creator. For a developer with
        a share, it follows the share's `can_view_password` flag (defaults True
        if, somehow, no share row exists but they reached reveal).
        """
        from apps.credentials.models import CredentialShare

        if credential.created_by_id == getattr(user, "id", None):
            return True
        membership = TeamMembership.objects.filter(
            user=user, team=credential.team
        ).first()
        if membership and membership.role in (
            TeamMembership.Role.OWNER, TeamMembership.Role.MANAGER
        ):
            return True
        share = CredentialShare.objects.filter(
            credential=credential, user=user
        ).first()
        return share.can_view_password if share else True

    @classmethod
    def reveal(
        cls,
        credential: Credential,
        requesting_user,
        ip_address: str | None = None,
        for_autofill: bool = False,
    ) -> dict:
        """Decrypt and return credential plaintext after role and audit checks.

        When the requester may not view the password (a share with
        `can_view_password=False`) and this is not an autofill request, the
        password is blanked and `password_hidden` is set so the dashboard never
        displays it. Autofill (`for_autofill=True`) still receives it so the
        extension can fill the login form.
        """
        cls._assert_can_reveal(credential, requesting_user)

        CredentialAccessLog.objects.create(
            credential=credential,
            user=requesting_user,
            action=CredentialAccessLog.Action.VIEWED,
            ip_address=ip_address,
        )
        password = credential.get_password()
        hidden = False
        if not for_autofill and not cls.can_view_password(credential, requesting_user):
            password = ""
            hidden = True
        return {
            "username": credential.get_username(),
            "password": password,
            "notes": credential.get_notes(),
            "password_hidden": hidden,
        }

    @classmethod
    def _assert_can_reveal(cls, credential: Credential, user) -> None:
        team = credential.team
        try:
            membership = TeamMembership.objects.get(user=user, team=team)
        except TeamMembership.DoesNotExist:
            raise ForbiddenError("You are not a member of this team.")
        if membership.role not in cls._REVEAL_ROLES:
            raise ForbiddenError(
                "Viewer role cannot reveal credentials. "
                "Contact your team manager."
            )
