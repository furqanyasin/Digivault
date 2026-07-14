"""Per-member feature access — shared between views and serializers.

`feature_access` gates which app sections a member sees. It applies to every
role except owner (owner always has full access). Assigning a role seeds a
default preset that a manager can then fine-tune per member.
"""

from __future__ import annotations

FEATURE_KEYS = frozenset({
    "websites", "clients", "monitors", "status_pages",
    "alerts", "reports", "renewals", "credentials", "activity_log",
})

# Renewal Center is manager-only, so it's excluded from non-manager presets.
_ALL = sorted(FEATURE_KEYS)
_MEMBER = sorted(FEATURE_KEYS - {"renewals"})

ROLE_DEFAULT_FEATURES = {
    "owner": _ALL,
    "manager": _ALL,
    "developer": _MEMBER,
    "viewer": _MEMBER,
    "editor": _MEMBER,
    "seo": _MEMBER,
    "custom": [],
}


def default_features(role: str) -> list[str]:
    """The starting feature set for a role (a preset, not a hard limit)."""
    return list(ROLE_DEFAULT_FEATURES.get(role, _MEMBER))


def effective_features(role: str, feature_access) -> list[str]:
    """Features a member actually has: owner = all; otherwise their stored
    feature_access, falling back to the role default when unset (legacy rows)."""
    if role == "owner":
        return list(_ALL)
    if feature_access:
        return list(feature_access)
    return default_features(role)
