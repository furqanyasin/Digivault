"""Deactivating a script needs the same evidence as reporting it removed.

`is_active` is what the Scripts tab renders, so whatever flips it decides what
an agency sees. It used to be flipped by a site-wide sweep driven by a *single
page's* observation:

    Script.objects.filter(website=..., scope=GLOBAL, is_active=True) \
        .exclude(normalized_url__in=current_urls).update(is_active=False)

`current_urls` came from the window for the one page in the payload; the UPDATE
covered the whole website. So one partial capture — the first post of a page
load before GTM injects, a first-ever visit to a page, or a server-side scan
that only ever parses the homepage's static HTML — switched off every site-wide
tag the site has. A site running GTM, GA4, Hotjar, HubSpot and WhatConverts
showed one row: Google.

The scope gate made it hit exactly the tags worth watching. `_update_script_scopes`
marks a script GLOBAL once it is on >=80% of pages, so a site-wide marketing tag
was the only kind the sweep could reach; a one-page script was immune.

Deactivation is now driven by the windowed diff — the same union-of-observations
standard that decides whether a removal is reported at all.
"""

from datetime import timedelta

import pytest
from django.db.models import F

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.scripts.models import Script, ScriptChange, ScriptSnapshot
from apps.scripts.tasks import process_ingest_payload
from apps.websites.models import Website

pytestmark = pytest.mark.django_db


@pytest.fixture
def website(db):
    owner = User.objects.create_user(email="deact_o@test.com", password="Pass123!")
    team = TeamService.create(name="Deact Agency", owner=owner)
    return Website.objects.create(team=team, name="Deact Site", domain="deact.io")


def _script(src):
    return {
        "src": src, "location": "head", "is_async": True,
        "is_defer": False, "is_inline": False, "inline_hash": "",
        "wp_plugin": "", "wp_post_id": None,
    }


# In the served HTML — captured by every post, including the first one and the
# server-side scan that only ever sees static markup.
GTM = "https://www.googletagmanager.com/gtm.js?id=GTM-DEACT"
# Injected by GTM after DOMContentLoaded — absent from a partial capture.
GA4 = "https://www.googletagmanager.com/gtag/js?id=G-DEACT"
HOTJAR = "https://static.hotjar.com/c/hotjar-7654321.js?sv=6"
HUBSPOT = "https://js.hs-scripts.com/7654321.js"
WHATCONVERTS = "https://scripts.whatconverts.com/7654.js"

FULL = [_script(s) for s in (GTM, GA4, HOTJAR, HUBSPOT, WHATCONVERTS)]
EARLY = [_script(GTM)]

HOME = "https://deact.io/"
ABOUT = "https://deact.io/about"
SERVICES = "https://deact.io/services"
CONTACT = "https://deact.io/contact"


def _age_existing_snapshots(website, gap=timedelta(minutes=5)):
    """Push this site's stored snapshots back so the next post is a new visit.

    The diff windows are counted in buckets of wall-clock time
    (`tasks._LOAD_BUCKET`), because a page load is several posts within a few
    seconds and a run of observations has to mean a run of *visits*. A test
    that posts six times in the same millisecond is therefore describing one
    page load, however many calls it makes. Ageing what is already stored is
    what makes "six loads" and "repeat daily" below mean what they say.
    """
    ScriptSnapshot.objects.filter(website=website).update(
        captured_at=F("captured_at") - gap
    )
    # Time passes for the inventory too: a removal is only confirmed when no
    # page has seen the script since it went missing (Script.last_seen_at).
    Script.objects.filter(website=website).update(
        last_seen_at=F("last_seen_at") - gap
    )


def _ingest(website, scripts, page_url, snippet_version="2.0"):
    """One page load — this file's scripts arrive complete or not at all."""
    _age_existing_snapshots(website)
    process_ingest_payload(
        str(website.site_id),
        {
            "page_url": page_url,
            "scripts": scripts,
            "forms": [],
            "snippet_version": snippet_version,
        },
    )


def _scan(website, scripts, page_url):
    """What passive_scan_website / the scan action post: static HTML only."""
    _ingest(website, scripts, page_url, snippet_version="server-scan")


def _settle(website, scripts=FULL, pages=(HOME, ABOUT, SERVICES)):
    """Enough full loads on enough pages for every script to be scoped GLOBAL."""
    for page in pages:
        for _ in range(6):
            _ingest(website, scripts, page)


def _active(website):
    return sorted(
        Script.objects.filter(website=website, is_active=True)
        .values_list("provider", flat=True)
    )


ALL_FIVE = [
    "Google Analytics 4",
    "Google Tag Manager",
    "Hotjar",
    "HubSpot Live Chat",
    "WhatConverts",
]


