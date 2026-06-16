import pytest

from apps.chat.intents import process_message
from apps.scripts.models import Script
from apps.websites.models import Website


@pytest.mark.django_db
def test_check_website_details_does_not_error(team):
    site = Website.objects.create(team=team, name="Digi", domain="digilatics.com")
    Script.objects.create(
        website=site, src_url="https://x.com/a.js", src_domain="x.com",
        provider="unknown", is_active=True, review_status="pending",
    )

    result = process_message(team, "open digilatics.com website details")

    assert result["type"] == "website_status"
    assert "digilatics.com" in result["reply"]
    # Counts render (previously raised AttributeError on the missing annotation).
    assert "1 unknown" in result["reply"]
