"""Website create API — team scoping of the client FK."""

import pytest


@pytest.mark.django_db
def test_cannot_attach_website_to_another_teams_client(auth_client, team):
    """The client FK on create must be scoped to the caller's active team."""
    from apps.accounts.models import Team, User
    from apps.clients.models import Client

    outsider = User.objects.create_user(email="outsider@example.com", password="pw12345!")
    other_team = Team.objects.create(name="Other", slug="other-team", owner=outsider)
    foreign_client = Client.objects.create(team=other_team, name="Not Yours")

    resp = auth_client.post(
        "/api/v1/websites/",
        {"name": "Sneaky", "domain": "sneaky.io", "client": str(foreign_client.id)},
        format="json",
    )
    assert resp.status_code == 400, resp.data
    # Errors go through custom_exception_handler, so resp.data IS the envelope
    # here — unlike success responses, which are the raw payload.
    assert "Client not found on this team" in str(resp.data["errors"])


@pytest.mark.django_db
def test_can_attach_website_to_own_teams_client(auth_client, team):
    """The one-click "Add" on /websites posts exactly this payload."""
    from apps.clients.models import Client

    own = Client.objects.create(team=team, name="Mine")

    resp = auth_client.post(
        "/api/v1/websites/",
        {"name": "Mine", "domain": "mine.io", "client": str(own.id)},
        format="json",
    )
    assert resp.status_code == 201, resp.data
    assert str(resp.data["client"]) == str(own.id)
