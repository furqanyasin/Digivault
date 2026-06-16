import pytest

from apps.monitors.models import NotificationChannel
from apps.monitors.notifications import resolve_channels
from apps.websites.models import Website


@pytest.mark.django_db
def test_resolve_channels_prefers_website_channel(team):
    ch = NotificationChannel.objects.create(team=team, name="Site CH", channel_type="email", is_active=True, config={"addresses": ["a@b.com"]})
    other = NotificationChannel.objects.create(team=team, name="Team CH", channel_type="email", is_active=True, config={"addresses": ["t@b.com"]})  # noqa: F841
    w = Website.objects.create(team=team, name="S", domain="ch.example", notification_channel=ch)

    channels = resolve_channels(w)
    assert [c.id for c in channels] == [ch.id]


@pytest.mark.django_db
def test_resolve_channels_falls_back_to_team(team):
    ch = NotificationChannel.objects.create(team=team, name="Team CH", channel_type="email", is_active=True, config={"addresses": ["t@b.com"]})
    w = Website.objects.create(team=team, name="S", domain="ch2.example")  # no channel set

    ids = {c.id for c in resolve_channels(w)}
    assert ch.id in ids


@pytest.mark.django_db
def test_patch_sets_website_channel(auth_client, team):
    ch = NotificationChannel.objects.create(team=team, name="CH", channel_type="email", is_active=True, config={"addresses": ["a@b.com"]})
    w = Website.objects.create(team=team, name="S", domain="ch3.example")
    resp = auth_client.patch(f"/api/v1/websites/{w.id}/", {"notification_channel": str(ch.id)}, format="json")
    assert resp.status_code == 200
    w.refresh_from_db()
    assert w.notification_channel_id == ch.id
