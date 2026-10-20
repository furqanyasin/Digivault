"""Team-level ClickUp chat channel settings.

The channel target is stored as a single URL and parsed on use, so these tests
guard the two things that can silently break notifications: an unparseable URL
being accepted, and a PATCH for one field clearing another.
"""
from unittest.mock import patch

import pytest

from apps.accounts.models import TeamMembership, User
from apps.integrations.models import ClickUpMemberLink


def _settings_url(team):
    return f"/api/v1/auth/teams/{team.id}/settings/"


def _channel_url(team):
    return f"/api/v1/auth/teams/{team.id}/settings/clickup-channel/"


def _members_url(team):
    return f"/api/v1/auth/teams/{team.id}/settings/clickup-members/"


FAKE_SYNC = {
    "matched": [
        {"user_id": "u1", "email": "jane@x.io", "clickup_user_id": "11", "clickup_username": "jane"}
    ],
    "unmatched": [{"user_id": "u2", "email": "bob@x.io"}],
    "workspace_id": "9001",
}


def test_patching_the_chat_url_stores_it(auth_client, team):
    resp = auth_client.patch(
        _settings_url(team),
        {"clickup_chat_url": "https://acme.clickup.com/25658037/chat/r/rf0nn-49438"},
        format="json",
    )

    assert resp.status_code == 200
    team.refresh_from_db()
    assert team.clickup_chat_url == "https://acme.clickup.com/25658037/chat/r/rf0nn-49438"
    assert resp.data["clickup_chat_connected"] is True


def test_an_unparseable_chat_url_is_rejected(auth_client, team):
    resp = auth_client.patch(
        _settings_url(team), {"clickup_chat_url": "https://example.com/nope"}, format="json"
    )

    assert resp.status_code == 400
    team.refresh_from_db()
    assert team.clickup_chat_url == ""


def test_an_empty_chat_url_is_an_intentional_clear(auth_client, team):
    team.clickup_chat_url = "https://app.clickup.com/9001/chat/r/chan-77"
    team.save()

    resp = auth_client.patch(_settings_url(team), {"clickup_chat_url": ""}, format="json")

    assert resp.status_code == 200
    team.refresh_from_db()
    assert team.clickup_chat_url == ""
    assert resp.data["clickup_chat_connected"] is False


def test_patching_only_the_chat_url_leaves_token_and_list_intact(auth_client, team):
    team.clickup_api_token = "pk_keepme"
    team.clickup_list_id = "list-42"
    team.clickup_chat_url = ""
    team.save()

    auth_client.patch(
        _settings_url(team),
        {"clickup_chat_url": "https://app.clickup.com/9001/chat/r/chan-77"},
        format="json",
    )

    team.refresh_from_db()
    assert team.clickup_api_token == "pk_keepme"
    assert team.clickup_list_id == "list-42"


# ---------------------------------------------------------------------------
# Channel creation and member mapping endpoints
# ---------------------------------------------------------------------------

def test_creating_the_channel_stores_the_url_and_reports_members(auth_client, team):
    team.clickup_api_token = "pk_test"
    team.save()

    with patch("apps.accounts.views.sync_member_links", return_value=FAKE_SYNC), \
         patch("apps.accounts.views.ClickUpClient") as CU:
        CU.return_value.create_chat_channel.return_value = {
            "id": "chan-77", "url": "https://app.clickup.com/9001/chat/r/chan-77",
        }
        resp = auth_client.post(_channel_url(team), {"name": "Web Team"}, format="json")

    assert resp.status_code == 200
    team.refresh_from_db()
    assert team.clickup_chat_url == "https://app.clickup.com/9001/chat/r/chan-77"
    assert resp.data["matched"][0]["clickup_user_id"] == "11"
    assert resp.data["unmatched"][0]["email"] == "bob@x.io"
    # Matched members go into the channel.
    assert CU.return_value.create_chat_channel.call_args.kwargs["user_ids"] == ["11"]


def test_creating_the_channel_without_a_token_is_a_400(auth_client, team):
    resp = auth_client.post(_channel_url(team), {}, format="json")

    assert resp.status_code == 400


def test_a_viewer_cannot_create_the_channel_or_map_members(api_client, team, db):
    viewer = User.objects.create_user(email="viewer@x.io", password="SecurePass1!")
    TeamMembership.objects.create(user=viewer, team=team, role=TeamMembership.Role.VIEWER)
    tok = api_client.post(
        "/api/v1/auth/token/", {"email": viewer.email, "password": "SecurePass1!"}, format="json"
    ).data["access"]
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {tok}")

    assert api_client.post(_channel_url(team), {}, format="json").status_code == 403
    assert api_client.post(_members_url(team), {}, format="json").status_code == 403


def test_resyncing_members_returns_matched_and_unmatched(auth_client, team):
    team.clickup_api_token = "pk_test"
    team.save()

    with patch("apps.accounts.views.sync_member_links", return_value=FAKE_SYNC):
        resp = auth_client.post(_members_url(team), {}, format="json")

    assert resp.status_code == 200
    assert resp.data["unmatched"][0]["email"] == "bob@x.io"


def test_an_override_maps_a_member_clickup_did_not_match(auth_client, team, db):
    dev = User.objects.create_user(email="bob@x.io", password="SecurePass1!")
    TeamMembership.objects.create(user=dev, team=team, role=TeamMembership.Role.DEVELOPER)
    team.clickup_api_token = "pk_test"
    team.save()

    with patch("apps.accounts.views.sync_member_links", return_value=FAKE_SYNC):
        resp = auth_client.post(
            _members_url(team),
            {"overrides": [{"user_id": str(dev.id), "clickup_user_id": "424242"}]},
            format="json",
        )

    assert resp.status_code == 200
    assert ClickUpMemberLink.objects.get(team=team, user=dev).clickup_user_id == "424242"


def test_an_override_for_a_non_member_is_ignored(auth_client, team, db):
    """An override must not create a mapping for someone outside the team."""
    outsider = User.objects.create_user(email="outsider@x.io", password="SecurePass1!")
    team.clickup_api_token = "pk_test"
    team.save()

    with patch("apps.accounts.views.sync_member_links", return_value=FAKE_SYNC):
        auth_client.post(
            _members_url(team),
            {"overrides": [{"user_id": str(outsider.id), "clickup_user_id": "1"}]},
            format="json",
        )

    assert ClickUpMemberLink.objects.filter(team=team, user=outsider).count() == 0
