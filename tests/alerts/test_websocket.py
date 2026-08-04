
import pytest
from channels.testing import WebsocketCommunicator

from apps.accounts.models import User
from apps.accounts.services import TeamService
from config.asgi import application


@pytest.fixture
def owner(db):
    return User.objects.create_user(email="ws_owner@test.com", password="Pass123!")


@pytest.fixture
def team(owner):
    return TeamService.create(name="WS Agency", owner=owner)


def _get_token(user, password="Pass123!"):
    """Return a valid JWT access token string for the user."""
    from rest_framework_simplejwt.tokens import AccessToken

    return str(AccessToken.for_user(user))


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestAlertConsumer:
    async def test_valid_token_connects(self, owner, team):
        token = _get_token(owner)
        communicator = WebsocketCommunicator(
            application, f"/ws/alerts/?token={token}"
        )
        connected, _ = await communicator.connect()
        assert connected

        # Should receive a connection_established message
        msg = await communicator.receive_json_from()
        assert msg["type"] == "connection_established"

        await communicator.disconnect()

    async def test_invalid_token_rejected(self):
        communicator = WebsocketCommunicator(
            application, "/ws/alerts/?token=not.a.real.token"
        )
        connected, code = await communicator.connect()
        assert not connected
        assert code == 4001

    async def test_no_token_rejected(self):
        communicator = WebsocketCommunicator(application, "/ws/alerts/")
        connected, code = await communicator.connect()
        assert not connected
        assert code == 4001
