"""Pointing every website at one notification channel in a single action.

Routing was per-site only, set one select at a time on each website's page. An
agency that adds a ClickUp channel wants every site on it, and doing that by
hand across dozens of sites is where sites get missed — the ones that then
alert nowhere.

The action is manager-only and deliberately total: it also clears any per-site
uptime override, because "same channel everywhere" that quietly leaves downtime
alerts routed elsewhere is the failure it exists to prevent.
"""
import pytest
from rest_framework.test import APIClient

from apps.accounts.models import TeamMembership, User
from apps.accounts.services import TeamService
from apps.audit.models import ActivityLog
from apps.monitors.models import NotificationChannel
from apps.websites.models import Website

pytestmark = pytest.mark.django_db


@pytest.fixture
def team(db):
    owner = User.objects.create_user(email="applyall_o@test.com", password="Pass123!")
    return TeamService.create(name="ApplyAll Agency", owner=owner)


@pytest.fixture
def channel(team):
    return NotificationChannel.objects.create(
        team=team, name="Web Team ClickUp", channel_type="clickup",
        config={"chat_url": "https://app.clickup.com/9001/chat/r/chan-1"},
    )


@pytest.fixture
def websites(team):
    return [
        Website.objects.create(team=team, name=f"Site {i}", domain=f"site{i}.io")
        for i in range(3)
    ]


def _client_for(user, team):
    user.active_team = team
    user.save(update_fields=["active_team"])
    api = APIClient()
    api.force_authenticate(user=user)
    return api


def _member(team, role):
    user = User.objects.create_user(email=f"applyall_{role}@test.com", password="Pass123!")
    TeamMembership.objects.create(user=user, team=team, role=role)
    return user


def _url(channel):
    return f"/api/v1/notification-channels/{channel.pk}/apply-to-all-websites/"


def test_every_website_is_pointed_at_the_channel(team, channel, websites):
    owner = team.owner
    resp = _client_for(owner, team).post(_url(channel))

    assert resp.status_code == 200
    assert resp.data["updated"] == 3
    for site in websites:
        site.refresh_from_db()
        assert site.notification_channel_id == channel.pk


def test_a_per_site_uptime_override_is_cleared(team, channel, websites):
    other = NotificationChannel.objects.create(
        team=team, name="Old", channel_type="email", config={"addresses": ["a@b.io"]},
    )
    websites[0].uptime_notification_channel = other
    websites[0].save(update_fields=["uptime_notification_channel"])

    _client_for(team.owner, team).post(_url(channel))

    websites[0].refresh_from_db()
    assert websites[0].uptime_notification_channel_id is None
    assert websites[0].notification_channel_id == channel.pk


def test_websites_on_another_team_are_untouched(team, channel, websites):
    stranger = User.objects.create_user(email="applyall_x@test.com", password="Pass123!")
    other_team = TeamService.create(name="Other Agency", owner=stranger)
    foreign = Website.objects.create(team=other_team, name="Foreign", domain="foreign.io")

    _client_for(team.owner, team).post(_url(channel))

    foreign.refresh_from_db()
    assert foreign.notification_channel_id is None


def test_a_developer_cannot_reroute_the_whole_team(team, channel, websites):
    dev = _member(team, TeamMembership.Role.DEVELOPER)

    resp = _client_for(dev, team).post(_url(channel))

    assert resp.status_code == 403
    websites[0].refresh_from_db()
    assert websites[0].notification_channel_id is None


def test_another_teams_channel_is_not_found(team, websites):
    stranger = User.objects.create_user(email="applyall_y@test.com", password="Pass123!")
    other_team = TeamService.create(name="Y Agency", owner=stranger)
    foreign_channel = NotificationChannel.objects.create(
        team=other_team, name="Theirs", channel_type="email", config={"addresses": ["y@y.io"]},
    )

    resp = _client_for(team.owner, team).post(_url(foreign_channel))

    assert resp.status_code == 404


def test_the_bulk_reroute_is_audited(team, channel, websites):
    _client_for(team.owner, team).post(_url(channel))

    log = ActivityLog.objects.filter(
        action=ActivityLog.Action.NOTIFICATION_CHANNEL_APPLIED_ALL
    ).first()
    assert log is not None
    assert "Web Team ClickUp" in log.description
    assert "3" in log.description
