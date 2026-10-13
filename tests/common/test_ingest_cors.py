"""CORS on the public ingest endpoints.

Regression cover for a production outage: the snippet on a client site POSTed
to /api/ingest/ and Chrome rejected it at the preflight with "No
'Access-Control-Allow-Origin' header is present", because CORS_ALLOWED_ORIGINS
only ever lists Stacks Monitor's own dashboard origin. No scripts, forms or JS
errors reached the backend from that site.
"""

import pytest
from rest_framework.test import APIClient

CLIENT_ORIGIN = "https://a-client-site.example"

PUBLIC_PATHS = [
    "/api/ingest/",
    "/api/ingest/form-errors/",
    "/api/ingest/js-errors/",
    "/api/ingest/form-submission/",
]


@pytest.mark.parametrize("path", PUBLIC_PATHS)
def test_preflight_from_any_origin_is_allowed(path):
    resp = APIClient().options(
        path,
        HTTP_ORIGIN=CLIENT_ORIGIN,
        HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
        HTTP_ACCESS_CONTROL_REQUEST_HEADERS="content-type",
    )
    assert resp.status_code == 204
    assert resp["Access-Control-Allow-Origin"] == "*"
    assert "POST" in resp["Access-Control-Allow-Methods"]
    assert "Content-Type" in resp["Access-Control-Allow-Headers"]


@pytest.mark.django_db
def test_post_response_carries_the_allow_origin_header():
    # An unknown site_id is a 404, but the CORS header must still be present:
    # without it the browser discards the response and the snippet cannot tell
    # a rejected site from a network failure.
    resp = APIClient().post(
        "/api/ingest/",
        {"site_id": "unknown-site", "scripts": []},
        format="json",
        HTTP_ORIGIN=CLIENT_ORIGIN,
    )
    assert resp["Access-Control-Allow-Origin"] == "*"


def test_credentials_are_never_allowed():
    # "*" plus Allow-Credentials is invalid per spec and browsers reject it;
    # these endpoints must stay credential-free.
    resp = APIClient().options(
        "/api/ingest/",
        HTTP_ORIGIN=CLIENT_ORIGIN,
        HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
    )
    assert "Access-Control-Allow-Credentials" not in resp


@pytest.mark.django_db
def test_authenticated_api_is_not_opened_to_every_origin():
    # The blast radius of the fix stops at the ingest paths: the dashboard API
    # keeps the CORS_ALLOWED_ORIGINS allowlist.
    resp = APIClient().get("/api/v1/websites/", HTTP_ORIGIN=CLIENT_ORIGIN)
    assert resp.get("Access-Control-Allow-Origin") != "*"
