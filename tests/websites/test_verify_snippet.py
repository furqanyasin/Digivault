"""Snippet verification must distinguish "not installed" from "we were blocked".

Both cases in this file are real ones seen in production:

- hudsonvalleyhomeinspections.net answers a server-side fetch with a
  75,193-byte "403 - Forbidden" page from its host's WAF. The old code
  searched that page for the marker and told the user the snippet was
  missing, so they kept re-pasting HTML that was already correct.
- totalhouseinspection.com sits behind Cloudflare bot management, which
  hands the VPS a few-KB challenge body instead of the real 350 KB page.

A site behind a WAF may never be fetchable by us, so ingest traffic — which
only a real browser loading a page that carries the snippet can produce — is
the authoritative signal and is checked first.
"""

from unittest.mock import Mock, patch

import pytest


@pytest.fixture
def website(team):
    from apps.websites.models import Website

    return Website.objects.create(
        team=team, name="Total House Inspection", domain="totalhouseinspection.com"
    )


def _fetch(status_code, text):
    resp = Mock()
    resp.status_code = status_code
    resp.text = text
    return patch("requests.get", return_value=resp)


def _verify(auth_client, website):
    return auth_client.post(f"/api/v1/websites/{website.id}/verify-snippet/")


@pytest.mark.django_db
def test_snippet_present_verifies(auth_client, website):
    html = f'<head><script async src="/s.js" data-site="{website.site_id}"></script></head>'
    with _fetch(200, html):
        resp = _verify(auth_client, website)

    assert resp.status_code == 200, resp.data
    assert resp.data["verified"] is True


@pytest.mark.django_db
def test_snippet_genuinely_absent_says_not_found(auth_client, website):
    """A real 200 page without the marker is the one case that IS "not found"."""
    with _fetch(200, "<html><head><title>Home</title></head><body>" + "x" * 5000 + "</body></html>"):
        resp = _verify(auth_client, website)

    assert resp.data["verified"] is False
    assert resp.data["reason"] == "not_found"
    assert "not found" in resp.data["error"].lower()


@pytest.mark.django_db
def test_403_block_page_is_reported_as_blocked_not_missing(auth_client, website):
    """The hudsonvalleyhomeinspections.net case: HTTP 403 from the host's WAF."""
    block_page = "<html><head><title>403 - Forbidden</title></head><body>" + "x" * 70000 + "</body></html>"
    with _fetch(403, block_page):
        resp = _verify(auth_client, website)

    assert resp.data["verified"] is False
    assert resp.data["reason"] == "blocked"
    assert "403" in resp.data["error"]
    # Must not claim the snippet is missing — that sent users chasing their HTML.
    assert "not found" not in resp.data["error"].lower()


@pytest.mark.django_db
def test_cloudflare_challenge_body_is_reported_as_blocked(auth_client, website):
    """The totalhouseinspection.com case: HTTP 200, but a bot-challenge body."""
    challenge = (
        "<html><head><title>Just a moment...</title></head>"
        "<body>Enable JavaScript and cookies to continue. cf-browser-verification</body></html>"
    )
    with _fetch(200, challenge):
        resp = _verify(auth_client, website)

    assert resp.data["verified"] is False
    assert resp.data["reason"] == "blocked"


@pytest.mark.django_db
def test_implausibly_small_body_is_reported_as_blocked(auth_client, website):
    """An interstitial with no known marker is still not a real page."""
    with _fetch(200, "<html><body>Access denied</body></html>"):
        resp = _verify(auth_client, website)

    assert resp.data["verified"] is False
    assert resp.data["reason"] == "blocked"


@pytest.mark.django_db
def test_recent_ingest_traffic_verifies_even_when_the_fetch_is_blocked(auth_client, website):
    """Ingest can only come from a page carrying the snippet, so it outranks the fetch."""
    from apps.scripts.models import ScriptSnapshot

    ScriptSnapshot.objects.create(
        website=website,
        page_url="https://totalhouseinspection.com/",
        scripts_data=[],
        snippet_version="1.0",
    )

    with _fetch(403, "<title>403 - Forbidden</title>"):
        resp = _verify(auth_client, website)

    assert resp.data["verified"] is True
    assert resp.data["reason"] == "ingest_traffic"


@pytest.mark.django_db
def test_server_scan_snapshots_do_not_count_as_snippet_evidence(auth_client, website):
    """`scan` fetches server-side and writes a snapshot — that proves nothing."""
    from apps.scripts.models import ScriptSnapshot

    ScriptSnapshot.objects.create(
        website=website,
        page_url="https://totalhouseinspection.com/",
        scripts_data=[],
        snippet_version="server-scan",
    )

    with _fetch(403, "<title>403 - Forbidden</title>"):
        resp = _verify(auth_client, website)

    assert resp.data["verified"] is False
    assert resp.data["reason"] == "blocked"
