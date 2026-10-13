"""WP Connect hook name -> (SiteEvent.EventType, category, severity).

An explicit table, not a derivation. The snippet's wire names are a contract
with pasted PHP that we cannot redeploy, so they are deliberately decoupled
from the Django enum values — renaming a `SiteEvent.EventType` must never
silently stop accepting events from sites already in the field.

Severity is assigned here rather than by the snippet for the same reason: it is
a product judgement we want to be able to change without a re-paste.
"""
from __future__ import annotations

from apps.site_health.models import SiteEvent

_E = SiteEvent.EventType
_C = SiteEvent.Category
_S = SiteEvent.Severity

# wire name -> (event type, category, severity)
_TABLE: dict[str, tuple[str, str, str]] = {
    # Users. Account and role changes are WARNING, not INFO: on a client site
    # the agency did not touch, a new user is the single most useful early
    # signal that something is wrong.
    "login": (_E.WP_LOGIN, _C.USERS, _S.INFO),
    "login_failed": (_E.WP_LOGIN_FAILED, _C.USERS, _S.INFO),
    "user_created": (_E.WP_USER_CREATED, _C.USERS, _S.WARNING),
    "user_updated": (_E.WP_USER_UPDATED, _C.USERS, _S.INFO),
    "user_role_changed": (_E.WP_USER_ROLE_CHANGED, _C.USERS, _S.WARNING),
    "user_deleted": (_E.WP_USER_DELETED, _C.USERS, _S.WARNING),
    "password_reset": (_E.WP_PASSWORD_RESET, _C.USERS, _S.INFO),
    # Plugins and themes.
    "plugin_activated": (_E.WP_PLUGIN_ACTIVATED, _C.PLUGINS, _S.INFO),
    "plugin_deactivated": (_E.WP_PLUGIN_DEACTIVATED, _C.PLUGINS, _S.WARNING),
    "plugin_updated": (_E.WP_PLUGIN_UPDATED, _C.PLUGINS, _S.INFO),
    "plugin_deleted": (_E.WP_PLUGIN_DELETED, _C.PLUGINS, _S.WARNING),
    "theme_switched": (_E.WP_THEME_SWITCHED, _C.THEMES, _S.WARNING),
    "theme_updated": (_E.WP_THEME_UPDATED, _C.THEMES, _S.INFO),
    "theme_deleted": (_E.WP_THEME_DELETED, _C.THEMES, _S.WARNING),
    "core_updated": (_E.WP_CORE_UPDATED, _C.CORE, _S.INFO),
    # Content.
    "post_published": (_E.WP_POST_PUBLISHED, _C.CONTENT, _S.INFO),
    "post_updated": (_E.WP_POST_UPDATED, _C.CONTENT, _S.INFO),
    "post_trashed": (_E.WP_POST_TRASHED, _C.CONTENT, _S.INFO),
    "post_deleted": (_E.WP_POST_DELETED, _C.CONTENT, _S.WARNING),
    # Commerce.
    "order_status_changed": (_E.WP_ORDER_STATUS_CHANGED, _C.COMMERCE, _S.INFO),
    "product_updated": (_E.WP_PRODUCT_UPDATED, _C.COMMERCE, _S.INFO),
    "order_refunded": (_E.WP_ORDER_REFUNDED, _C.COMMERCE, _S.INFO),
    # Self-reported collector health. CRITICAL because it means events for this
    # site were dropped on the client and can never be recovered.
    "buffer_overflow": (_E.WP_BUFFER_OVERFLOW, _C.FILES, _S.CRITICAL),
    # Reserved: the snippet does not send this today (the walk manifest is
    # diffed server-side), but a future snippet reporting a change directly
    # must not be rejected as an unknown type.
    "file_changed": (_E.WP_FILE_CHANGED, _C.FILES, _S.WARNING),
}

SUPPORTED_WP_TYPES = frozenset(_TABLE)


def map_event(wp_type: str) -> tuple[str, str, str] | None:
    """Return (event_type, category, severity), or None for an unknown type.

    None rather than a raise: a site running a newer snippet than this backend
    is a normal state during rollout, and one unrecognised row must not reject
    the whole batch.
    """
    return _TABLE.get(wp_type)
