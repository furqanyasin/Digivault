"""CSV import — header mapping, including the renamed 'Domain Access' column."""

import datetime

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.clients.models import Client


def _csv_upload(text: str) -> SimpleUploadedFile:
    return SimpleUploadedFile("clients.csv", text.encode("utf-8"), content_type="text/csv")


@pytest.mark.django_db
def test_patch_client_with_blank_renewal_date(auth_client, team):
    """An empty hosting_renewal_date ("") must clear the field, not 400."""
    c = Client.objects.create(team=team, name="Blank Date Co", website_url="https://bd.io")
    resp = auth_client.patch(
        f"/api/v1/clients/{c.id}/",
        {"name": "Blank Date Co", "hosting_renewal_date": ""},
        format="json",
    )
    assert resp.status_code == 200, resp.data
    c.refresh_from_db()
    assert c.hosting_renewal_date is None


@pytest.mark.django_db
def test_import_reads_new_domain_access_header(auth_client):
    csv_text = (
        "Task ID,Task Name,Websites URL (short text),Domain Access\n"
        "abc123,Acme Co,https://acme.io,Khurram GoDaddy Account\n"
    )
    resp = auth_client.post(
        "/api/v1/clients/import/",
        {"file": _csv_upload(csv_text)},
        format="multipart",
    )
    assert resp.status_code == 200
    assert resp.data["created"] == 1
    client = Client.objects.get(name="Acme Co")
    assert client.domain_access_location == "Khurram GoDaddy Account"


@pytest.mark.django_db
def test_import_reads_renewal_date_and_notes(auth_client):
    csv_text = (
        "Task Name,Hosting Platform (drop down),Hosting Renewal Date,Notes\n"
        "Acme Co,SiteGround,2027-03-15,Internal note here\n"
    )
    resp = auth_client.post(
        "/api/v1/clients/import/",
        {"file": _csv_upload(csv_text)},
        format="multipart",
    )
    assert resp.status_code == 200
    client = Client.objects.get(name="Acme Co")
    assert client.hosting_platform == "siteground"
    assert str(client.hosting_renewal_date) == "2027-03-15"
    assert client.notes == "Internal note here"


@pytest.mark.django_db
def test_export_round_trips_through_import(auth_client, team):
    Client.objects.create(
        team=team, name="Roundtrip Co", website_url="https://rt.io",
        status="paused", tier="gold",
        hosting_platform="wpengine",
        domain_access_location="Acct X", website_built_by_digi="Yes",
        website_maintained_by_digi="No", notes="N1",
        website_access_level="delegate", departments=["seo", "dev"],
        hosting_renewal_date=datetime.date(2027, 3, 15),
        domain_renewal_date=datetime.date(2027, 6, 30),
        notify_desktop=True, notify_email=False,
    )
    export = auth_client.get("/api/v1/clients/export/")
    assert export.status_code == 200
    assert export["Content-Type"].startswith("text/csv")
    body = export.content.decode("utf-8")
    assert "Roundtrip Co" in body
    assert "WPEngine" in body  # code rendered as readable label

    # Feeding the export straight back in must preserve the coded values.
    Client.objects.filter(name="Roundtrip Co").delete()
    resp = auth_client.post(
        "/api/v1/clients/import/",
        {"file": _csv_upload(body)},
        format="multipart",
    )
    assert resp.status_code == 200
    c = Client.objects.get(name="Roundtrip Co")
    assert c.hosting_platform == "wpengine"
    assert c.status == "paused"
    assert c.tier == "gold"
    assert c.website_access_level == "delegate"
    assert c.departments == ["seo", "dev"]
    assert c.hosting_renewal_date == datetime.date(2027, 3, 15)
    assert c.domain_renewal_date == datetime.date(2027, 6, 30)
    # Notification toggles survive the export→import round-trip.
    assert c.notify_desktop is True
    assert c.notify_email is False


@pytest.mark.django_db
def test_import_still_reads_legacy_domain_access_header(auth_client):
    csv_text = (
        "Task ID,Task Name,Websites URL (short text),"
        "Where we have the domain access (drop down)\n"
        "def456,Beta Co,https://beta.io,Client SiteGround Account\n"
    )
    resp = auth_client.post(
        "/api/v1/clients/import/",
        {"file": _csv_upload(csv_text)},
        format="multipart",
    )
    assert resp.status_code == 200
    assert resp.data["created"] == 1
    client = Client.objects.get(name="Beta Co")
    assert client.domain_access_location == "Client SiteGround Account"


@pytest.mark.django_db
def test_reimport_creates_websites_for_existing_clients(auth_client, team):
    """Re-importing a sheet must still provision websites.

    Every client is an *update* on the second pass, and auto-create used to run
    only on the create branch — so a re-import left clients with no website.
    """
    from apps.websites.models import Website

    csv_text = (
        "Client Name,Websites URL (short text)\n"
        "Acme Co,https://acme.io\n"
    )
    # First pass creates the client, but pretend it predates auto-create by
    # removing the website it provisioned.
    resp = auth_client.post(
        "/api/v1/clients/import/", {"file": _csv_upload(csv_text)}, format="multipart"
    )
    assert resp.status_code == 200
    assert resp.data["created"] == 1
    Website.objects.all().delete()

    # Second pass: the client already exists, so this is an update.
    resp = auth_client.post(
        "/api/v1/clients/import/", {"file": _csv_upload(csv_text)}, format="multipart"
    )
    assert resp.status_code == 200
    assert resp.data["updated"] == 1

    website = Website.objects.get(team=team, domain="acme.io")
    assert website.client.name == "Acme Co"


@pytest.mark.django_db
def test_import_maps_real_sheet_wording(auth_client):
    """Wording from the live client sheet must not be silently dropped."""
    csv_text = (
        "Client Name,Hosting Platform (drop down),Website Access Level\n"
        "Admin Co,Wp Engine,admin\n"
        "Unmanaged Co,Not Manage by us,Not Have\n"
        "Broken Co,SiteGround,Not Working\n"
        "Limited Co,SiteGround,Limited\n"
    )
    resp = auth_client.post(
        "/api/v1/clients/import/", {"file": _csv_upload(csv_text)}, format="multipart"
    )
    assert resp.status_code == 200, resp.data

    assert Client.objects.get(name="Admin Co").website_access_level == "full_admin"
    assert Client.objects.get(name="Limited Co").website_access_level == "delegate"
    assert Client.objects.get(name="Broken Co").website_access_level == "not_working"

    unmanaged = Client.objects.get(name="Unmanaged Co")
    assert unmanaged.website_access_level == "none"
    # Unrecognised platform wording is preserved rather than discarded.
    assert unmanaged.hosting_platform == "other"
    assert unmanaged.hosting_platform_other == "Not Manage by us"