class TestPartialCaptureDoesNotDeactivate:
    def test_settled_site_has_every_tag_active_and_global(self, website):
        _settle(website)

        assert _active(website) == ALL_FIVE
        assert set(
            Script.objects.filter(website=website).values_list("scope", flat=True)
        ) == {Script.Scope.GLOBAL}

    def test_first_visit_to_a_new_page_keeps_the_site_stack_active(self, website):
        _settle(website)

        # A visitor lands on a page nobody has loaded before. Its first post
        # carries only the statically embedded GTM tag.
        _ingest(website, EARLY, CONTACT)

        assert _active(website) == ALL_FIVE

    def test_server_side_homepage_scan_keeps_runtime_scripts_active(self, website):
        _settle(website)

        # passive_scan_website / the scan action parse static homepage HTML, so
        # they never see anything GTM injects at runtime. Run daily, they used
        # to fill the homepage window on their own and report the whole
        # runtime-injected stack as removed.
        for _ in range(6):
            _scan(website, EARLY, HOME)

        assert _active(website) == ALL_FIVE

    def test_a_scan_never_reports_a_runtime_tag_removed(self, website):
        _settle(website)
        for _ in range(6):
            _scan(website, EARLY, HOME)

        assert list(
            ScriptChange.objects.filter(
                website=website, change_type=ScriptChange.ChangeType.REMOVED
            ).values_list("description", flat=True)
        ) == []

    def test_a_bounce_on_a_quiet_page_keeps_the_site_stack_active(self, website):
        _settle(website)
        # One visitor, one early post, then they leave. Repeat daily.
        for _ in range(5):
            _ingest(website, EARLY, CONTACT)

        assert _active(website) == ALL_FIVE


class TestGenuineRemovalStillDeactivates:
    def test_uninstalled_tag_goes_inactive_once_traffic_confirms_it(self, website):
        _settle(website)
        without_hotjar = [_script(s) for s in (GTM, GA4, HUBSPOT, WHATCONVERTS)]

        _settle(website, scripts=without_hotjar)

        assert _active(website) == [
            "Google Analytics 4",
            "Google Tag Manager",
            "HubSpot Live Chat",
            "WhatConverts",
        ]
        hotjar = Script.objects.get(website=website, provider="Hotjar")
        assert hotjar.is_active is False

    def test_a_reinstalled_tag_comes_back(self, website):
        _settle(website)
        without_hotjar = [_script(s) for s in (GTM, GA4, HUBSPOT, WHATCONVERTS)]
        _settle(website, scripts=without_hotjar)
        assert "Hotjar" not in _active(website)

        _settle(website)

        assert _active(website) == ALL_FIVE


class TestScanOnlySiteKeepsRemovalDetection:
    """A site with no snippet is monitored by the daily homepage scan alone.
    Scan-against-scan is a like-for-like comparison, so the floor still works."""

    def test_tag_removed_from_static_html_is_deactivated(self, website):
        static_full = [_script(s) for s in (GTM, GA4)]
        for _ in range(6):
            _scan(website, static_full, HOME)
        assert _active(website) == ["Google Analytics 4", "Google Tag Manager"]

        for _ in range(6):
            _scan(website, EARLY, HOME)

        assert _active(website) == ["Google Tag Manager"]


class TestInactiveScriptsReachTheFrontend:
    """The Scripts tab renders an "Inactive" badge for a tag that stopped
    loading. It could never appear: the list endpoint filtered to .active(),
    so an inactive row never left the API."""

    def test_list_endpoint_returns_inactive_scripts(self, auth_client, team):
        site = Website.objects.create(team=team, name="S", domain="inactive.io")
        Script.objects.create(
            website=site,
            src_url="https://static.hotjar.com/c/hotjar-1.js",
            provider="Hotjar",
            category=Script.Category.SESSION_RECORDING,
            is_active=False,
        )

        resp = auth_client.get(f"/api/v1/websites/{site.id}/scripts/")

        assert resp.status_code == 200
        assert [r["provider"] for r in resp.data] == ["Hotjar"]
        assert resp.data[0]["is_active"] is False


class TestRepairMigration:
    """scripts/0029 undoes rows the old site-wide sweep wrongly retired.

    Exercised through the migration's own function rather than a schema replay:
    the historical models it asks for are field-identical to the live ones here,
    and what is worth pinning is the evidence rule — reactivate what the raw
    snapshots say was really on the site, and nothing else."""

    def test_reactivates_only_scripts_the_snapshots_still_show(self, website):
        import importlib

        from django.apps import apps as global_apps

        migration = importlib.import_module(
            "apps.scripts.migrations.0029_reactivate_wrongly_deactivated_scripts"
        )

        _settle(website)
        # A tag genuinely uninstalled long before the snapshots we keep.
        gone = Script.objects.create(
            website=website,
            src_url="https://cdn.callrail.com/companies/999/swap.js",
            normalized_url="https://cdn.callrail.com/companies/999/swap.js",
            provider="CallRail",
            category=Script.Category.CALL_TRACKING,
            is_active=False,
        )
        # What the old sweep did: switch off tags the snapshots still contain.
        Script.objects.filter(website=website).exclude(pk=gone.pk).update(is_active=False)
        assert _active(website) == []

        migration.reactivate(global_apps, None)

        assert _active(website) == ALL_FIVE
        gone.refresh_from_db()
        assert gone.is_active is False
