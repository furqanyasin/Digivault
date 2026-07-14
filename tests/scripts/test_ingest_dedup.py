"""End-to-end dedupe behaviour of the ingest pipeline.

Celery runs eagerly in tests, so calling the task directly exercises the full
diff → upsert → change persistence path.
"""

import pytest

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.scripts.models import DetectedForm, Script, ScriptChange
from apps.scripts.tasks import process_ingest_payload
from apps.websites.models import Website

pytestmark = pytest.mark.django_db


@pytest.fixture
def website(db):
    owner = User.objects.create_user(email="ingdedup_o@test.com", password="Pass123!")
    team = TeamService.create(name="IngDedup Agency", owner=owner)
    return Website.objects.create(team=team, name="IngDedup Site", domain="ingdedup.io")


def _script(src):
    return {
        "src": src, "location": "head", "is_async": True,
        "is_defer": False, "is_inline": False, "inline_hash": "",
        "wp_plugin": "", "wp_post_id": None,
    }


def _ingest(website, page_url, scripts, forms=None):
    process_ingest_payload(
        str(website.site_id),
        {"page_url": page_url, "scripts": scripts, "forms": forms or []},
    )


GTM = "https://www.googletagmanager.com/gtm.js?id=GTM-TEST"


class TestSiteWideChangeDedupe:
    def test_same_new_script_on_two_pages_yields_one_added_change(self, website):
        _ingest(website, "https://ingdedup.io/a", [_script(GTM)])
        _ingest(website, "https://ingdedup.io/b", [_script(GTM)])

        added = ScriptChange.objects.filter(website=website, change_type="added")
        assert added.count() == 1
        assert Script.objects.filter(website=website).count() == 1

    def test_ver_bump_creates_no_change_and_no_new_script(self, website):
        url = "https://cdn.widget.com/w.js?ver=1.0"
        _ingest(website, "https://ingdedup.io/a", [_script(url)])
        ScriptChange.objects.filter(website=website).delete()

        _ingest(website, "https://ingdedup.io/a",
                [_script("https://cdn.widget.com/w.js?ver=2.0")])

        assert ScriptChange.objects.filter(website=website).count() == 0
        script = Script.objects.get(website=website)
        assert script.normalized_url == "https://cdn.widget.com/w.js"
        assert script.src_url == "https://cdn.widget.com/w.js?ver=2.0"

    def test_seen_on_pages_stores_normalized_urls(self, website):
        _ingest(website, "https://www.ingdedup.io/contact/?utm_source=x", [_script(GTM)])
        script = Script.objects.get(website=website)
        assert script.seen_on_pages == ["https://ingdedup.io/contact"]


FORM = {
    "form_id": "wpcf7-f12", "form_name": "contact", "form_action": "/submit",
    "form_method": "post", "detection_type": "native", "provider": "",
    "fields": [{"name": "email", "type": "email", "label": "Email", "required": True}],
}


class TestFormPageDedupe:
    def test_page_url_variants_yield_one_form(self, website):
        _ingest(website, "https://ingdedup.io/contact", [], forms=[FORM])
        _ingest(website, "https://ingdedup.io/contact/", [], forms=[FORM])
        _ingest(website, "https://ingdedup.io/contact?utm_source=fb", [], forms=[FORM])

        assert DetectedForm.objects.filter(website=website).count() == 1
        form = DetectedForm.objects.get(website=website)
        assert form.page_url == "https://ingdedup.io/contact"

    def test_elementor_style_form_ingested(self, website):
        elementor_form = {
            "form_id": "elementor-form-7a2", "form_name": "Careers Application",
            "form_action": "", "form_method": "post", "detection_type": "dom",
            "provider": "Elementor Forms",
            "fields": [{"name": "form_fields[name]"}, {"name": "form_fields[email]"},
                       {"name": "form_fields[cv]"}],
        }
        _ingest(website, "https://ingdedup.io/careers", [], forms=[elementor_form])
        form = DetectedForm.objects.get(website=website)
        assert form.provider == "Elementor Forms"
        assert form.detection_type == "dom"
