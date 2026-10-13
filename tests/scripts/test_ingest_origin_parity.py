"""Every public ingest endpoint binds its domain the same way.

The check was inlined four times, each copy stripping `www.` before the scheme,
so a site saved as `https://www.example.com` reduced to `www.example.com`, never
matched a browser's `example.com`, and was answered 403 on every script, form,
submission and error it sent. Collapsing them into `origin_matches` fixed those
four — and the heatmap ingest, written afterwards, grew a fifth copy with the
same bug.

So this pins the behaviour at the endpoints rather than only at the helper: a
sixth endpoint that reimplements the logic fails here, which is the only place
that would have caught the fifth.
"""

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.scripts.ingest_origin import origin_matches
from apps.websites.models import Website


@pytest.fixture
def owner(db):
    return User.objects.create_user(email="origin_o@test.com", password="Pass123!")


@pytest.fixture
def team(owner):
    return TeamService.create(name="Origin Agency", owner=owner)


@pytest.fixture
def client():
    return APIClient()


#: The shapes a user actually types into the domain field. Every one of these
#: is the same site, and a browser on it sends `https://example.com` or
#: `https://www.example.com` as its Origin.
DOMAIN_SHAPES = [
    "example.com",
    "www.example.com",
    "https://example.com",
    "https://www.example.com",
    "https://www.example.com/",
]


@pytest.mark.django_db
@pytest.mark.parametrize("stored_domain", DOMAIN_SHAPES)
@pytest.mark.parametrize("origin", ["https://example.com", "https://www.example.com"])
def test_helper_accepts_every_shape_of_the_same_site(team, stored_domain, origin, rf):
    website = Website.objects.create(
        team=team, name="Shape Site", domain=stored_domain
    )
    request = rf.post("/api/ingest/", HTTP_ORIGIN=origin)
    assert origin_matches(request, website) is True


@pytest.mark.django_db
def test_helper_rejects_a_different_site(team, rf):
    website = Website.objects.create(team=team, name="A", domain="https://www.example.com")
    request = rf.post("/api/ingest/", HTTP_ORIGIN="https://evil.example.net")
    assert origin_matches(request, website) is False


def _endpoint_calls(site_id):
    """One minimal valid body per public ingest endpoint."""
    return [
        ("/api/ingest/", {
            "site_id": site_id,
            "page_url": "https://www.example.com/",
            "scripts": [],
        }),
        ("/api/ingest/js-errors/", {
            "site_id": site_id,
            "page_url": "https://www.example.com/",
            "message": "TypeError: x is not a function",
        }),
        ("/api/ingest/form-errors/", {
            "site_id": site_id,
            "page_url": "https://www.example.com/",
            "source": "wpcf7",
            "form_id": "wpcf7-f1",
            "message": "There was an error trying to send your message.",
        }),
        ("/api/ingest/form-submission/", {
            "site_id": site_id,
            "page_url": "https://www.example.com/",
            "form": {"form_id": "wpcf7-f1", "form_action": "", "fields": []},
        }),
        ("/api/ingest/heatmap/", {
            "site_id": site_id,
            "page_url": "https://www.example.com/",
            "device": "desktop",
            "final": True,
            "total_clicks": 1,
            "max_scroll_percent": 50,
            "cells": [{"kind": "click", "x": 10, "y": 10, "count": 1}],
        }),
    ]


@pytest.mark.django_db
def test_no_ingest_endpoint_403s_a_www_and_scheme_domain(team, client):
    """The regression: heatmap answered 403 here while the other four did not."""
    website = Website.objects.create(
        team=team,
        name="WWW Site",
        domain="https://www.example.com",
        heatmap_enabled=True,
    )
    for path, body in _endpoint_calls(website.site_id):
        response = client.post(
            path, body, format="json", HTTP_ORIGIN="https://example.com"
        )
        assert response.status_code != 403, f"{path} rejected its own site's origin"


@pytest.mark.django_db
def test_every_ingest_endpoint_rejects_a_foreign_origin(team, client):
    website = Website.objects.create(
        team=team,
        name="WWW Site",
        domain="https://www.example.com",
        heatmap_enabled=True,
    )
    for path, body in _endpoint_calls(website.site_id):
        response = client.post(
            path, body, format="json", HTTP_ORIGIN="https://evil.example.net"
        )
        assert response.status_code == 403, f"{path} accepted a foreign origin"


@pytest.mark.django_db
class TestPageUrlBinding:
    """With no Origin/Referer the origin check fails open; page_url still binds."""

    def _post(self, client, website, page_url):
        return client.post(
            "/api/ingest/",
            {"site_id": str(website.site_id), "page_url": page_url, "scripts": []},
            format="json",
        )

    def test_another_sites_page_is_refused(self, team, client):
        website = Website.objects.create(team=team, name="Bound", domain="https://www.example.com")
        assert self._post(client, website, "https://grupoproeduca.com/").status_code == 403

    @pytest.mark.parametrize("page", ["https://example.com/a", "https://www.example.com/"])
    def test_own_pages_are_accepted(self, team, client, page):
        website = Website.objects.create(team=team, name="Bound", domain="https://www.example.com")
        assert self._post(client, website, page).status_code == 202
