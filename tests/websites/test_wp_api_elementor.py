"""Pulling Elementor form recipients out of `_elementor_data`.

The recipient sits in the form widget's settings inside a nested builder tree,
so the walk has to survive arbitrary section/column nesting and pages that carry
no form at all.

Note the fixture is synthetic. Elementor Pro is not publicly distributed, so the
exact settings keys (`email_to` and its Cc/Bcc siblings) are the one part of
this feature not confirmed against source — see `_TO_KEYS` in the reader.
"""

import json
import pathlib

import pytest

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.websites import wp_api_forms
from apps.websites.models import Website

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "elementor_data.json"


@pytest.fixture
def team(db):
    owner = User.objects.create_user(email="elem_o@test.com", password="Pass123!")
    return TeamService.create(name="Elementor Agency", owner=owner)


@pytest.fixture
def website(team):
    return Website.objects.create(team=team, name="Elementor Site", domain="wpapi.test")


def _only_pages(rows):
    """Answer the `pages` request and nothing else, as a site with no posts would."""

    def _fetch(site, path, credential, **kwargs):
        if path.startswith("wp/v2/pages") and "page=1" in path:
            return rows, 200
        return None, 404

    return _fetch


def test_reads_the_form_name_and_recipients_from_elementor_data(website):
    rows = json.loads(FIXTURE.read_text())

    entries = wp_api_forms.read_elementor(
        website, credential=object(), fetch=_only_pages(rows)
    )

    assert entries == [{
        "plugin": "elementor",
        "name": "Contact Form",
        "to": "leads@example.com",
        "cc": "sales@example.com",
        "bcc": "",
    }]


def test_a_page_with_no_form_widget_yields_nothing(website):
    rows = [{
        "id": 4,
        "link": "https://wpapi.test/about",
        "meta": {"_elementor_data": json.dumps([
            {"elType": "section", "elements": [
                {"elType": "widget", "widgetType": "heading", "settings": {"title": "Hi"}}
            ]}
        ])},
    }]

    assert wp_api_forms.read_elementor(
        website, credential=object(), fetch=_only_pages(rows)
    ) == []


def test_a_form_widget_with_no_recipient_is_skipped(website):
    """A form posting to a webhook rather than email has nothing to report."""
    rows = [{
        "id": 5,
        "link": "https://wpapi.test/webhook",
        "meta": {"_elementor_data": json.dumps([
            {"elType": "widget", "widgetType": "form",
             "settings": {"form_name": "Webhook", "email_to": ""}}
        ])},
    }]

    assert wp_api_forms.read_elementor(
        website, credential=object(), fetch=_only_pages(rows)
    ) == []


def test_a_deeply_nested_form_is_still_found(website):
    rows = [{
        "id": 6,
        "link": "https://wpapi.test/deep",
        "meta": {"_elementor_data": json.dumps([
            {"elType": "section", "elements": [
                {"elType": "column", "elements": [
                    {"elType": "section", "elements": [
                        {"elType": "column", "elements": [
                            {"elType": "widget", "widgetType": "form",
                             "settings": {"form_name": "Deep", "email_to": "d@example.com"}}
                        ]}
                    ]}
                ]}
            ]}
        ])},
    }]

    entries = wp_api_forms.read_elementor(
        website, credential=object(), fetch=_only_pages(rows)
    )

    assert [e["to"] for e in entries] == ["d@example.com"]


def test_the_alternate_cc_spelling_is_accepted(website):
    rows = [{
        "id": 7,
        "link": "https://wpapi.test/alt",
        "meta": {"_elementor_data": json.dumps([
            {"elType": "widget", "widgetType": "form",
             "settings": {"form_name": "Alt", "email_to": "a@example.com",
                          "email_to_cc": "c@example.com"}}
        ])},
    }]

    entries = wp_api_forms.read_elementor(
        website, credential=object(), fetch=_only_pages(rows)
    )

    assert entries[0]["cc"] == "c@example.com"


def test_unparseable_elementor_data_is_ignored(website):
    rows = [{"id": 8, "link": "https://wpapi.test/broken",
             "meta": {"_elementor_data": "{not json"}}]

    assert wp_api_forms.read_elementor(
        website, credential=object(), fetch=_only_pages(rows)
    ) == []


def test_a_failed_fetch_yields_nothing(website):
    assert wp_api_forms.read_elementor(
        website, credential=object(), fetch=lambda *a, **kw: (None, 401)
    ) == []


def test_pagination_stops_at_the_cap_and_says_so(website, monkeypatch):
    """A full page every time means more may be waiting; that must not be silent."""
    full_page = [
        {"id": i, "link": f"https://wpapi.test/{i}", "meta": {"_elementor_data": ""}}
        for i in range(wp_api_forms._ELEMENTOR_PER_PAGE)
    ]
    calls = []

    def _always_full(site, path, credential, **kwargs):
        calls.append(path)
        return (full_page, 200) if path.startswith("wp/v2/pages") else (None, 404)

    # The app loggers do not propagate to root, so caplog never sees these.
    logged: list[str] = []
    monkeypatch.setattr(
        wp_api_forms.logger, "info", lambda msg, *args: logged.append(msg % args)
    )

    wp_api_forms.read_elementor(website, credential=object(), fetch=_always_full)

    page_calls = [c for c in calls if c.startswith("wp/v2/pages")]
    assert len(page_calls) == wp_api_forms._ELEMENTOR_MAX_PAGES
    assert any("later pages not read" in line for line in logged)
