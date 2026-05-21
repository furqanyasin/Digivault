import pytest
from unittest.mock import patch, MagicMock

from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.monitors.models import NotificationChannel


@pytest.fixture
def owner(db):
    return User.objects.create_user(email="chtest@test.com", password="Pass123!")


@pytest.fixture
def team(owner):
    return TeamService.create(name="Test Agency", owner=owner)


@pytest.fixture
def auth_client(owner, team):
    client = APIClient()
    resp = client.post(
        "/api/v1/auth/token/",
        {"email": owner.email, "password": "Pass123!"},
        format="json",
    )
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")
    return client


@pytest.fixture
def email_channel(team):
    return NotificationChannel.objects.create(
        team=team,
        name="Test Email",
        channel_type="email",
        config={"addresses": ["alert@test.com"]},
    )


@pytest.fixture
def clickup_channel(team):
    return NotificationChannel.objects.create(
        team=team,
        name="Test ClickUp",
        channel_type="clickup",
        config={"api_token": "pk_test", "task_id": "abc123"},
    )


@pytest.mark.django_db
class TestChannelTest:
    @patch("apps.monitors.views.send_mail")
    def test_email_channel_test_sends_mail(self, mock_send, auth_client, email_channel):
        resp = auth_client.post(f"/api/v1/notification-channels/{email_channel.pk}/test/")
        assert resp.status_code == 200
        data = resp.data.get("data", resp.data)
        assert data["success"] is True
        mock_send.assert_called_once()
        call_args = mock_send.call_args
        assert "alert@test.com" in call_args[1]["recipient_list"]

    @patch("apps.monitors.views.send_mail", side_effect=Exception("SMTP error"))
    def test_email_channel_test_returns_success_false_on_failure(self, mock_send, auth_client, email_channel):
        resp = auth_client.post(f"/api/v1/notification-channels/{email_channel.pk}/test/")
        assert resp.status_code == 200
        data = resp.data.get("data", resp.data)
        assert data["success"] is False
        assert "SMTP error" in data["message"]

    @patch("apps.monitors.views.urllib.request.urlopen")
    def test_clickup_channel_test_calls_api(self, mock_urlopen, auth_client, clickup_channel):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp
        resp = auth_client.post(f"/api/v1/notification-channels/{clickup_channel.pk}/test/")
        assert resp.status_code == 200
        data = resp.data.get("data", resp.data)
        assert data["success"] is True
        mock_urlopen.assert_called_once()

    def test_channel_test_requires_auth(self, api_client, email_channel):
        resp = api_client.post(f"/api/v1/notification-channels/{email_channel.pk}/test/")
        assert resp.status_code == 401

    def test_channel_test_team_scoped(self, owner, team, auth_client):
        other_owner = User.objects.create_user(email="other_chtest@test.com", password="Pass123!")
        other_team = TeamService.create(name="Other Test Agency", owner=other_owner)
        other_ch = NotificationChannel.objects.create(
            team=other_team, name="OtherChannel", channel_type="email",
            config={"addresses": ["x@x.com"]},
        )
        resp = auth_client.post(f"/api/v1/notification-channels/{other_ch.pk}/test/")
        assert resp.status_code == 404
