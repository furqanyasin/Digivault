"""Client hosting_renewal_date mirrors onto the matching website's DomainInfo."""

import datetime

import pytest

from apps.clients.models import Client
from apps.domains.models import DomainInfo
from apps.websites.models import Website


@pytest.mark.django_db
def test_update_client_syncs_hosting_to_same_domain_website(auth_client, team):
    web = Website.objects.create(team=team, name="Acme", domain="acme.io")
    client = Client.objects.create(team=team, name="Acme", website_url="https://acme.io")

    resp = auth_client.patch(
        f"/api/v1/clients/{client.id}/",
        {"name": "Acme", "hosting_renewal_date": "2027-07-19"},
        format="json",
    )
    assert resp.status_code == 200, resp.data

    di = DomainInfo.objects.get(website=web)
    assert di.hosting_expires_at is not None
    assert di.hosting_expires_at.date() == datetime.date(2027, 7, 19)


@pytest.mark.django_db
def test_sync_matches_via_client_fk(auth_client, team):
    client = Client.objects.create(team=team, name="Beta", website_url="https://beta.io")
    web = Website.objects.create(team=team, name="Beta site", domain="different.io", client=client)

    resp = auth_client.patch(
        f"/api/v1/clients/{client.id}/",
        {"name": "Beta", "hosting_renewal_date": "2027-01-15"},
        format="json",
    )
    assert resp.status_code == 200, resp.data

    di = DomainInfo.objects.get(website=web)
    assert di.hosting_expires_at.date() == datetime.date(2027, 1, 15)
