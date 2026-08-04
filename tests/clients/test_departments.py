"""Department values: the new Lead Insight / Social Media options, and the CSV
import accepting human labels rather than only the stored codes."""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.clients.models import Client
from apps.clients.views import _parse_departments


def _csv_upload(text: str) -> SimpleUploadedFile:
    return SimpleUploadedFile("clients.csv", text.encode("utf-8"), content_type="text/csv")


class TestDepartmentChoices:
    def test_new_departments_are_available(self):
        assert "lead_insight" in Client.DEPARTMENTS
        assert "social_media" in Client.DEPARTMENTS

    def test_existing_departments_are_kept(self):
        for value in ("seo", "ads", "dev", "content"):
            assert value in Client.DEPARTMENTS


@pytest.mark.django_db
class TestDepartmentApi:
    def test_can_save_the_new_departments(self, auth_client, team):
        c = Client.objects.create(team=team, name="Dept Co")
        resp = auth_client.patch(
            f"/api/v1/clients/{c.id}/",
            {"name": "Dept Co", "departments": ["lead_insight", "social_media"]},
            format="json",
        )
        assert resp.status_code == 200, resp.data
        c.refresh_from_db()
        assert c.departments == ["lead_insight", "social_media"]

    def test_unknown_department_is_rejected(self, auth_client, team):
        """The serializer validates against DEPARTMENTS, so typos don't persist."""
        c = Client.objects.create(team=team, name="Dept Co 2")
        resp = auth_client.patch(
            f"/api/v1/clients/{c.id}/",
            {"name": "Dept Co 2", "departments": ["not_a_department"]},
            format="json",
        )
        assert resp.status_code == 400

    def test_departments_are_returned_on_the_list(self, auth_client, team):
        Client.objects.create(
            team=team, name="Listed Co", departments=["seo", "social_media"]
        )
        resp = auth_client.get("/api/v1/clients/")
        rows = resp.data["results"] if isinstance(resp.data, dict) else resp.data
        row = next(r for r in rows if r["name"] == "Listed Co")
        assert row["departments"] == ["seo", "social_media"]


class TestParseDepartments:
    """A sheet maintained by hand carries labels like "Lead Insight", not codes.

    The old parser matched stored codes only, so those cells were dropped in
    silence — the row imported and simply lost its departments.
    """

    def test_stored_codes_still_work(self):
        assert _parse_departments("seo,ads") == ["seo", "ads"]

    def test_human_labels_are_accepted(self):
        assert _parse_departments("Lead Insight, Social Media") == [
            "lead_insight",
            "social_media",
        ]

    def test_label_casing_and_spacing_are_forgiving(self):
        assert _parse_departments("  LEAD insight ,SOCIAL   MEDIA ") == [
            "lead_insight",
            "social_media",
        ]

    def test_development_label_maps_to_dev(self):
        assert _parse_departments("Development") == ["dev"]

    def test_unknown_values_are_dropped(self):
        assert _parse_departments("seo, Accounting") == ["seo"]

    def test_blank_is_empty(self):
        assert _parse_departments("") == []
        assert _parse_departments(None) == []

    def test_duplicates_collapse(self):
        assert _parse_departments("seo, SEO, Seo") == ["seo"]

    def test_semicolons_and_slashes_separate_too(self):
        assert _parse_departments("seo; social media / ads") == [
            "seo",
            "social_media",
            "ads",
        ]


@pytest.mark.django_db
class TestDepartmentCsvRoundTrip:
    def test_import_accepts_labels_from_a_hand_written_sheet(self, auth_client):
        csv_text = (
            "Task Name,Websites URL (short text),Departments\n"
            "Label Co,https://label.io,\"Lead Insight, Social Media\"\n"
        )
        resp = auth_client.post(
            "/api/v1/clients/import/", {"file": _csv_upload(csv_text)}, format="multipart"
        )
        assert resp.status_code == 200, resp.data
        client = Client.objects.get(name="Label Co")
        assert client.departments == ["lead_insight", "social_media"]

    def test_export_then_import_preserves_new_departments(self, auth_client, team):
        Client.objects.create(
            team=team,
            name="Round Trip Co",
            website_url="https://rt.io",
            departments=["lead_insight", "social_media"],
        )
        export = auth_client.get("/api/v1/clients/export/")
        assert export.status_code == 200
        body = export.content.decode("utf-8")

        Client.objects.filter(name="Round Trip Co").delete()
        resp = auth_client.post(
            "/api/v1/clients/import/", {"file": _csv_upload(body)}, format="multipart"
        )
        assert resp.status_code == 200, resp.data
        client = Client.objects.get(name="Round Trip Co")
        assert client.departments == ["lead_insight", "social_media"]
