"""Adding a client with a website URL auto-creates a matching Website."""

import pytest

from apps.clients.models import Client
from apps.websites.models import Website


@pytest.mark.django_db
def test_create_client_with_url_auto_creates_website(auth_client, team):
    resp = auth_client.post(
        "/api/v1/clients/",
        {"name": "Acme", "website_url": "https://acme.io"},
        format="json",
    )
    assert resp.status_code == 201, resp.data
    client = Client.objects.get(id=resp.data["id"])

    website = Website.objects.get(team=team, domain="acme.io")
    assert website.client_id == client.id
    assert website.name == "Acme"


@pytest.mark.django_db
def test_create_client_without_url_does_not_create_website(auth_client, team):
    resp = auth_client.post(
        "/api/v1/clients/",
        {"name": "No Site Yet"},
        format="json",
    )
    assert resp.status_code == 201, resp.data
    assert not Website.objects.filter(team=team).exists()


@pytest.mark.django_db
def test_create_client_adopts_existing_unlinked_website(auth_client, team):
    """Re-importing clients must reattach sites orphaned by the previous wipe."""
    existing = Website.objects.create(team=team, name="Acme site", domain="acme.io")

    resp = auth_client.post(
        "/api/v1/clients/",
        {"name": "Acme", "website_url": "https://acme.io"},
        format="json",
    )
    assert resp.status_code == 201, resp.data

    assert Website.objects.filter(team=team, domain__iexact="acme.io").count() == 1
    existing.refresh_from_db()
    assert str(existing.client_id) == resp.data["id"]


@pytest.mark.django_db
def test_create_client_does_not_steal_website_from_another_client(auth_client, team):
    owner = Client.objects.create(team=team, name="Original", website_url="https://acme.io")
    existing = Website.objects.create(team=team, name="Acme site", domain="acme.io", client=owner)

    resp = auth_client.post(
        "/api/v1/clients/",
        {"name": "Impostor", "website_url": "https://acme.io"},
        format="json",
    )
    assert resp.status_code == 201, resp.data

    existing.refresh_from_db()
    assert existing.client_id == owner.id
