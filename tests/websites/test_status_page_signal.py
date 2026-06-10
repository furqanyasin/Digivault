"""Auto-provisioning of a status page when a Website is created (and no dupes)."""

import pytest

from apps.status_pages.models import StatusPage, StatusPageMonitor
from apps.websites.models import Website


@pytest.mark.django_db
class TestStatusPageAutoCreate:
    def test_creating_website_creates_one_status_page(self, team):
        Website.objects.create(team=team, name="Acme", domain="acme.com")
        pages = StatusPage.objects.filter(team=team)
        assert pages.count() == 1
        assert pages.first().slug == "acme-com"
        # The auto-created uptime monitor is attached to the page.
        assert StatusPageMonitor.objects.filter(status_page=pages.first()).count() == 1

    def test_same_domain_added_twice_does_not_duplicate_page(self, team):
        Website.objects.create(team=team, name="Acme", domain="acme.com")
        Website.objects.create(team=team, name="Acme Again", domain="acme.com")
        # Only one status page for the domain — the second add is deduped.
        assert StatusPage.objects.filter(team=team).count() == 1
        # No `-1` collision variant was created.
        assert not StatusPage.objects.filter(slug="acme-com-1").exists()

    def test_different_domains_each_get_a_page(self, team):
        Website.objects.create(team=team, name="Acme", domain="acme.com")
        Website.objects.create(team=team, name="Beta", domain="beta.io")
        assert StatusPage.objects.filter(team=team).count() == 2

    def test_same_domain_other_team_gets_its_own_page(self, team):
        from apps.accounts.models import User
        from apps.accounts.services import TeamService

        Website.objects.create(team=team, name="Acme", domain="acme.com")

        other_owner = User.objects.create_user(email="o2@test.com", password="Pass123!")
        other_team = TeamService.create(name="Other", owner=other_owner)
        Website.objects.create(team=other_team, name="Acme2", domain="acme.com")

        # Each team has exactly one page; the second uses a `-1` slug to satisfy
        # the model's global slug-uniqueness.
        assert StatusPage.objects.filter(team=team).count() == 1
        assert StatusPage.objects.filter(team=other_team).count() == 1
        assert StatusPage.objects.filter(slug="acme-com").count() == 1
        assert StatusPage.objects.filter(slug="acme-com-1").count() == 1
