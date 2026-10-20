"""Access requests and credential handover.

Two halves of running a shared vault with a team that changes:

- **Requests.** A member who cannot see a credential asks for it; anyone who
  may share it approves, usually for a fixed time. The grant is an ordinary
  `CredentialShare` with `expires_at`, so every access check already honours it
  and it lapses on its own.
- **Handover.** When someone leaves, their credentials move to a named
  colleague, their shares go, and the list of passwords they actually revealed
  is what the team rotates — "everything they could see" is far longer and is
  not what leaked.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.db import transaction
from django.db.models import Count, Max
from django.utils import timezone

from apps.accounts.models import TeamMembership
from apps.credentials import notify
from apps.credentials.models import (
    Credential,
    CredentialAccessLog,
    CredentialAccessRequest,
    CredentialShare,
)
from apps.credentials.permissions import can_modify_credential
from apps.credentials.services import SHAREABLE_ROLES, CredentialService

logger = logging.getLogger(__name__)


class AccessRequestError(Exception):
    """A request that cannot be made or decided; the message is user-facing."""


_name = notify.display_name


def _approver_emails(credential) -> list[str]:
    return sorted(notify.approver_emails(credential))


def _mail(subject: str, body: str, recipients: list[str]) -> None:
    notify.mail(subject, body, recipients)


def _duration_label(hours: int | None) -> str:
    if not hours:
        return "permanently"
    if hours % 24 == 0:
        days = hours // 24
        return f"for {days} day{'s' if days != 1 else ''}"
    return f"for {hours} hours"


def requestable_for(user, team):
    """Team credentials `user` cannot see but could be granted.

    Metadata only, for the request picker. Exposes labels across the team on
    purpose — you cannot ask for something you cannot name — never secrets.
    """
    visible = Credential.objects.visible_to(user).filter(team=team).values("pk")
    return (
        Credential.objects.filter(team=team)
        .exclude(pk__in=visible)
        .select_related("website", "client")
    )


@transaction.atomic
def create_request(user, credential: Credential, reason: str, hours: int | None):
    membership = TeamMembership.objects.filter(user=user, team=credential.team).first()
    if membership is None or membership.role not in SHAREABLE_ROLES:
        raise AccessRequestError(
            "Only member roles can request credentials. Owners and managers already "
            "see the whole vault, and viewers cannot reveal one."
        )
    if Credential.objects.visible_to(user).filter(pk=credential.pk).exists():
        raise AccessRequestError("You already have access to this credential.")
    if hours not in CredentialAccessRequest.DURATION_CHOICES:
        raise AccessRequestError("Unsupported duration.")

    existing = CredentialAccessRequest.objects.filter(
        credential=credential, requester=user, status=CredentialAccessRequest.Status.PENDING
    ).first()
    if existing:
        return existing, False

    req = CredentialAccessRequest.objects.create(
        team=credential.team,
        credential=credential,
        requester=user,
        reason=(reason or "").strip()[:300],
        requested_hours=hours,
    )
    _mail(
        f"[Stacks Monitor] {_name(user)} is asking for '{credential.label}'",
        f"{_name(user)} ({user.email}) asked for access to '{credential.label}' "
        f"{_duration_label(hours)}.\n\n"
        f"Reason: {req.reason or '(none given)'}\n\n"
        "Approve or deny it on the Credentials page in Stacks Monitor.",
        [e for e in _approver_emails(credential) if e != user.email],
    )
    return req, True


@transaction.atomic
def decide_request(
    approver,
    req: CredentialAccessRequest,
    approve: bool,
    hours: int | None = None,
    can_view_password: bool = False,
    note: str = "",
):
    """Approve (creating or extending a share) or deny a pending request."""
    req = CredentialAccessRequest.objects.select_for_update().get(pk=req.pk)
    if req.status != CredentialAccessRequest.Status.PENDING:
        raise AccessRequestError(f"This request was already {req.status}.")
    if not can_modify_credential(approver, req.credential):
        raise AccessRequestError("Only the creator, a manager or an owner can decide this.")
    if approve and hours not in CredentialAccessRequest.DURATION_CHOICES:
        raise AccessRequestError("Unsupported duration.")

    now = timezone.now()
    req.decided_by = approver
    req.decided_at = now
    req.decision_note = (note or "").strip()[:300]

    if approve:
        expires_at = now + timedelta(hours=hours) if hours else None
        share = CredentialShare.objects.filter(credential=req.credential, user=req.requester).first()
        if share is not None:
            # Never shorten what they already have: a permanent share stays
            # permanent, and a longer temporary one keeps its later expiry.
            still_active = share.expires_at is None or share.expires_at > now
            if still_active and (share.expires_at is None or (expires_at and share.expires_at > expires_at)):
                expires_at = share.expires_at
            share.expires_at = expires_at
            # A lapsed share's old reveal flag is not carried into the new grant.
            share.can_view_password = (
                share.can_view_password or can_view_password if still_active else can_view_password
            )
            share.shared_by = approver
            share.save(update_fields=["expires_at", "can_view_password", "shared_by", "updated_at"])
        else:
            share = CredentialShare.objects.create(
                credential=req.credential,
                user=req.requester,
                shared_by=approver,
                can_view_password=can_view_password,
                expires_at=expires_at,
            )
        req.status = CredentialAccessRequest.Status.APPROVED
        req.granted_until = share.expires_at
        req.can_view_password = share.can_view_password
    else:
        req.status = CredentialAccessRequest.Status.DENIED
    req.save()

    verdict = (
        f"approved {_duration_label(hours)}" if approve else "denied"
    )
    _mail(
        f"[Stacks Monitor] Your request for '{req.credential.label}' was {'approved' if approve else 'denied'}",
        f"{_name(approver)} {verdict} your request for '{req.credential.label}'."
        + (f"\n\nNote: {req.decision_note}" if req.decision_note else ""),
        [req.requester.email],
    )
    return req


def cancel_request(user, req: CredentialAccessRequest) -> CredentialAccessRequest:
    if req.requester_id != user.id:
        raise AccessRequestError("Only the person who asked can cancel a request.")
    if req.status != CredentialAccessRequest.Status.PENDING:
        raise AccessRequestError(f"This request was already {req.status}.")
    req.status = CredentialAccessRequest.Status.CANCELLED
    req.save(update_fields=["status", "updated_at"])
    return req


def requests_for_approver(user, team):
    """Pending requests on credentials `user` may share."""
    pending = (
        CredentialAccessRequest.objects.filter(
            team=team, status=CredentialAccessRequest.Status.PENDING
        )
        .select_related("credential", "credential__team", "requester")
    )
    return [r for r in pending if can_modify_credential(user, r.credential)]


# ── Handover ──────────────────────────────────────────────────────────────────

#: Access-log actions that put a secret in front of the person, i.e. what to
#: rotate after they leave. An edit is not one; a TOTP code expires on its own.
_EXPOSING_ACTIONS = (
    CredentialAccessLog.Action.VIEWED,
    CredentialAccessLog.Action.COPIED_PASSWORD,
    CredentialAccessLog.Action.AUTOFILL,
)


def member_summary(team, member) -> dict:
    """What a member holds and has seen, for the handover screen."""
    exposed = (
        CredentialAccessLog.objects.filter(
            user=member, credential__team=team, action__in=_EXPOSING_ACTIONS
        )
        .values("credential_id", "credential__label", "credential__credential_type")
        .annotate(last_at=Max("created_at"), times=Count("id"))
        .order_by("-last_at")
    )
    from apps.credentials.models import FolderShare

    return {
        "owned_count": Credential.objects.filter(team=team, created_by=member).count(),
        "share_count": CredentialShare.objects.active()
        .filter(credential__team=team, user=member)
        .count()
        + FolderShare.objects.filter(folder__team=team, user=member).count(),
        "revealed": [
            {
                "credential_id": str(row["credential_id"]),
                "label": row["credential__label"],
                "credential_type": row["credential__credential_type"],
                "last_at": row["last_at"],
                "times": row["times"],
            }
            for row in exposed
        ],
    }


@transaction.atomic
def handover(team, member, recipient, revoke_shares: bool) -> dict:
    """Move `member`'s credentials to `recipient`; optionally drop their shares."""
    if member.pk == recipient.pk:
        raise AccessRequestError("Pick someone else to hand the credentials to.")
    if not TeamMembership.objects.filter(team=team, user=recipient).exists():
        raise AccessRequestError("The recipient is not on this team.")
    moved = Credential.objects.filter(team=team, created_by=member).update(created_by=recipient)
    revoked = 0
    if revoke_shares:
        from apps.credentials.models import FolderShare

        revoked, _ = CredentialShare.objects.filter(credential__team=team, user=member).delete()
        folders_revoked, _ = FolderShare.objects.filter(folder__team=team, user=member).delete()
        revoked += folders_revoked
        CredentialAccessRequest.objects.filter(
            team=team, requester=member, status=CredentialAccessRequest.Status.PENDING
        ).update(status=CredentialAccessRequest.Status.CANCELLED)
    return {"moved": moved, "shares_revoked": revoked}


