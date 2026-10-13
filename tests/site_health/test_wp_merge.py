import pytest
from django.utils import timezone
from django.utils.timezone import timedelta

from apps.site_health.models import SiteEvent
from apps.site_health.wp_merge import (
    MERGE_WINDOW_HOURS,
    component_key,
    flag_unattributed_component_changes,
    merge_into_passive,
)
from apps.websites.models import Website


@pytest.fixture
def website(db, team):
    """A site with WP Connect live — the only kind the merge rule concerns."""
    return Website.objects.create(
        team=team,
        name="Acme",
        domain="acme.test",
        wp_connect_version=2,
        wp_connect_last_ack=timezone.now(),
    )


def passive(website, slug, version, age_minutes=5, kind="plugin"):
    return SiteEvent.objects.create(
        website=website,
        event_type=SiteEvent.EventType.PLUGIN_UPDATED,
        summary=f"plugin {slug} updated from v1.0 to v{version}",
        source=SiteEvent.Source.PASSIVE,
        category=SiteEvent.Category.PLUGINS,
        details={"kind": kind, "slug": slug, "new_version": version},
        occurred_at=timezone.now() - timedelta(minutes=age_minutes),
    )


# --- component_key -----------------------------------------------------------


def test_component_key_prefers_new_version():
    assert component_key({"kind": "plugin", "slug": "wp-rocket", "new_version": "3.5"}) == (
        "plugin",
        "wp-rocket",
        "3.5",
    )


def test_component_key_falls_back_to_version():
    assert component_key({"kind": "theme", "slug": "astra", "version": "2.1"}) == (
        "theme",
        "astra",
        "2.1",
    )


def test_component_key_is_none_without_a_slug():
    assert component_key({"kind": "plugin"}) is None


def test_component_key_lowercases_so_case_never_blocks_a_merge():
    assert component_key({"kind": "Plugin", "slug": "WP-Rocket", "version": "1"}) == (
        "plugin",
        "wp-rocket",
        "1",
    )


# --- merge_into_passive ------------------------------------------------------


def test_merge_upgrades_the_passive_row_in_place(website):
    row = passive(website, "wp-rocket", "3.5")
    merged = merge_into_passive(
        website,
        {"kind": "plugin", "slug": "wp-rocket", "version": "3.5"},
        actor="jdoe",
        actor_wp_id=7,
        actor_ip="41.1.2.3",
        sequence=99,
    )
    assert merged is True
    row.refresh_from_db()
    assert row.source == SiteEvent.Source.WP_CONNECT
    assert row.actor == "jdoe"
    assert row.actor_wp_id == 7
    assert row.actor_ip == "41.1.2.3"
    assert row.sequence == 99
    # Still exactly one row: the attributed event does not create a second.
    assert SiteEvent.objects.filter(website=website).count() == 1


def test_merge_declines_when_versions_differ(website):
    passive(website, "wp-rocket", "3.5")
    assert (
        merge_into_passive(
            website, {"kind": "plugin", "slug": "wp-rocket", "version": "9.9"}, actor="x"
        )
        is False
    )


def test_versionless_hook_claims_matching_passive_component(website):
    row = passive(website, "elementor-pro", "4.0.1")
    assert merge_into_passive(
        website, {"kind": "plugin", "slug": "elementor-pro"}, actor="admin"
    ) is True
    row.refresh_from_db()
    assert row.source == SiteEvent.Source.WP_CONNECT
    assert row.actor == "admin"


def test_merge_declines_outside_the_window(website):
    passive(website, "wp-rocket", "3.5", age_minutes=MERGE_WINDOW_HOURS * 60 + 1)
    assert (
        merge_into_passive(
            website, {"kind": "plugin", "slug": "wp-rocket", "version": "3.5"}, actor="x"
        )
        is False
    )


def test_merge_declines_when_no_passive_row_exists(website):
    assert (
        merge_into_passive(
            website, {"kind": "plugin", "slug": "ghost", "version": "1.0"}, actor="x"
        )
        is False
    )


def test_merge_never_touches_an_already_attributed_row(website):
    row = passive(website, "wp-rocket", "3.5")
    row.source = SiteEvent.Source.WP_CONNECT
    row.actor = "someone-else"
    row.save(update_fields=["source", "actor"])
    assert (
        merge_into_passive(
            website, {"kind": "plugin", "slug": "wp-rocket", "version": "3.5"}, actor="x"
        )
        is False
    )
    row.refresh_from_db()
    assert row.actor == "someone-else"


# --- flag_unattributed_component_changes -------------------------------------


def test_old_unmatched_passive_change_is_flagged(website):
    row = passive(website, "wp-rocket", "3.5", age_minutes=MERGE_WINDOW_HOURS * 60 + 60)
    assert flag_unattributed_component_changes() == 1
    row.refresh_from_db()
    assert row.severity == SiteEvent.Severity.WARNING
    assert "outside wp-admin" in row.summary


def test_recent_passive_change_is_left_alone(website):
    # Still inside the window — its attributed twin may yet arrive.
    row = passive(website, "wp-rocket", "3.5", age_minutes=5)
    assert flag_unattributed_component_changes() == 0
    row.refresh_from_db()
    assert "outside wp-admin" not in row.summary


def test_flagging_is_idempotent(website):
    passive(website, "wp-rocket", "3.5", age_minutes=MERGE_WINDOW_HOURS * 60 + 60)
    assert flag_unattributed_component_changes() == 1
    assert flag_unattributed_component_changes() == 0


def test_sites_without_wp_connect_are_never_flagged(website):
    """The signal is 'a change with no admin action', which only means anything
    where we would have seen the admin action. On a site with no snippet, every
    change is unattributed and flagging them all would be pure noise."""
    website.wp_connect_last_ack = None
    website.save(update_fields=["wp_connect_last_ack"])
    passive(website, "wp-rocket", "3.5", age_minutes=MERGE_WINDOW_HOURS * 60 + 60)
    assert flag_unattributed_component_changes() == 0
