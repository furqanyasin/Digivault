"""Added and removed are judged against the site's inventory, not one page's window.

The change log used to repeat itself: the same tags "added" week after week
though nobody touched them, and add/remove pairs for one tag on the same day.
Two rules produced that:

* "added" meant "in this page's current window, not in its previous one", so a
  tag the site had carried for a year was announced again whenever one page's
  window lacked it — held back only by the seven-day cooldown;
* "removed" meant "missing from three buckets of one page", which three
  visitors declining the cookie banner satisfy on any quiet page.

See apps/scripts/presence.py and tasks._inventory_changes.
"""

from datetime import timedelta

import pytest
from django.db.models import F
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.scripts import presence
from apps.scripts.models import Script, ScriptChange, ScriptSnapshot
from apps.scripts.tasks import process_ingest_payload, purge_old_snapshots
from apps.websites.models import Website


def _script(src):
    return {
        "src": src, "location": "head", "is_async": True,
        "is_defer": False, "is_inline": False, "inline_hash": "",
        "wp_plugin": "", "wp_post_id": None,
    }


HOME = "https://inv.io/"
ABOUT = "https://inv.io/about"

GTM = "https://www.googletagmanager.com/gtm.js?id=GTM-INV001"
# Consent-gated: loads only for visitors who accept the banner.
HOTJAR = "https://static.hotjar.com/c/hotjar-3065386.js?sv=6"
ADS = "https://www.googletagmanager.com/gtag/js?id=AW-805842842"


@pytest.fixture
def website(db):
    owner = User.objects.create_user(email="inv_o@test.com", password="Pass123!")
    team = TeamService.create(name="Inventory Agency", owner=owner)
    return Website.objects.create(team=team, name="Inventory Site", domain="inv.io")


def _pass_time(website, gap=timedelta(minutes=5)):
    ScriptSnapshot.objects.filter(website=website).update(
        captured_at=F("captured_at") - gap
    )
    Script.objects.filter(website=website).update(last_seen_at=F("last_seen_at") - gap)
    ScriptChange.objects.filter(website=website).update(created_at=F("created_at") - gap)


def _visit(website, srcs, page=HOME):
    """One page load by one visitor."""
    _pass_time(website)
    process_ingest_payload(
        str(website.site_id),
        {"page_url": page, "scripts": [_script(s) for s in srcs], "forms": []},
    )


def _descriptions(website, change_type):
    return sorted(
        ScriptChange.objects.filter(website=website, change_type=change_type)
        .values_list("description", flat=True)
    )


@pytest.mark.django_db
class TestConsentGatedTagsDoNotFlap:
    def test_tag_loading_for_half_the_visitors_is_never_removed(self, website):
        # Accept, decline, decline, decline, accept... — three declines in a
        # row is an ordinary afternoon, and was exactly the old threshold.
        pattern = [True, False, False, False, True, True, False, False, False, True] * 3
        for accepted in pattern:
            _visit(website, [GTM, HOTJAR] if accepted else [GTM])

        assert _descriptions(website, "removed") == []
        assert _descriptions(website, "added") == [
            "New script added: Google Tag Manager (GTM-INV001)",
            "New script added: Hotjar (hotjar-3065386)",
        ]
        assert Script.objects.get(website=website, provider="Hotjar").is_active

    def test_steady_tag_that_disappears_is_still_reported(self, website):
        for _ in range(6):
            _visit(website, [GTM, ADS])
        for _ in range(5):
            _visit(website, [GTM])

        assert _descriptions(website, "removed") == [
            "Critical script removed: Google Ads (AW-805842842)"
        ]
        assert not Script.objects.get(website=website, provider="Google Ads").is_active


@pytest.mark.django_db
class TestAKnownTagIsNeverAddedAgain:
    def test_known_tag_on_a_new_page_after_the_cooldown_is_silent(self, website):
        for _ in range(3):
            _visit(website, [GTM, ADS])
        ScriptChange.objects.filter(website=website).update(acknowledged_at=timezone.now())
        # Well past _CHANGE_COOLDOWN, which is all that stopped the weekly repeat.
        _pass_time(website, timedelta(days=10))

        _visit(website, [GTM, ADS], page=ABOUT)
        _visit(website, [GTM], page=HOME)
        _visit(website, [GTM, ADS], page=HOME)

        assert ScriptChange.objects.filter(
            website=website, acknowledged_at__isnull=True
        ).count() == 0

    def test_seen_on_another_page_since_is_not_a_removal(self, website):
        for _ in range(6):
            _visit(website, [GTM, ADS], page=HOME)
        # HOME stops carrying it, while ABOUT keeps loading it in between.
        for _ in range(6):
            _visit(website, [GTM], page=HOME)
            _visit(website, [GTM, ADS], page=ABOUT)

        assert _descriptions(website, "removed") == []


@pytest.mark.django_db
class TestAFlapHealsItself:
    def _remove_ads(self, website):
        for _ in range(6):
            _visit(website, [GTM, ADS])
        for _ in range(5):
            _visit(website, [GTM])
        assert _descriptions(website, "removed") == [
            "Critical script removed: Google Ads (AW-805842842)"
        ]

    def test_return_while_the_removal_is_open_closes_it_quietly(self, website):
        self._remove_ads(website)

        _visit(website, [GTM, ADS])

        removal = ScriptChange.objects.get(website=website, change_type="removed")
        assert removal.acknowledged_at is not None
        assert ScriptChange.objects.filter(
            website=website, change_type="added", acknowledged_at__isnull=True
        ).count() == 2  # the original first sightings, nothing new
        assert Script.objects.get(website=website, provider="Google Ads").is_active

    def test_return_after_an_acknowledged_removal_is_news(self, website):
        self._remove_ads(website)
        ScriptChange.objects.filter(website=website).update(acknowledged_at=timezone.now())

        _visit(website, [GTM, ADS])

        open_changes = ScriptChange.objects.filter(
            website=website, acknowledged_at__isnull=True
        )
        assert list(open_changes.values_list("description", flat=True)) == [
            "Script returned after removal: Google Ads (AW-805842842)"
        ]


