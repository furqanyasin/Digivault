from __future__ import annotations

import logging

from apps.common.client_ip import client_ip

logger = logging.getLogger(__name__)


def site_meta(obj, **extra) -> dict:
    """Audit metadata tagging the website a record belongs to.

    Most site-scoped actions record the sub-resource as the resource (a report,
    a monitor, a credential), which leaves nothing pointing at the website — so
    the Activity Log's Website column and its ?website_id= filter both come up
    empty. Passing this as `metadata` fixes both, since they already read
    metadata["website_id"].

    Returns just `extra` when the record isn't tied to a website (a team-level
    credential, say), so it is always safe to call.
    """
    meta = dict(extra)
    website_id = getattr(obj, "website_id", None)
    if website_id:
        meta["website_id"] = str(website_id)
    # A credential can belong to a client with no website (their Search
    # Console, their registrar), so it carries the client too — that is what
    # lets the Activity Log's client filter find it.
    client_id = getattr(obj, "client_id", None)
    if client_id:
        meta["client_id"] = str(client_id)
    return meta


class AuditService:
    """Central point for writing ActivityLog records.

    All arguments except actor, action, and team are optional.
    Failures are caught and logged — audit writes must never crash the caller.
    """

    @staticmethod
    def log(
        actor,
        action: str,
        team,
        description: str = "",
        resource_type: str = "",
        resource_id: str = "",
        ip_address: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        # ActivityLog.team is non-nullable, so a teamless event (a failed login
        # for an unknown email, a user with no active team) would raise an
        # IntegrityError here. Catching it is not enough: on Postgres the failed
        # INSERT aborts the surrounding transaction, so the caller's own writes
        # start failing too. Skip the write instead.
        if team is None:
            logger.debug(
                "AuditService.log skipped — no team: actor=%s action=%s",
                getattr(actor, "email", actor), action,
            )
            return

        try:
            from apps.audit.models import ActivityLog

            ActivityLog.objects.create(
                actor=actor,
                team=team,
                action=action,
                description=description,
                resource_type=resource_type,
                resource_id=str(resource_id) if resource_id else "",
                ip_address=ip_address,
                metadata=metadata or {},
            )
        except Exception:
            logger.exception(
                "AuditService.log failed: actor=%s action=%s team=%s",
                getattr(actor, "email", actor),
                action,
                getattr(team, "name", team),
            )

    @staticmethod
    def log_request(request, action: str, description: str = "", resource_type: str = "", resource_id: str = "", metadata: dict | None = None) -> None:
        """Convenience wrapper that extracts actor, team, and IP from a DRF request."""
        actor = request.user if request.user.is_authenticated else None
        team = getattr(actor, "active_team", None) if actor else None
        if not team:
            return
        ip = _get_ip(request)
        AuditService.log(
            actor=actor,
            action=action,
            team=team,
            description=description,
            resource_type=resource_type,
            resource_id=resource_id,
            ip_address=ip,
            metadata=metadata,
        )


def _get_ip(request) -> str | None:
    # Resolved once, by uvicorn — see apps/common/client_ip.py for why this
    # no longer reads X-Forwarded-For itself.
    return client_ip(request)
