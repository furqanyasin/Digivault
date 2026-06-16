import pytest

from apps.site_health import tasks
from apps.site_health.models import SiteScanState
from apps.site_health.tasks import _version_lt, run_security_scan
from apps.websites.models import Website


def test_version_lt():
    assert _version_lt("6.4.1", "6.6.2") is True
    assert _version_lt("6.6.2", "6.6.2") is False
    assert _version_lt("6.7", "6.6.2") is False


@pytest.mark.django_db
def test_security_scan_flags_wp_update(monkeypatch, team):
    w = Website.objects.create(team=team, name="W", domain="wp.example")
    SiteScanState.objects.create(website=w, wp_version="6.4.1")
    monkeypatch.setattr(tasks, "_fetch_latest_wp_version", lambda: "6.6.2")

    run_security_scan(str(w.pk))

    state = SiteScanState.objects.get(website=w)
    assert state.wp_latest_version == "6.6.2"
    assert state.wp_update_available is True


@pytest.mark.django_db
def test_security_scan_up_to_date(monkeypatch, team):
    w = Website.objects.create(team=team, name="W", domain="wp2.example")
    SiteScanState.objects.create(website=w, wp_version="6.6.2")
    monkeypatch.setattr(tasks, "_fetch_latest_wp_version", lambda: "6.6.2")

    run_security_scan(str(w.pk))

    state = SiteScanState.objects.get(website=w)
    assert state.wp_update_available is False
