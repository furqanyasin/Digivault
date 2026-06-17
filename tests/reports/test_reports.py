"""Phase 2.3 — automated client reports (gather + PDF/CSV + API)."""

import datetime

import pytest

from apps.reports.builder import ReportBuilder
from apps.reports.models import Report
from apps.reports.services import generate_report
from apps.scripts.models import Script, ScriptChange
from apps.websites.models import Website

# Period spans up to today so data created "now" in fixtures falls inside it.
PERIOD_END = datetime.date.today()
PERIOD_START = PERIOD_END - datetime.timedelta(days=30)


@pytest.fixture
def report_website(team):
    site = Website.objects.create(team=team, name="Report Site", domain="report.io")
    script = Script.objects.create(
        website=site, src_url="https://x.com/a.js", src_domain="x.com",
        provider="evil", is_active=True,
    )
    ScriptChange.objects.create(
        website=site, script=script, change_type="added", severity="high",
        description="High-risk add",
    )
    return site


@pytest.mark.django_db
class TestBuilder:
    def test_gather_structure(self, report_website):
        data = ReportBuilder.gather(report_website, PERIOD_START, PERIOD_END)
        assert data["website"]["domain"] == "report.io"
        assert set(data) >= {
            "website", "period", "script_changes", "security", "recommendations",
        }
        assert data["script_changes"]["total"] >= 1
        assert isinstance(data["recommendations"], list) and data["recommendations"]
        # Active scripts are gathered (the fixture has one active, non-internal script).
        assert data["scripts"]["active_total"] >= 1
        assert any(s["domain"] == "x.com" for s in data["scripts"]["active"])

    def test_csv_lists_active_scripts(self, report_website):
        data = ReportBuilder.gather(report_website, PERIOD_START, PERIOD_END)
        csv_text = ReportBuilder.render_csv(data)
        assert "Active scripts (total)" in csv_text
        assert "Active" in csv_text

    def test_render_pdf_returns_pdf_bytes(self, report_website):
        data = ReportBuilder.gather(report_website, PERIOD_START, PERIOD_END)
        pdf = ReportBuilder.render_pdf(data)
        assert isinstance(pdf, bytes)
        assert pdf[:4] == b"%PDF"

    def test_render_csv_has_sections(self, report_website):
        data = ReportBuilder.gather(report_website, PERIOD_START, PERIOD_END)
        csv_text = ReportBuilder.render_csv(data)
        assert "Digivault Report" in csv_text
        assert "Recommendations" in csv_text
        assert "report.io" in csv_text


@pytest.mark.django_db
class TestService:
    def test_generate_pdf_report(self, report_website, settings, tmp_path):
        settings.MEDIA_ROOT = str(tmp_path)
        report = generate_report(report_website, PERIOD_START, PERIOD_END, "pdf")
        assert report.status == Report.Status.DONE
        assert report.file
        assert report.generated_at is not None
        with report.file.open("rb") as fh:
            assert fh.read(4) == b"%PDF"

    def test_generate_csv_report(self, report_website, settings, tmp_path):
        settings.MEDIA_ROOT = str(tmp_path)
        report = generate_report(report_website, PERIOD_START, PERIOD_END, "csv")
        assert report.status == Report.Status.DONE
        assert report.file.name.endswith(".csv")


@pytest.mark.django_db
class TestAPI:
    def test_generate_and_list_and_download(self, auth_client, report_website, settings, tmp_path):
        settings.MEDIA_ROOT = str(tmp_path)
        resp = auth_client.post(
            "/api/v1/reports/generate/",
            {
                "website_id": str(report_website.id),
                "period_start": PERIOD_START.isoformat(),
                "period_end": PERIOD_END.isoformat(),
                "report_format": "pdf",
            },
            format="json",
        )
        assert resp.status_code == 201
        assert resp.data["status"] == "done"
        report_id = resp.data["id"]

        resp = auth_client.get("/api/v1/reports/")
        assert resp.status_code == 200
        assert any(r["id"] == report_id for r in resp.data)

        resp = auth_client.get(f"/api/v1/reports/{report_id}/download/")
        assert resp.status_code == 200
        assert resp["Content-Type"] == "application/pdf"

    def test_delete_report_removes_record_and_file(self, auth_client, report_website, settings, tmp_path):
        settings.MEDIA_ROOT = str(tmp_path)
        report = generate_report(report_website, PERIOD_START, PERIOD_END, "pdf")
        file_path = report.file.path
        import os
        assert os.path.exists(file_path)

        resp = auth_client.delete(f"/api/v1/reports/{report.id}/")
        assert resp.status_code == 204
        assert not Report.objects.filter(pk=report.id).exists()
        assert not os.path.exists(file_path)

    def test_delete_other_teams_report_404(self, auth_client, report_website, settings, tmp_path):
        settings.MEDIA_ROOT = str(tmp_path)
        from apps.accounts.models import User
        from apps.accounts.services import TeamService

        other_owner = User.objects.create_user(email="other@test.com", password="Pass123!")
        other_team = TeamService.create(name="Other Agency", owner=other_owner)
        other_site = Website.objects.create(team=other_team, name="Other", domain="other.io")
        other_report = generate_report(other_site, PERIOD_START, PERIOD_END, "pdf")

        resp = auth_client.delete(f"/api/v1/reports/{other_report.id}/")
        assert resp.status_code == 404
        assert Report.objects.filter(pk=other_report.id).exists()

    def test_generate_unknown_website_404(self, auth_client, settings, tmp_path):
        settings.MEDIA_ROOT = str(tmp_path)
        import uuid

        resp = auth_client.post(
            "/api/v1/reports/generate/",
            {
                "website_id": str(uuid.uuid4()),
                "period_start": PERIOD_START.isoformat(),
                "period_end": PERIOD_END.isoformat(),
            },
            format="json",
        )
        assert resp.status_code == 404
