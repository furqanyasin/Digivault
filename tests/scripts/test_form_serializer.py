"""DetectedFormSerializer — managed vs third-party embedded forms."""

import pytest

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.scripts.models import DetectedForm
from apps.scripts.serializers import DetectedFormSerializer
from apps.websites.models import Website

pytestmark = pytest.mark.django_db


@pytest.fixture
def website(db):
    owner = User.objects.create_user(email="formser_o@test.com", password="Pass123!")
    team = TeamService.create(name="FormSer Agency", owner=owner)
    return Website.objects.create(team=team, name="FormSer Site", domain="formser.io")


def _form(website, detection_type, **kwargs):
    data = {
        "detection_type": detection_type,
        "form_action": kwargs.pop("form_action", "/submit"),
        "fields": kwargs.pop("fields", [{"name": "email"}]),
        **kwargs,
    }
    return DetectedForm.objects.create(
        website=website,
        page_url="https://formser.io/contact",
        fingerprint=DetectedForm.compute_fingerprint(data),
        **data,
    )


class TestIsManaged:
    def test_native_form_is_managed(self, website):
        form = _form(website, DetectedForm.DetectionType.NATIVE)
        assert DetectedFormSerializer(form).data["is_managed"] is True

    def test_dom_form_is_managed(self, website):
        form = _form(website, DetectedForm.DetectionType.DOM, form_action="")
        assert DetectedFormSerializer(form).data["is_managed"] is True

    def test_embedded_iframe_form_is_not_managed(self, website):
        form = _form(
            website, DetectedForm.DetectionType.EMBEDDED,
            form_action="", fields=[], provider="ISA",
        )
        assert DetectedFormSerializer(form).data["is_managed"] is False
