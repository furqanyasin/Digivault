"""Credential vault business logic.

All reads and writes to encrypted fields go through this service so that
encryption, access logging, and role enforcement are centralised.
"""

from __future__ import annotations

import time

import pyotp
from django.db import transaction

from apps.accounts.models import TeamMembership
from apps.common.exceptions import ForbiddenError
from apps.credentials.models import (
    Credential,
    CredentialAccessLog,
    CredentialPasswordHistory,
)

# Member-level roles a credential can be shared with. Owners and managers see
# the whole vault already, so a share row for them is redundant; a viewer can
# never decrypt, so a share row for them would be misleading. Every other
# member-level role belongs here — an SEO executive needs the same WordPress
# logins a developer does.
SHAREABLE_ROLES = frozenset({
    TeamMembership.Role.DEVELOPER,
    TeamMembership.Role.EDITOR,
    TeamMembership.Role.SEO,
    TeamMembership.Role.SEO_EXECUTIVE,
})


class CredentialService:

    # Roles that may reveal (decrypt) credentials. Member-level roles
    # (developer, editor, seo, seo_executive) can reveal only the credentials
    # shared with them — visibility is enforced separately by
    # Credential.objects.visible_to().
    _REVEAL_ROLES = {
        TeamMembership.Role.OWNER,
        TeamMembership.Role.MANAGER,
        *SHAREABLE_ROLES,
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
        client=None,
        department: str | None = None,
        totp_secret: str = "",
        folder=None,
    ) -> Credential:
        """`client` defaults to the website's client, `department` to the type's
        `DEFAULT_DEPARTMENT` — so a login saved from anywhere (the dashboard, the
        extension, an import) lands in its client folder without the caller
        having to know folders exist. Pass `department=""` to file it nowhere.
        """
        if team is None:
            if website is None:
                raise ValueError("Either team or website must be provided.")
            team = website.team
        if client is None and website is not None:
            client = website.client
        if client is not None and client.team_id != team.id:
            raise ValueError("Client belongs to a different team.")
        if department is None:
            department = Credential.DEFAULT_DEPARTMENT.get(credential_type, "")
        if folder is not None and folder.team_id != team.id:
            raise ValueError("Folder belongs to a different team.")
        credential = Credential(
            team=team,
            website=website,
            folder=folder,
            client=client,
            department=department,
            label=label,
            credential_type=credential_type,
            login_url=login_url,
            created_by=created_by,
        )
        credential.set_username(username)
        credential.set_password(password)
        credential.set_notes(notes)
        credential.set_totp_secret(totp_secret)
        credential.save()
        return credential

    #: Sentinel for "the caller did not mention the website", so that an
    #: explicit `website=None` ("unlink it") is distinguishable from an omitted
    #: argument. Every other field here uses None for "unchanged", which is
    #: fine because none of them is legitimately nullable — the website is.
    UNSET = object()

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
        website=UNSET,
        client=UNSET,
        department: str | None = None,
        totp_secret: str | None = None,
        notify_users: bool = True,
        folder=UNSET,
    ) -> Credential:
        """`None` (or UNSET for the nullable links) leaves a field alone.
        `totp_secret=""` removes the authenticator secret."""
        if label is not None:
            credential.label = label
        if credential_type is not None:
            credential.credential_type = credential_type
        if login_url is not None:
            credential.login_url = login_url
        if username is not None:
            credential.set_username(username)
        password_changed = False
        if password is not None:
            password_changed = CredentialService._remember_password(
                credential, password, updated_by
            )
            credential.set_password(password)
            if password_changed:
                # A new password is the fix for "this login is broken".
                credential.reported_broken_at = None
                credential.reported_broken_by = None
                credential.reported_broken_note = ""
        if notes is not None:
            credential.set_notes(notes)
        if website is not CredentialService.UNSET:
            # Which website a credential belongs to decides which section of the
            # vault it appears in, so this is how a login filed under "Hosting &
            # General" gets moved to "Website Credentials" — and back.
            #
            # The caller resolves the website and is responsible for checking it
            # belongs to the same team; this asserts it anyway, because a
            # credential pointed at another team's website would be visible from
            # that website's page and is the one mistake here that crosses a
            # tenancy boundary.
            if website is not None and website.team_id != credential.team_id:
                raise ValueError("Website belongs to a different team.")
            credential.website = website
            # The client follows the website — the folder is how people file
            # things, the client is just what the website says it is for.
            if website is not None and website.client_id:
                credential.client_id = website.client_id
        if folder is not CredentialService.UNSET:
            if folder is not None and folder.team_id != credential.team_id:
                raise ValueError("Folder belongs to a different team.")
            credential.folder = folder
        if client is not CredentialService.UNSET:
            if client is not None and client.team_id != credential.team_id:
                raise ValueError("Client belongs to a different team.")
            credential.client = client
        if department is not None:
            credential.department = department
        if totp_secret is not None:
            credential.set_totp_secret(totp_secret)
        credential.save()

        if updated_by:
            CredentialAccessLog.objects.create(
                credential=credential,
                user=updated_by,
                action=CredentialAccessLog.Action.EDITED,
            )
        # A bulk import passes notify_users=False: re-importing a vault must not
        # send each recent user one email per changed row.
        if password_changed and notify_users:
            from apps.credentials import notify

            notify.password_changed(credential, updated_by)
        return credential

    @staticmethod
    def _remember_password(credential: Credential, new_password: str, changed_by) -> bool:
        """Keep the outgoing password before it is overwritten.

        Only when it really changes: an import re-run or an extension save of
        the same login writes the same password again, and ten identical rows
        would push the useful history out. Returns whether the password
        actually changed.
        """
        if not credential.pk or not credential._password:
            return bool(new_password)
        try:
            old = credential.get_password()
        except Exception:  # noqa: BLE001 — undecryptable (rotated key): nothing to keep
            return True
        if old == new_password:
            return False
        if not old:
            return True
        CredentialPasswordHistory.objects.create(
            credential=credential,
            _password=bytes(credential._password),
            changed_by=changed_by,
            set_at=credential.last_password_changed_at,
        )
        stale = CredentialPasswordHistory.objects.filter(credential=credential).values_list(
            "pk", flat=True
        )[CredentialPasswordHistory.KEEP:]
        CredentialPasswordHistory.objects.filter(pk__in=list(stale)).delete()
        return True

    @classmethod
    def reveal_history(cls, entry: CredentialPasswordHistory, user, ip_address=None) -> str:
        """An old password in plaintext. Held to the dashboard reveal's rule —
        a use-only grantee has no business reading a password's past either."""
        cls._assert_can_reveal(entry.credential, user)
        if not cls.can_view_password(entry.credential, user):
            raise ForbiddenError("Your access to this credential does not include viewing passwords.")
        CredentialAccessLog.objects.create(
            credential=entry.credential,
            user=user,
            action=CredentialAccessLog.Action.HISTORY_VIEWED,
            ip_address=ip_address,
        )
        return entry.get_password()

    @classmethod
    def can_view_password(cls, credential: Credential, user) -> bool:
        """Whether `user` may see this credential's plaintext password.

        Closed by default. This used to end `return share.can_view_password if
        share else True`, which was survivable only because the sole routes
        into reveal were owner, manager, creator and an explicit share. Group
        grants add a fourth route, and that fallback would have handed every
        grantee full plaintext.

        Access is additive: `can_view_password=False` is not a deny, it is a
        grant that omits reveal, so any permitting row wins.
        """
        from apps.credentials.models import CredentialShare, SubTeamCredentialGrant

        if credential.created_by_id == getattr(user, "id", None):
            return True

        membership = TeamMembership.objects.filter(
            user=user, team=credential.team
        ).first()
        if membership and membership.role in (
            TeamMembership.Role.OWNER, TeamMembership.Role.MANAGER
        ):
            return True

        if CredentialShare.objects.active().filter(
            credential=credential, user=user, can_view_password=True
        ).exists():
            return True

        if credential.folder_id:
            from apps.credentials.models import FolderShare

            if FolderShare.objects.filter(
                folder_id=credential.folder_id, user=user, can_view_password=True
            ).exists():
                return True

        if membership and membership.sub_team_id:
            permitting = SubTeamCredentialGrant.objects.filter(
                sub_team_id=membership.sub_team_id, can_view_password=True
            )
            if permitting.filter(scope=SubTeamCredentialGrant.Scope.ALL).exists():
                return True
            if permitting.filter(
                scope=SubTeamCredentialGrant.Scope.CREDENTIAL_TYPE,
                credential_type=credential.credential_type,
            ).exists():
                return True
            if permitting.filter(
                scope=SubTeamCredentialGrant.Scope.CREDENTIAL,
                credential_id=credential.pk,
            ).exists():
                return True
            if credential.folder_id and permitting.filter(
                scope=SubTeamCredentialGrant.Scope.FOLDER,
                folder_id=credential.folder_id,
            ).exists():
                return True

        return False

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
            action=(
                CredentialAccessLog.Action.AUTOFILL
                if for_autofill
                else CredentialAccessLog.Action.VIEWED
            ),
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

    #: TOTP step, fixed: `normalize_totp_secret` refuses anything else.
    TOTP_PERIOD = 30

    @classmethod
    def totp_code(
        cls,
        credential: Credential,
        requesting_user,
        ip_address: str | None = None,
    ) -> dict:
        """The current authenticator code for `credential`, never its secret.

        Open to anyone who may reveal the credential at all, including a
        use-only share or grant: a code is useless without the password, lasts
        thirty seconds, and is exactly what a teammate needs to finish a sign-in
        the extension filled. Logged per read, like a reveal.
        """
        cls._assert_can_reveal(credential, requesting_user)
        secret = credential.get_totp_secret()
        if not secret:
            raise ValueError("This credential has no authenticator secret.")
        CredentialAccessLog.objects.create(
            credential=credential,
            user=requesting_user,
            action=CredentialAccessLog.Action.TOTP_CODE,
            ip_address=ip_address,
        )
        now = time.time()
        return {
            "code": pyotp.TOTP(secret).at(now),
            "period": cls.TOTP_PERIOD,
            "expires_in": cls.TOTP_PERIOD - int(now) % cls.TOTP_PERIOD,
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
