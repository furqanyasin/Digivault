import pytest
from django.utils import timezone
from django.utils.timezone import timedelta

from apps.alerts.models import AlertRule, Notification
from apps.site_health.models import SiteEvent
from apps.site_health.wp_alerts import (
    LOGIN_FAILURE_BURST,
    LOGIN_FAILURE_WINDOW_MINUTES,
    alertable_reason,
    dispatch_for_site_event,
)
from apps.websites.models import Website


@pytest.fixture
def website(db, team):
    return Website.objects.create(team=team, name="Acme", domain="acme.test")


@pytest.fixture
def rule(db, team):
    return AlertRule.objects.create(
        team=team, channel=AlertRule.Channel.IN_APP, min_severity="low", is_active=True
    )


def make(website, event_type, **kw):
    defaults = {
        "website": website,
        "event_type": event_type,
        "summary": "something happened",
        "source": SiteEvent.Source.WP_CONNECT,
        "occurred_at": timezone.now(),
    }
    defaults.update(kw)
    return SiteEvent.objects.create(**defaults)


# --- alertable_reason --------------------------------------------------------


def test_admin_user_creation_is_alertable(website):
    event = make(
        website, SiteEvent.EventType.WP_USER_CREATED, details={"role": "administrator"}
    )
    assert alertable_reason(event) == "wp.admin_user_created"


def test_subscriber_creation_is_not_alertable(website):
    """A shop or membership site registers customers all day. Alerting on every
    one of them trains people to ignore the alert that matters."""
    event = make(
        website, SiteEvent.EventType.WP_USER_CREATED, details={"role": "subscriber"}
    )
    assert alertable_reason(event) is None


def test_escalation_to_admin_is_alertable(website):
    event = make(
        website,
        SiteEvent.EventType.WP_USER_ROLE_CHANGED,
        details={"old_role": "editor", "new_role": "administrator"},
    )
    assert alertable_reason(event) == "wp.role_escalated"


def test_demotion_from_admin_is_not_alertable(website):
    event = make(
        website,
        SiteEvent.EventType.WP_USER_ROLE_CHANGED,
        details={"old_role": "administrator", "new_role": "editor"},
    )
    assert alertable_reason(event) is None


def test_change_outside_wp_admin_is_alertable(website):
    event = make(
        website,
        SiteEvent.EventType.PLUGIN_UPDATED,
        source=SiteEvent.Source.PASSIVE,
        category=SiteEvent.Category.PLUGINS,
        summary="plugin wp-rocket updated — changed outside wp-admin",
    )
    assert alertable_reason(event) == "wp.plugin_changed_outside_admin"


def test_ordinary_post_edit_is_not_alertable(website):
    event = make(website, SiteEvent.EventType.WP_POST_UPDATED)
    assert alertable_reason(event) is None


def test_login_failure_burst_is_alertable(website):
    for _ in range(LOGIN_FAILURE_BURST - 1):
        make(website, SiteEvent.EventType.WP_LOGIN_FAILED)
    last = make(website, SiteEvent.EventType.WP_LOGIN_FAILED)
    assert alertable_reason(last) == "wp.login_failed_burst"


def test_a_few_login_failures_are_not_alertable(website):
    make(website, SiteEvent.EventType.WP_LOGIN_FAILED)
    last = make(website, SiteEvent.EventType.WP_LOGIN_FAILED)
    assert alertable_reason(last) is None


def test_old_login_failures_do_not_count_towards_the_burst(website):
    stale = timezone.now() - timedelta(minutes=LOGIN_FAILURE_WINDOW_MINUTES + 5)
    for _ in range(LOGIN_FAILURE_BURST):
        make(website, SiteEvent.EventType.WP_LOGIN_FAILED, occurred_at=stale)
    last = make(website, SiteEvent.EventType.WP_LOGIN_FAILED)
    assert alertable_reason(last) is None


# --- dispatch ----------------------------------------------------------------


def test_dispatch_creates_a_notification_carrying_the_event(website, rule):
    event = make(
        website, SiteEvent.EventType.WP_USER_CREATED, details={"role": "administrator"}
    )
    notifications = dispatch_for_site_event(event)
    assert len(notifications) == 1
    notif = notifications[0]
    assert notif.site_event_id == event.id
    assert notif.website_id == website.id


def test_dispatch_is_a_no_op_for_an_unremarkable_event(website, rule):
    event = make(website, SiteEvent.EventType.WP_POST_UPDATED)
    assert dispatch_for_site_event(event) == []
    assert Notification.objects.count() == 0


def test_dispatch_with_no_active_rule_creates_nothing(website):
    event = make(
        website, SiteEvent.EventType.WP_USER_CREATED, details={"role": "administrator"}
    )
    assert dispatch_for_site_event(event) == []


def test_email_body_describes_the_event_not_just_the_website(website, rule):
    from apps.alerts.delivery import _build_email_body

    event = make(
        website,
        SiteEvent.EventType.WP_USER_CREATED,
        summary="User bob created (administrator)",
        actor="jdoe",
        actor_ip="41.1.2.3",
        details={"role": "administrator"},
    )
    notif = dispatch_for_site_event(event)[0]
    body = _build_email_body(notif)
    assert "User bob created (administrator)" in body
    assert "jdoe" in body
    assert "41.1.2.3" in body
