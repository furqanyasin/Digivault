"""CSV import — header mapping, including the renamed 'Domain Access' column."""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.clients.models import Client


def _csv_upload(text: str) -> SimpleUploadedFile:
    return SimpleUploadedFile("clients.csv", text.encode("utf-8"), content_type="text/csv")


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
