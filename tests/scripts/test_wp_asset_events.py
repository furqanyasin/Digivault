"""WordPress asset changes recorded as SiteEvents by the ingest pipeline."""

import pytest

from apps.scripts.tasks import process_ingest_payload
from apps.site_health.models import SiteEvent
from apps.websites.models import Website

PAGE = "https://wp.example/"
P = "https://wp.example/wp-content/plugins/{}/js/app.js?ver={}"
CORE_JS = "https://wp.example/wp-includes/js/jquery/jquery.min.js?ver={}"
GTM = "https://www.googletagmanager.com/gtm.js?id=GTM-AAA"


@pytest.fixture
def website(team):
    return Website.objects.create(team=team, name="WP Site", domain="wp.example")


def ingest(website, scripts, page=PAGE):
    process_ingest_payload(
        str(website.site_id),
        {"page_url": page, "scripts": [{"src": u, "location": "head"} for u in scripts]},
    )


def events(website, event_type=None):
    qs = SiteEvent.objects.filter(website=website)
    if event_type:
        qs = qs.filter(event_type=event_type)
    return list(qs)


@pytest.mark.django_db
class TestWpAssetEvents:
    def test_first_ingest_records_no_asset_events(self, website):
        ingest(website, [P.format("wpforms", "1.8"), GTM])
        assert events(website) == []

    def test_plugin_update_is_recorded(self, website):
        ingest(website, [P.format("wpforms", "1.8.4")])
        ingest(website, [P.format("wpforms", "1.9.0")])

        updated = events(website, SiteEvent.EventType.PLUGIN_UPDATED)
        assert len(updated) == 1
        assert updated[0].details["old_version"] == "1.8.4"
        assert updated[0].details["new_version"] == "1.9.0"

    def test_core_update_is_recorded_even_though_core_scripts_are_untracked(self, website):
        # /wp-includes/ is filtered out of Script tracking as noise, so this only
        # works because asset detection reads the unfiltered payload.
        ingest(website, [CORE_JS.format("6.7.1"), GTM])
        ingest(website, [CORE_JS.format("6.8"), GTM])

        assert len(events(website, SiteEvent.EventType.CORE_UPDATED)) == 1

    def test_plugin_install_and_removal(self, website):
        ingest(website, [P.format("wpforms", "1.8")])
        ingest(website, [P.format("wpforms", "1.8"), P.format("elementor", "3.2")])
        ingest(website, [P.format("elementor", "3.2")])

        assert len(events(website, SiteEvent.EventType.PLUGIN_INSTALLED)) == 1
        removed = events(website, SiteEvent.EventType.PLUGIN_REMOVED)
        assert len(removed) == 1
        assert removed[0].severity == SiteEvent.Severity.WARNING

    def test_repeat_visits_do_not_duplicate_the_same_change(self, website):
        ingest(website, [P.format("wpforms", "1.8")])
        ingest(website, [P.format("wpforms", "1.9")])
        # Every subsequent visitor re-reports 1.9 against the 1.8 snapshot until
        # it rolls over; that must not mint an event each time.
        ingest(website, [P.format("wpforms", "1.9")])
        ingest(website, [P.format("wpforms", "1.9")])

        assert len(events(website, SiteEvent.EventType.PLUGIN_UPDATED)) == 1

    def test_new_page_is_recorded_but_not_the_first_page(self, website):
        ingest(website, [GTM], page="https://wp.example/")
        assert events(website, SiteEvent.EventType.PAGE_DISCOVERED) == []

        ingest(website, [GTM], page="https://wp.example/contact")
        found = events(website, SiteEvent.EventType.PAGE_DISCOVERED)
        assert len(found) == 1
        assert "contact" in found[0].summary

        # Revisiting an established page is not a discovery.
        ingest(website, [GTM], page="https://wp.example/contact")
        assert len(events(website, SiteEvent.EventType.PAGE_DISCOVERED)) == 1

    def test_third_party_only_site_produces_no_asset_events(self, website):
        ingest(website, [GTM])
        ingest(website, [GTM, "https://static.hotjar.com/c/hotjar-1.js"])
        assert events(website, SiteEvent.EventType.PLUGIN_INSTALLED) == []