@pytest.mark.django_db
class TestStaleSweep:
    def test_unseen_for_a_month_is_retired_silently(self, website):
        _visit(website, [GTM, ADS])
        Script.objects.filter(website=website, provider="Google Ads").update(
            last_seen_at=timezone.now() - timedelta(days=31)
        )

        purge_old_snapshots()

        assert not Script.objects.get(website=website, provider="Google Ads").is_active
        assert Script.objects.get(website=website, provider="Google Tag Manager").is_active
        assert _descriptions(website, "removed") == []


class TestRequiredAbsences:
    @pytest.mark.parametrize("rate,needed", [
        (1.0, 3), (0.9, 3), (0.5, 7), (0.3, 13), (0.1, 44),
    ])
    def test_needed_misses_scale_with_presence_rate(self, rate, needed):
        assert presence.required_absences(rate) == needed

    def test_steady_tag_confirmed_after_minimum(self):
        loads = [set(), set(), set()] + [{"a"}] * 5
        assert presence.confirmed_absences(loads) == {"a": 3}

    def test_intermittent_tag_needs_more(self):
        loads = [set(), set(), set()] + [{"a"}, set()] * 4
        assert presence.confirmed_absences(loads) == {}

    def test_too_little_history_to_judge(self):
        loads = [set(), set(), set(), set(), {"a"}, {"a"}]
        assert presence.confirmed_absences(loads) == {}

    def test_too_intermittent_is_never_called(self):
        # 10% presence needs 44 misses — beyond MAX_ABSENT_LOADS.
        loads = [set()] * 45 + [{"a"}] + [set()] * 9
        assert presence.confirmed_absences(loads) == {}


@pytest.mark.django_db
class TestHeaderTagsAreTrackedOnce:
    """A client's header runs on every page; each installed tag is one row and
    one alert however many pages load it and whatever its loader fetches."""

    SITE = [
        # Header: two GA4 properties (one "from the SEO side").
        "https://www.googletagmanager.com/gtag/js?id=G-KH1ZNV6P0N",
        "https://www.googletagmanager.com/gtag/js?id=G-T7NBHHVRYY",
        # What gtag re-requests at runtime for the same two properties.
        "https://www.googletagmanager.com/gtag/destination?id=G-KH1ZNV6P0N&cx=c&gtm=4e69n0",
        "https://www.googletagmanager.com/gtag/destination?id=G-T7NBHHVRYY&cx=c&gtm=4e69n0",
        # Footer: the GoHighLevel loader, and the chat widget it fetches.
        "https://widgets.leadconnectorhq.com/loader.js",
        "https://widgets.leadconnectorhq.com/chat-widget/loader.js",
        # Not a monitored vendor.
        "https://connect.facebook.net/en_US/fbevents.js",
    ]

    def test_every_page_one_row_per_tag(self, website):
        for i in range(12):
            _visit(website, self.SITE, page=f"https://inv.io/page-{i % 4}")

        rows = sorted(Script.objects.filter(website=website).values_list("normalized_url", flat=True))
        assert rows == [
            "https://widgets.leadconnectorhq.com/loader.js",
            "https://www.googletagmanager.com/gtag/js?id=G-KH1ZNV6P0N",
            "https://www.googletagmanager.com/gtag/js?id=G-T7NBHHVRYY",
        ]
        assert _descriptions(website, "added") == [
            "New script added: Google Analytics 4 (G-KH1ZNV6P0N)",
            "New script added: Google Analytics 4 (G-T7NBHHVRYY)",
            "New script added: LeadConnector (GoHighLevel)",
        ]
        assert ScriptChange.objects.filter(website=website).exclude(change_type="added").count() == 0


@pytest.mark.django_db
class TestMigrationRetiresWhatIsNoLongerWatched:
    def test_existing_rows_merge_and_unmonitored_ones_retire(self, website):
        import importlib

        from django.apps import apps as django_apps

        forwards = importlib.import_module(
            "apps.scripts.migrations.0033_monitored_vendors_only"
        ).forwards

        def row(src, provider):
            return Script.objects.create(
                website=website, src_url=src, normalized_url=src, provider=provider,
            )

        portal = row("https://js.hs-scripts.com/46377927.js", "HubSpot Live Chat")
        banner = row("https://js.hs-banner.com/v2/46377927/banner.js", "HubSpot Cookie Banner")
        pixel = row("https://connect.facebook.net/en_US/fbevents.js", "Meta Pixel")
        ScriptChange.objects.create(
            website=website, script=pixel, change_type="removed",
            severity="high", description="Critical script removed: Meta Pixel",
        )
        ScriptChange.objects.create(
            website=website, script=banner, change_type="added",
            severity="medium", description="New script added: HubSpot Cookie Banner",
        )

        forwards(django_apps, None)

        assert list(Script.objects.filter(website=website, is_active=True)
                    .values_list("pk", flat=True)) == [portal.pk]
        assert not Script.objects.filter(pk=banner.pk).exists()  # merged onto the portal
        assert ScriptChange.objects.get(script=pixel).acknowledged_at is not None
        assert ScriptChange.objects.get(description__contains="Cookie Banner").script_id == portal.pk
