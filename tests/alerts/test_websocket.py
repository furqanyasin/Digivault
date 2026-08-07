
import pytest
from channels.testing import WebsocketCommunicator

from apps.accounts.models import User
from apps.accounts.services import TeamService
from config.asgi import application

# The ASGI app is wrapped in AllowedHostsOriginValidator (CSWSH protection),
# which denies any connection without an Origin header — WebsocketCommunicator
# sends none by default, so every connect would close with 1000 before the
# consumer ever ran. Send an origin the dev/test ALLOWED_HOSTS accepts.
_ORIGIN = [(b"origin", b"http://localhost")]


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


def _connect(path, headers=_ORIGIN):
    return WebsocketCommunicator(application, path, headers=headers)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestAlertConsumer:
    async def test_valid_token_connects(self, owner, team):
        token = _get_token(owner)
        communicator = _connect(f"/ws/alerts/?token={token}")
        connected, _ = await communicator.connect()
        assert connected

        # Should receive a connection_established message
        msg = await communicator.receive_json_from()
        assert msg["type"] == "connection_established"

        await communicator.disconnect()

    async def test_invalid_token_rejected(self):
        communicator = _connect("/ws/alerts/?token=not.a.real.token")
        connected, code = await communicator.connect()
        assert not connected
        assert code == 4001

    async def test_no_token_rejected(self):
        communicator = _connect("/ws/alerts/")
        connected, code = await communicator.connect()
        assert not connected
        assert code == 4001

    async def test_foreign_origin_rejected(self, owner, team):
        """A page on another domain must not be able to open the socket."""
        token = _get_token(owner)
        communicator = _connect(
            f"/ws/alerts/?token={token}",
            headers=[(b"origin", b"https://evil.example.com")],
        )
        connected, _ = await communicator.connect()
        assert not connected

    async def test_missing_origin_rejected(self, owner, team):
        """No Origin header at all is denied too — not treated as same-origin."""
        token = _get_token(owner)
        communicator = _connect(f"/ws/alerts/?token={token}", headers=[])
        connected, _ = await communicator.connect()
        assert not connected
