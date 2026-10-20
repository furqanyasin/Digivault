"""What each plan includes, and the one check every create path calls.

Prices and limits here are the single source of truth. The pricing page on
the marketing site mirrors them by hand, so change both together.

`None` means unlimited. A limit is checked when something is created, never
retroactively: a downgraded team keeps what it has and cannot add more.
"""

from __future__ import annotations

from django.conf import settings
from rest_framework import status
from rest_framework.exceptions import APIException

UNLIMITED = None

PLAN_LIMITS: dict[str, dict[str, int | None]] = {
    "free": {
        "websites": 1,
        "monitors": 3,
        "members": 1,
        "status_pages": 1,
        "min_check_interval": 300,
    },
    "starter": {
        "websites": 10,
        "monitors": 50,
        "members": 3,
        "status_pages": 3,
        "min_check_interval": 60,
    },
    "agency": {
        "websites": 30,
        "monitors": 150,
        "members": 10,
        "status_pages": 10,
        "min_check_interval": 60,
    },
    "agency_pro": {
        "websites": 75,
        "monitors": 400,
        "members": UNLIMITED,
        "status_pages": UNLIMITED,
        "min_check_interval": 30,
    },
    "enterprise": {
        "websites": UNLIMITED,
        "monitors": UNLIMITED,
        "members": UNLIMITED,
        "status_pages": UNLIMITED,
        "min_check_interval": 30,
    },
    "internal": {
        "websites": UNLIMITED,
        "monitors": UNLIMITED,
        "members": UNLIMITED,
        "status_pages": UNLIMITED,
        "min_check_interval": 30,
    },
}

_LABELS = {
    "websites": ("website", "websites"),
    "monitors": ("uptime monitor", "uptime monitors"),
    "members": ("team member", "team members"),
    "status_pages": ("status page", "status pages"),
}


class PlanLimitReached(APIException):
    status_code = status.HTTP_402_PAYMENT_REQUIRED
    default_code = "plan_limit"
    default_detail = "Your plan limit is reached. Upgrade to add more."


def limits_for(team) -> dict[str, int | None]:
    plan = getattr(team, "plan", None) or "free"
    return PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])


def limit(team, key: str) -> int | None:
    if not getattr(settings, "ENFORCE_PLAN_LIMITS", True):
        return UNLIMITED
    return limits_for(team).get(key)


def _count(team, key: str) -> int:
    if key == "websites":
        from apps.websites.models import Website
        return Website.objects.filter(team=team).count()
    if key == "monitors":
        from apps.monitors.models import Monitor
        return Monitor.objects.filter(team=team).count()
    if key == "members":
        from apps.accounts.models import TeamInvitation, TeamMembership
        # Pending invitations hold a seat, or a free owner could send ten
        # invitations and have all ten accepted.
        pending = TeamInvitation.objects.filter(team=team, accepted=False).count()
        return TeamMembership.objects.filter(team=team).count() + pending
    if key == "status_pages":
        from apps.status_pages.models import StatusPage
        return StatusPage.objects.filter(team=team).count()
    raise KeyError(key)


def usage(team) -> dict[str, dict[str, int | None]]:
    """Used and allowed for every counted limit, for the settings page."""
    return {
        key: {"used": _count(team, key), "limit": limit(team, key)}
        for key in _LABELS
    }


def can_add(team, key: str, adding: int = 1) -> bool:
    cap = limit(team, key)
    return cap is None or _count(team, key) + adding <= cap


def ensure_can_add(team, key: str, adding: int = 1) -> None:
    """Raise a 402 with code `plan_limit` when one more would pass the cap."""
    if team is None or can_add(team, key, adding):
        return
    cap = limit(team, key)
    singular, plural = _LABELS[key]
    noun = singular if cap == 1 else plural
    plan_name = (team.get_plan_display() if hasattr(team, "get_plan_display") else team.plan)
    raise PlanLimitReached(
        f"The {plan_name} plan includes {cap} {noun}. Upgrade your plan to add more."
    )


def ensure_check_interval(team, seconds: int | None) -> None:
    if team is None or seconds is None:
        return
    floor = limit(team, "min_check_interval")
    if floor is not None and seconds < floor:
        minutes = floor // 60
        span = f"{minutes} minute{'s' if minutes != 1 else ''}" if floor >= 60 else f"{floor} seconds"
        raise PlanLimitReached(
            f"Your plan checks at most every {span}. Upgrade for faster checks."
        )
