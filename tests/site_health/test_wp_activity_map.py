from apps.site_health.models import SiteEvent
from apps.site_health.wp_activity_map import SUPPORTED_WP_TYPES, map_event


def test_maps_user_created_to_users_category():
    event_type, category, severity = map_event("user_created")
    assert event_type == SiteEvent.EventType.WP_USER_CREATED
    assert category == SiteEvent.Category.USERS
    assert severity == SiteEvent.Severity.WARNING


def test_role_change_is_warning_not_info():
    _, _, severity = map_event("user_role_changed")
    assert severity == SiteEvent.Severity.WARNING


def test_post_update_is_info():
    event_type, category, severity = map_event("post_updated")
    assert event_type == SiteEvent.EventType.WP_POST_UPDATED
    assert category == SiteEvent.Category.CONTENT
    assert severity == SiteEvent.Severity.INFO


def test_buffer_overflow_is_critical():
    _, _, severity = map_event("buffer_overflow")
    assert severity == SiteEvent.Severity.CRITICAL


def test_unknown_type_returns_none():
    assert map_event("not_a_real_hook") is None


def test_supported_types_matches_table():
    assert "plugin_activated" in SUPPORTED_WP_TYPES
    assert "not_a_real_hook" not in SUPPORTED_WP_TYPES


def test_every_supported_type_maps_to_a_real_enum_value():
    valid = {c.value for c in SiteEvent.EventType}
    for wp_type in SUPPORTED_WP_TYPES:
        event_type, _, _ = map_event(wp_type)
        assert event_type in valid, wp_type
