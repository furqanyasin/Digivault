import pytest
from unittest.mock import patch

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.alerts.models import AlertRule, Notification
from apps.alerts.services import AlertService
from apps.scripts.models import Script, ScriptChange
from apps.websites.models import Website


@pytest.fixture
def owner(db):
    return User.objects.create_user(email="al_owner@test.com", password="Pass123!")


@pytest.fixture
def team(owner):
    return TeamService.create(name="Alert Agency", owner=owner)


@pytest.fixture
def website(team):
    return Website.objects.create(team=team, name="Alert Site", domain="alert.io")


def _make_change(website, severity="high", change_type="added"):
    return ScriptChange.objects.create(
        website=website,
        change_type=change_type,
        severity=severity,
        description=f"Test {change_type} change",
    )


@pytest.mark.django_db
class TestAlertService:
    def test_no_rules_produces_no_notifications(self, website):
        change = _make_change(website)
        notifications = AlertService.dispatch_for_change(change)
        assert notifications == []

    def test_matching_global_rule_creates_notification(self, website, team):
        AlertRule.objects.create(
            team=team,
            website=None,
            channel=AlertRule.Channel.IN_APP,
            min_severity="high",
            delivery_mode=AlertRule.DeliveryMode.IMMEDIATE,
        )
        change = _make_change(website, severity="high")
        notifications = AlertService.dispatch_for_change(change)
        assert len(notifications) == 1
        assert notifications[0].channel == AlertRule.Channel.IN_APP

    def test_severity_below_min_skips_notification(self, website, team):
        AlertRule.objects.create(
            team=team,
            website=None,
            channel=AlertRule.Channel.IN_APP,
            min_severity="high",  # only high
            delivery_mode=AlertRule.DeliveryMode.IMMEDIATE,
        )
        change = _make_change(website, severity="low")
        notifications = AlertService.dispatch_for_change(change)
        assert notifications == []

    def test_per_website_rule_shadows_global(self, website, team):
        AlertRule.objects.create(
            team=team, website=None,
            channel=AlertRule.Channel.IN_APP,
            min_severity="low",
            delivery_mode=AlertRule.DeliveryMode.IMMEDIATE,
        )
        # Per-website rule for same channel — should shadow the global one
        AlertRule.objects.create(
            team=team, website=website,
            channel=AlertRule.Channel.IN_APP,
            min_severity="high",  # tighter threshold
            delivery_mode=AlertRule.DeliveryMode.IMMEDIATE,
        )
        # Low severity change — global rule would match but per-website rule should win
        change = _make_change(website, severity="low")
        notifications = AlertService.dispatch_for_change(change)
        assert notifications == []

    def test_change_type_filter(self, website, team):
        AlertRule.objects.create(
            team=team, website=None,
            channel=AlertRule.Channel.IN_APP,
            min_severity="low",
            change_types=["removed"],  # only removed
            delivery_mode=AlertRule.DeliveryMode.IMMEDIATE,
        )
        added_change = _make_change(website, change_type="added")
        assert AlertService.dispatch_for_change(added_change) == []

        removed_change = _make_change(website, change_type="removed")
        assert len(AlertService.dispatch_for_change(removed_change)) == 1


@pytest.mark.django_db
class TestNotificationAPI:
    def _client(self, user):
        from rest_framework.test import APIClient
        c = APIClient()
        resp = c.post(
            "/api/v1/auth/token/",
            {"email": user.email, "password": "Pass123!"},
            format="json",
        )
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")
        return c

    def test_list_notifications(self, website, owner, team):
        change = _make_change(website)
        Notification.objects.create(
            team=team, website=website, script_change=change,
            channel=AlertRule.Channel.IN_APP,
        )
        client = self._client(owner)
        resp = client.get("/api/v1/notifications/")
        assert resp.status_code == 200
        assert len(resp.data) >= 1

    def test_mark_all_read(self, website, owner, team):
        change = _make_change(website)
        Notification.objects.create(
            team=team, website=website, script_change=change,
            channel=AlertRule.Channel.IN_APP, read=False,
        )
        client = self._client(owner)
        resp = client.post("/api/v1/notifications/mark-read/", {}, format="json")
        assert resp.status_code == 200
        assert Notification.objects.filter(team=team, read=False).count() == 0

    def test_create_alert_rule(self, owner, team):
        client = self._client(owner)
        resp = client.post(
            "/api/v1/alert-rules/",
            {
                "channel": "in_app",
                "min_severity": "high",
                "change_types": [],
                "delivery_mode": "immediate",
            },
            format="json",
        )
        assert resp.status_code == 201
