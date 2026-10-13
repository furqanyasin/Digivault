"""An observation that changed nothing must cost almost nothing.

The snippet posts at DOMContentLoaded, again at 2.5s, and again after each DOM
mutation burst for 30 seconds — six or more posts per pageview, per page, per
visitor, across every client site. All but the first of those normally see
exactly what the one before saw.

Each of them used to run the full derived-state recomputation anyway, inside the
transaction that holds the website's row lock: a scan of every Script row the
site has (re-classified in Python), a walk of every active script plus a
`DISTINCT page_url` count over ScriptSnapshot — the largest table in the product
— and an eight-query health recalculation. That is the platform's hot path, and
it was doing a site-wide sweep several times per visitor to arrive at the values
already stored.

These tests pin the two halves of the fix: the cheap case is cheap, and the
cases that genuinely move derived state still recompute it.
"""

import pytest

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.scripts.models import Script, ScriptSnapshot
from apps.scripts.tasks import process_ingest_payload
from apps.websites.models import Website

pytestmark = pytest.mark.django_db

GTM = "https://www.googletagmanager.com/gtm.js?id=GTM-HOTPATH"
GA4 = "https://www.googletagmanager.com/gtag/js?id=G-HOTPATH1"


@pytest.fixture
def website(db):
    owner = User.objects.create_user(email="hotpath@test.com", password="Pass123!")
    team = TeamService.create(name="Hot Path Agency", owner=owner)
    return Website.objects.create(team=team, name="Hot Site", domain="hotpath.io")


def _script(src):
    return {
        "src": src, "location": "head", "is_async": True,
        "is_defer": False, "is_inline": False, "inline_hash": "",
        "wp_plugin": "", "wp_post_id": None,
    }


def _ingest(website, page_url, srcs):
    process_ingest_payload(
        str(website.site_id),
        {
            "page_url": page_url,
            "scripts": [_script(s) for s in srcs],
            "forms": [],
        },
    )


def test_a_repeat_observation_does_not_recompute_derived_state(website):
    """The same page, the same scripts, a second later. Nothing has changed."""
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    _ingest(website, "https://hotpath.io/", [GTM, GA4])
    # Let the window settle so the diff has nothing to report.
    _ingest(website, "https://hotpath.io/", [GTM, GA4])

    with CaptureQueriesContext(connection) as repeat:
        _ingest(website, "https://hotpath.io/", [GTM, GA4])

    sql = " ".join(q["sql"].lower() for q in repeat)

    # `monitors_monitor` is read on this path by exactly one thing:
    # `Website.recalculate_health_score`. Its absence is the assertion — the
    # health score is eight queries and a Python pass over every open change,
    # and it was running on every post.
    assert "monitors_monitor" not in sql, (
        "a no-op observation is still recalculating the health score"
    )

    # `_update_script_scopes` counts the site's distinct pages across
    # ScriptSnapshot, the largest table in the product.
    assert "select distinct" not in sql, (
        "a no-op observation is still counting the site's distinct pages"
    )


def test_a_new_script_still_recomputes_scope(website):
    _ingest(website, "https://hotpath.io/", [GTM])
    _ingest(website, "https://hotpath.io/about", [GTM])

    gtm = Script.objects.get(website=website, src_url=GTM)
    assert gtm.scope == Script.Scope.GLOBAL

    # A script on one page out of three is page-specific, and the label has to
    # move when the third page appears even though GA4 itself did not change.
    _ingest(website, "https://hotpath.io/pricing", [GTM, GA4])
    _ingest(website, "https://hotpath.io/pricing", [GTM, GA4])

    ga4 = Script.objects.get(website=website, src_url=GA4)
    assert ga4.scope == Script.Scope.ONE_TIME


def test_a_known_script_on_a_new_page_still_recomputes_scope(website):
    """The diff compares one page's window and cannot see this — the upsert can."""
    _ingest(website, "https://hotpath.io/", [GTM])
    gtm = Script.objects.get(website=website, src_url=GTM)
    assert gtm.seen_on_pages == ["https://hotpath.io/"]

    _ingest(website, "https://hotpath.io/contact", [GTM])
    gtm.refresh_from_db()
    assert sorted(gtm.seen_on_pages) == [
        "https://hotpath.io/",
        "https://hotpath.io/contact",
    ]


def test_health_score_is_still_written_when_a_change_is_recorded(website):
    """The gate must not stop the score reacting to something worth reacting to."""
    _ingest(website, "https://hotpath.io/", [GTM])
    website.refresh_from_db()
    before = website.health_score

    # An unknown third-party script is what the product exists to catch.
    _ingest(
        website,
        "https://hotpath.io/",
        [GTM, "https://unknown-tracker.example/collect.js"],
    )
    website.refresh_from_db()
    assert website.health_score <= before


def test_every_post_still_records_its_snapshot(website):
    """The gate covers derived state only. Raw observation is never skipped."""
    for _ in range(4):
        _ingest(website, "https://hotpath.io/", [GTM])
    assert ScriptSnapshot.objects.filter(website=website).count() == 4