# ── Who has access ───────────────────────────────────────────────────────────


def who_has_access(credential) -> list[dict]:
    """Everyone in the team who can see `credential`, and every route by which.

    Mirrors `CredentialQuerySet.visible_to` route for route — role, creator,
    active share, group grant, department — so the answer to "why can Sara see
    the hosting login?" is a list of reasons, not a guess. A member reached by
    no route is left out.
    """
    from apps.credentials.models import SubTeamCredentialGrant

    team = credential.team
    shares = {
        s.user_id: s
        for s in CredentialShare.objects.active().filter(credential=credential)
    }
    from apps.credentials.models import FolderShare

    folder_shares = (
        {fs.user_id: fs for fs in FolderShare.objects.filter(folder_id=credential.folder_id)}
        if credential.folder_id else {}
    )
    grants_by_group: dict = {}
    for g in SubTeamCredentialGrant.objects.filter(sub_team__team=team).select_related("sub_team"):
        if (
            g.scope == SubTeamCredentialGrant.Scope.ALL
            or (g.scope == SubTeamCredentialGrant.Scope.CREDENTIAL_TYPE
                and g.credential_type == credential.credential_type)
            or (g.scope == SubTeamCredentialGrant.Scope.CREDENTIAL
                and g.credential_id == credential.pk)
            or (g.scope == SubTeamCredentialGrant.Scope.FOLDER
                and credential.folder_id and g.folder_id == credential.folder_id)
        ):
            grants_by_group.setdefault(g.sub_team_id, []).append(g)
    last_used = dict(
        CredentialAccessLog.objects.filter(credential=credential)
        .exclude(user=None)
        .values("user_id")
        .annotate(last=Max("created_at"))
        .values_list("user_id", "last")
    )

    rows = []
    memberships = TeamMembership.objects.filter(team=team).select_related("user", "sub_team")
    for m in memberships:
        routes = []
        if m.role in (TeamMembership.Role.OWNER, TeamMembership.Role.MANAGER):
            routes.append({"kind": "role", "label": m.get_role_display(), "can_view_password": True})
        if credential.created_by_id == m.user_id:
            routes.append({"kind": "creator", "label": "Saved it", "can_view_password": True})
        share = shares.get(m.user_id)
        if share:
            routes.append({
                "kind": "share",
                "label": "Shared directly" if not share.expires_at else "Temporary share",
                "can_view_password": share.can_view_password,
                "expires_at": share.expires_at,
            })
        folder_share = folder_shares.get(m.user_id)
        if folder_share:
            routes.append({
                "kind": "folder",
                "label": f"Folder {credential.folder.name} shared with them",
                "can_view_password": folder_share.can_view_password,
            })
        if m.sub_team_id:
            for g in grants_by_group.get(m.sub_team_id, []):
                is_folder = g.scope == SubTeamCredentialGrant.Scope.FOLDER
                routes.append({
                    "kind": "folder" if is_folder else "group",
                    "label": (
                        f"{m.sub_team.name} · folder {credential.folder.name}" if is_folder
                        else f"{m.sub_team.name} ({g.get_scope_display().lower()})"
                    ),
                    "can_view_password": g.can_view_password,
                })
        if not routes:
            continue
        can_reveal = m.role in CredentialService._REVEAL_ROLES
        rows.append({
            "user_id": str(m.user_id),
            "name": notify.display_name(m.user),
            "email": m.user.email,
            "role": m.role,
            "can_reveal": can_reveal,
            "can_view_password": can_reveal and any(r["can_view_password"] for r in routes),
            "routes": routes,
            "last_used_at": last_used.get(m.user_id),
        })
    rows.sort(key=lambda r: (r["last_used_at"] is None, r["name"].lower()))
    return rows
