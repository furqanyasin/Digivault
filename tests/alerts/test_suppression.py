"""Phase 1.3 — alert suppression (mute a provider/domain per website)."""

import pytest

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.alerts.models import AlertRule, AlertSuppression
from apps.alerts.services import AlertService
from apps.scripts.models import Script, ScriptChange
from apps.websites.models import Website


@pytest.fixture
def owner(db):
    return User.objects.create_user(email="sup_o@test.com", password="Pass123!")


@pytest.fixture
def sup_team(owner):
    return TeamService.create(name="Sup Agency", owner=owner)


@pytest.fixture
def sup_website(sup_team):
    return Website.objects.create(team=sup_team, name="S", domain="sup.io")


def _change(website, provider="evil", domain="evil.com", severity="high"):
    script = Script.objects.create(
        website=website,
        src_url=f"https://{domain}/x.js",
        src_domain=domain,
        provider=provider,
        is_active=True,
    )
    return ScriptChange.objects.create(
        website=website, script=script, change_type="added",
        severity=severity, description="x",
    )


@pytest.mark.django_db
class TestSuppressionDispatch:
    def test_suppressed_provider_blocks(self, sup_website, sup_team):
        AlertRule.objects.create(team=sup_team, channel="in_app", min_severity="low")
        AlertSuppression.objects.create(
            website=sup_website, match_type="provider", match_value="evil"
        )
        change = _change(sup_website, provider="evil")
        assert AlertService.dispatch_for_change(change) == []

    def test_suppressed_domain_blocks(self, sup_website, sup_team):
        AlertRule.objects.create(team=sup_team, channel="in_app", min_severity="low")
        AlertSuppression.objects.create(
            website=sup_website, match_type="domain", match_value="evil.com"
        )
        change = _change(sup_website, domain="evil.com")
        assert AlertService.dispatch_for_change(change) == []

    def test_non_matching_suppression_allows(self, sup_website, sup_team):
        AlertRule.objects.create(team=sup_team, channel="in_app", min_severity="low")
        AlertSuppression.objects.create(
            website=sup_website, match_type="provider", match_value="other"
        )
        change = _change(sup_website, provider="evil")
        assert len(AlertService.dispatch_for_change(change)) == 1


@pytest.mark.django_db
class TestSuppressionAPI:
    def test_create_list_delete(self, auth_client, team):
        website = Website.objects.create(team=team, name="S", domain="api-sup.io")
        resp = auth_client.post(
            f"/api/v1/websites/{website.pk}/alert-suppressions/",
            {"match_type": "provider", "match_value": "evil"},
            format="json",
        )
        assert resp.status_code == 201
        sup_id = resp.data["id"]

        resp = auth_client.get(f"/api/v1/websites/{website.pk}/alert-suppressions/")
        assert resp.status_code == 200
        assert len(resp.data) == 1

        resp = auth_client.delete(f"/api/v1/alert-suppressions/{sup_id}/")
        assert resp.status_code == 204
        assert AlertSuppression.objects.filter(pk=sup_id).count() == 0
