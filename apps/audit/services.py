from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


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
    ) -> None:
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
            )
        except Exception:
            logger.exception(
                "AuditService.log failed: actor=%s action=%s team=%s",
                getattr(actor, "email", actor),
                action,
                getattr(team, "name", team),
            )

    @staticmethod
    def log_request(request, action: str, description: str = "", resource_type: str = "", resource_id: str = "") -> None:
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
        )


def _get_ip(request) -> str | None:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")
