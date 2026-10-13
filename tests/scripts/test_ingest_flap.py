"""A partial capture must never read as a script removal.

The snippet posts several times per page load — at DOMContentLoaded, again at
2.5s, and again after each DOM mutation burst for 30s. The first post of a load
happens before GTM has injected GA4, Meta Pixel, Clarity, Hotjar and HubSpot, so
it is a *partial* inventory of the page, not a smaller one.

Diffing each post against only the one before it made a partial capture
indistinguishable from an uninstall: every page load reported the whole
marketing stack as removed ("Critical script removed: Google Analytics 4") and
then added again, forever, on every page of every site.
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
    owner = User.objects.create_user(email="flap_o@test.com", password="Pass123!")
    team = TeamService.create(name="Flap Agency", owner=owner)
    return Website.objects.create(team=team, name="Flap Site", domain="flap.io")


def _script(src):
    return {
        "src": src, "location": "head", "is_async": True,
        "is_defer": False, "is_inline": False, "inline_hash": "",
        "wp_plugin": "", "wp_post_id": None,
    }


PAGE = "https://flap.io/"

# Present in the served HTML — captured by every post, including the first.
GTM = "https://www.googletagmanager.com/gtm.js?id=GTM-FLAP01"
# Injected by GTM after DOMContentLoaded — missing from the first post.
GA4 = "https://www.googletagmanager.com/gtag/js?id=G-FLAP01&cx=c&gtm=4e6841"
PIXEL = "https://connect.facebook.net/en_US/fbevents.js"
CLARITY = "https://www.clarity.ms/tag/flapclarity"

EARLY = [_script(GTM)]
SETTLED = [_script(s) for s in (GTM, GA4, PIXEL, CLARITY)]


def _ingest(website, scripts, page_url=PAGE):
    process_ingest_payload(
        str(website.site_id),
        {"page_url": page_url, "scripts": scripts, "forms": []},
    )


def _page_load(website, scripts=SETTLED, page_url=PAGE):
    """One page load: the early partial post, then the settled one.

    Both posts stay inside one observation bucket, which is the whole subject
    of this file — the partial capture and the settled capture belong to the
    *same* load. Only the snapshots already stored are aged, so each call to
    this helper is a separate visit while its two posts are not.
    See tasks._LOAD_BUCKET.
    """
    ScriptSnapshot.objects.filter(website=website).update(
        captured_at=F("captured_at") - timedelta(minutes=5)
    )
    Script.objects.filter(website=website).update(
        last_seen_at=F("last_seen_at") - timedelta(minutes=5)
    )
    _ingest(website, EARLY, page_url)
    _ingest(website, scripts, page_url)


def _changes(website, change_type):
    return ScriptChange.objects.filter(website=website, change_type=change_type)


class TestPartialCaptureIsNotARemoval:
    def test_repeated_page_loads_report_no_removals(self, website):
        for _ in range(6):
            _page_load(website)

        assert list(_changes(website, "removed").values_list("description", flat=True)) == []

    def test_each_script_is_reported_added_once(self, website):
        for _ in range(6):
            _page_load(website)

        added = sorted(_changes(website, "added").values_list("description", flat=True))
        # Descriptions carry the tag id where the URL has one. A site can run
        # four GA4 properties at once, and "Google Analytics 4" logged four
        # times is indistinguishable from one event repeating. Meta Pixel and
        # Clarity have none here: their ids would come from the path, and
        # `fbevents` and `flapclarity` carry no digits, so they are correctly
        # read as filenames rather than account ids.
        # Meta Pixel and Clarity load on this page too, and are not reported:
        # they are not among the monitored vendors (apps/scripts/monitored.py).
        assert added == [
            "New script added: Google Analytics 4 (G-FLAP01)",
            "New script added: Google Tag Manager (GTM-FLAP01)",
        ]

    def test_early_post_does_not_deactivate_the_stack(self, website):
        for _ in range(3):
            _page_load(website)
        # A visitor who bounces before GTM finishes leaves only an early post.
        _ingest(website, EARLY)

        inactive = Script.objects.filter(website=website, is_active=False)
        assert list(inactive.values_list("provider", flat=True)) == []


class TestGenuineRemovalStillReported:
    def test_uninstalled_tag_is_reported_once_traffic_confirms_it(self, website):
        for _ in range(6):
            _page_load(website)
        without_ga4 = [_script(s) for s in (GTM, PIXEL, CLARITY)]

        for _ in range(6):
            _page_load(website, scripts=without_ga4)

        removed = list(_changes(website, "removed").values_list("description", flat=True))
        assert removed == ["Critical script removed: Google Analytics 4 (G-FLAP01)"]


class TestRealWorldStack:
    """The digilatics.com stack that produced 31 repeating change-log rows.

    Every volatile part rotates the way it does in production: HubSpot's epoch
    path segment, Clarity's release directory, Hotjar's bundle hash, GTM's
    container version and Meta's experiment list.
    """

    # Enqueued into the HTML — present in the first post of every page load.
    SERVER_RENDERED = (
        "https://www.googletagmanager.com/gtm.js?id=GTM-N32TK6DJ",
        "https://www.googletagmanager.com/gtm.js?id=GTM-NDF77KHJ",
        "https://js.hs-scripts.com/46377927.js",
        "https://s.ksrndkehqnwntyxlhgto.com/130730.js",
    )

    @staticmethod
    def _injected(load: int) -> tuple[str, ...]:
        """The tags GTM injects, as they look on the Nth page load."""
        epoch = 1785958800000 + load * 2_100_000  # HubSpot rotates every ~35min
        return (
            f"https://www.googletagmanager.com/gtag/js?id=G-LC6FS8Y01E&cx=c&gtm=4e684{load}",
            "https://connect.facebook.net/en_US/fbevents.js",
            "https://connect.facebook.net/signals/config/7847387958713764"
            f"?v=2.9.37{load}&r=stable&domain=digilatics.com"
            "&hme=589ca7d2e122c6385be4e33d0bc38dace8e88b62db3f4bee0e6f01d386858e70"
            f"&ex_m=108%2C210%2C{load}",
            "https://www.clarity.ms/tag/i9x3wxzn9k",
            f"https://scripts.clarity.ms/0.8.6{load}/clarity.js",
            "https://static.hotjar.com/c/hotjar-3065386.js?sv=6",
            f"https://script.hotjar.com/modules.75bf3488a101739acfe{load}.js",
            f"https://js.hs-analytics.net/analytics/{epoch}/46377927.js",
            "https://js.hs-banner.com/v2/46377927/banner.js",
            "https://js.hsadspixel.net/pixels.js",
        )

    def _traffic(self, website, loads=8):
        for load in range(loads):
            page = f"https://digilatics.com/page-{load % 3}"
            # Each iteration is a separate visit; its two posts are one load.
            ScriptSnapshot.objects.filter(website=website).update(
                captured_at=F("captured_at") - timedelta(minutes=5)
            )
            _ingest(website, [_script(s) for s in self.SERVER_RENDERED], page)
            _ingest(
                website,
                [_script(s) for s in self.SERVER_RENDERED + self._injected(load)],
                page,
            )

    def test_rotating_urls_never_report_a_removal(self, website):
        self._traffic(website)

        assert list(_changes(website, "removed").values_list("description", flat=True)) == []
        assert list(_changes(website, "url_changed").values_list("description", flat=True)) == []

    def test_each_tag_is_reported_once_across_all_traffic(self, website):
        self._traffic(website)
        added = _changes(website, "added")

        # One row per installed tag, never a second for the same one. This is
        # the digilatics.com header as installed: two GTM containers, the GA4
        # property one of them injects, Hotjar, HubSpot and WhatConverts. Meta
        # Pixel and Clarity load here too and are not monitored vendors; the
        # files HubSpot's and Hotjar's loaders fetch (analytics, cookie banner,
        # ads pixel, recorder modules) are the tag they belong to, not new ones.
        script_ids = list(added.values_list("script_id", flat=True))
        assert len(script_ids) == len(set(script_ids))
        assert sorted(added.values_list("description", flat=True)) == [
            "New script added: Google Analytics 4 (G-LC6FS8Y01E)",
            "New script added: Google Tag Manager (GTM-N32TK6DJ)",
            "New script added: Google Tag Manager (GTM-NDF77KHJ)",
            "New script added: Hotjar (hotjar-3065386)",
            "New script added: HubSpot Live Chat (46377927)",
            "New script added: WhatConverts (130730)",
        ]

    def test_no_tag_is_reported_as_an_unknown_script(self, website):
        self._traffic(website)

        unknown = _changes(website, "added").filter(description__startswith="Unknown")
        assert list(unknown.values_list("description", flat=True)) == []


class TestAcknowledgingEndsTheAlert:
    def test_acknowledged_change_is_not_recreated_by_later_traffic(self, website):
        for _ in range(6):
            _page_load(website)
        ScriptChange.objects.filter(website=website).update(
            acknowledged_at="2026-08-06T00:00:00Z"
        )

        for _ in range(6):
            _page_load(website)

        assert _changes(website, "added").filter(acknowledged_at__isnull=True).count() == 0
        assert _changes(website, "removed").count() == 0
