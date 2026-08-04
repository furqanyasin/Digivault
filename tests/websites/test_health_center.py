"""Phase 2.1 — Health Center aggregate endpoint + security score."""

import pytest

from apps.scripts.models import Script, ScriptChange
from apps.site_health.models import VulnerabilityReport
from apps.websites.health import _security_score, build_health_snapshot
from apps.websites.models import Website


@pytest.fixture
def hc_website(team):
    return Website.objects.create(team=team, name="HC", domain="hc.io")


def test_security_score_deducts_for_vulns_and_ssl():
    assert _security_score({}, 0, None) == 100
    assert _security_score({"critical": 1}, 0, None) == 75
    assert _security_score({"high": 2}, 0, None) == 80
    # SSL tiers match the overall health score: <=7d -20, <=14d -12, <=30d -5.
    assert _security_score({}, 0, 5) == 80
    assert _security_score({}, 0, 12) == 88
    assert _security_score({}, 0, 25) == 95
    assert _security_score({}, 0, 90) == 100
    # floors at 0 (50 + 30 + 15 + 10 + 20 = 125 deductions)
    assert _security_score({"critical": 10, "high": 10, "medium": 10}, 50, 1) == 0


@pytest.mark.django_db
def test_snapshot_aggregates(hc_website):
    s = Script.objects.create(
        website=hc_website, src_url="https://x.com/a.js", src_domain="x.com",
        is_active=True,
    )
    ScriptChange.objects.create(
        website=hc_website, script=s, change_type="added", severity="high",
        description="x",
    )
    VulnerabilityReport.objects.create(
        website=hc_website, component_type="plugin", component_name="foo",
        severity="critical", title="bad",
    )
    snap = build_health_snapshot(hc_website)
    assert snap["domain"] == "hc.io"
    assert snap["scripts"]["active_count"] == 1
    assert snap["scripts"]["high_risk_pending"] == 1
    assert snap["security"]["vulnerabilities_by_severity"]["critical"] == 1
    assert snap["security"]["score"] == 75


@pytest.mark.django_db
def test_health_endpoint(auth_client, hc_website):
    resp = auth_client.get(f"/api/v1/websites/{hc_website.id}/health/")
    assert resp.status_code == 200
    assert resp.data["domain"] == "hc.io"
    assert "security" in resp.data
    assert "scripts" in resp.data
