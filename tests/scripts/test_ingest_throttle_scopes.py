"""The public ingest endpoints must not share one rate-limit budget.

`/api/ingest/` posts several times per pageview — DOMContentLoaded, 2.5s, then
one per DOM-mutation burst for 30s. A form submission happens once per
conversion and a form error once per broken submit. On a single shared bucket
the loud endpoint spent it, and from that point in the day every conversion and
every broken-form alarm was answered 429 and dropped — leaving a form counter
frozen at zero, which is indistinguishable from a site nobody filled a form in.
"""

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.scripts.models import DetectedForm
from apps.scripts.views import (
    FormErrorIngestView,
    FormSubmissionIngestView,
    IngestView,
    JsErrorIngestView,
)
from apps.websites.models import Website

PAGE = "https://throttle.io/contact"
FORM = {
    "form_id": "", "form_name": "Contact Form", "form_action": PAGE,
    "form_method": "post", "detection_type": "native", "provider": "",
    "fields": [{"name": "email", "type": "email", "label": "Email", "required": True}],
}


@pytest.fixture
def website(db):
    owner = User.objects.create_user(email="throttle@test.com", password="Pass123!")
    team = TeamService.create(name="Throttle Agency", owner=owner)
    return Website.objects.create(team=team, name="Throttle", domain="throttle.io")


@pytest.fixture(autouse=True)
def _clear_throttle_cache():
    cache.clear()
    yield
    cache.clear()


def _scope(view):
    return view.throttle_classes[0]().scope


class TestScopesAreSeparate:
    def test_scripts_forms_and_js_errors_each_have_their_own(self):
        scopes = {
            _scope(IngestView),
            _scope(FormSubmissionIngestView),
            _scope(JsErrorIngestView),
        }
        assert len(scopes) == 3

    def test_submissions_and_form_errors_share_one_bucket(self):
        # Two halves of the same picture: submits observed, and submits that
        # visibly failed. A success rate computed from a budget that ran out on
        # one side only would be worse than no number at all.
        assert _scope(FormSubmissionIngestView) == _scope(FormErrorIngestView)

    def test_every_scope_has_a_configured_rate(self):
        # A scope with no entry in DEFAULT_THROTTLE_RATES makes DRF raise on the
        # first request to that endpoint.
        for view in (
            IngestView, FormSubmissionIngestView, FormErrorIngestView, JsErrorIngestView,
        ):
            throttle = view.throttle_classes[0]()
            assert throttle.rate, f"{view.__name__} has no rate"

    def test_the_configured_rate_is_not_shadowed_by_a_hardcoded_one(self, settings):
        # DRF consults DEFAULT_THROTTLE_RATES only when the class sets no `rate`
        # attribute, so a hardcoded one makes the THROTTLE_* env knob dead.
        configured = settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["ingest"]
        assert IngestView.throttle_classes[0]().rate == configured


@pytest.mark.django_db
class TestBudgetsDoNotStarveEachOther:
    def test_exhausting_the_script_budget_leaves_submissions_working(
        self, website, settings, monkeypatch
    ):
        # Squeeze the script bucket down to one request, then spend it. The
        # submission that follows must still be counted: this is the live
        # failure, where an ordinary day's pageviews used up the shared budget
        # and every later conversion was thrown away.
        monkeypatch.setattr(
            "apps.scripts.views.ScriptIngestThrottle.rate", "1/day", raising=False
        )
        client = APIClient()
        body = {"site_id": website.site_id, "page_url": PAGE, "scripts": [], "forms": []}

        assert client.post("/api/ingest/", body, format="json").status_code != 429
        assert client.post("/api/ingest/", body, format="json").status_code == 429

        resp = client.post(
            "/api/ingest/form-submission/",
            {"site_id": website.site_id, "page_url": PAGE, "form": FORM},
            format="json",
        )

        assert resp.status_code == 202
        assert DetectedForm.objects.get(website=website).submission_count == 1
