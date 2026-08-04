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


@pytest.mark.django_db
def test_create_client_syncs_hosting_to_its_new_website(auth_client, team):
    """Regression: perform_create synced BEFORE auto-creating the website, so the
    sync found nothing and the date only landed on a later edit."""
    resp = auth_client.post(
        "/api/v1/clients/",
        {
            "name": "Gamma",
            "website_url": "https://gamma.test",
            "hosting_renewal_date": "2027-03-09",
        },
        format="json",
    )
    assert resp.status_code == 201, resp.data

    web = Website.objects.get(team=team, domain="gamma.test")
    di = DomainInfo.objects.get(website=web)
    assert di.hosting_expires_at is not None, "hosting date never reached the website"
    assert di.hosting_expires_at.date() == datetime.date(2027, 3, 9)


@pytest.mark.django_db
def test_website_exposes_the_clients_hosting_date(auth_client, team):
    """The website page reads the client's date directly, because the mirrored
    copy on DomainInfo only refreshes when the client is saved."""
    client = Client.objects.create(
        team=team, name="Delta", website_url="https://delta.test",
        hosting_renewal_date=datetime.date(2027, 5, 4),
    )
    web = Website.objects.create(
        team=team, name="Delta site", domain="delta.test", client=client
    )
    resp = auth_client.get(f"/api/v1/websites/{web.id}/")
    assert resp.status_code == 200
    assert resp.data["client_hosting_renewal_date"] == "2027-05-04"


@pytest.mark.django_db
def test_website_without_client_has_no_hosting_date(auth_client, team):
    web = Website.objects.create(team=team, name="Orphan", domain="orphan.test")
    resp = auth_client.get(f"/api/v1/websites/{web.id}/")
    assert resp.data["client_hosting_renewal_date"] is None
