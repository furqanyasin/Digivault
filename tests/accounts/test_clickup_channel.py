"""Team-level ClickUp chat channel settings.

The channel target is stored as a single URL and parsed on use, so these tests
guard the two things that can silently break notifications: an unparseable URL
being accepted, and a PATCH for one field clearing another.
"""
import pytest


def _settings_url(team):
    return f"/api/v1/auth/teams/{team.id}/settings/"


def test_patching_the_chat_url_stores_it(auth_client, team):
    resp = auth_client.patch(
        _settings_url(team),
        {"clickup_chat_url": "https://digilatics.clickup.com/25658037/chat/r/rf0nn-49438"},
        format="json",
    )

    assert resp.status_code == 200
    team.refresh_from_db()
    assert team.clickup_chat_url == "https://digilatics.clickup.com/25658037/chat/r/rf0nn-49438"
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
