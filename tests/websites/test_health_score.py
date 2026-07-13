import pytest
from django.utils import timezone
from datetime import timedelta

from apps.accounts.services import TeamService
from apps.accounts.models import User
from apps.websites.models import Website
from apps.scripts.models import ScriptChange, Script
from apps.domains.models import DomainInfo


@pytest.fixture
def owner(db):
    return User.objects.create_user(email="hs@test.com", password="Pass123!")


@pytest.fixture
def team(owner):
    return TeamService.create(name="HS Agency", owner=owner)


@pytest.fixture
def site(team):
    return Website.objects.create(team=team, name="Test Site", domain="test.com")


@pytest.mark.django_db
class TestHealthScore:
    def test_default_score_is_100(self, site):
        assert site.health_score == 100

    def test_recalculate_returns_100_for_clean_site(self, site):
        site.recalculate_health_score()
        site.refresh_from_db()
        assert site.health_score == 100

    def test_pending_critical_change_deducts_15(self, site):
        script = Script.objects.create(
            website=site, src_url="https://x.com/a.js", src_domain="x.com",
            provider="unknown", category="unknown", location="head", scope="GLOBAL",
            review_status=Script.ReviewStatus.APPROVED,
        )
        ScriptChange.objects.create(
            website=site, script=script,
            change_type=ScriptChange.ChangeType.ADDED,
            severity=ScriptChange.Severity.CRITICAL,
            description="new script",
        )
        site.recalculate_health_score()
        site.refresh_from_db()
        assert site.health_score == 85  # 100 - 15

    def test_critical_deduction_capped_at_30(self, site):
        script = Script.objects.create(
            website=site, src_url="https://x.com/a.js", src_domain="x.com",
            provider="unknown", category="unknown", location="head", scope="GLOBAL",
            review_status=Script.ReviewStatus.APPROVED,
        )
        for i in range(5):
            ScriptChange.objects.create(
                website=site, script=script,
                change_type=ScriptChange.ChangeType.ADDED,
                severity=ScriptChange.Severity.CRITICAL,
                description=f"change {i}",
            )
        site.recalculate_health_score()
        site.refresh_from_db()
        # 5 * 15 = 75 but capped at 30 for criticals → deduction = 30
        assert site.health_score == 70  # 100 - 30

    def test_acknowledged_changes_not_counted(self, site):
        script = Script.objects.create(
            website=site, src_url="https://x.com/a.js", src_domain="x.com",
            provider="unknown", category="unknown", location="head", scope="GLOBAL",
            review_status=Script.ReviewStatus.APPROVED,
        )
        ScriptChange.objects.create(
            website=site, script=script,
            change_type=ScriptChange.ChangeType.ADDED,
            severity=ScriptChange.Severity.CRITICAL,
            description="acked",
            acknowledged_at=timezone.now(),
        )
        site.recalculate_health_score()
        site.refresh_from_db()
        assert site.health_score == 100

    def test_ssl_expiry_within_14_days_deducts_12(self, site):
        DomainInfo.objects.update_or_create(
            website=site,
            defaults={"ssl_expires_at": timezone.now() + timedelta(days=10)},
        )
        site.recalculate_health_score()
        site.refresh_from_db()
        assert site.health_score == 88  # 100 - 12

    def test_ssl_expiry_within_7_days_deducts_20(self, site):
        DomainInfo.objects.update_or_create(
            website=site,
            defaults={"ssl_expires_at": timezone.now() + timedelta(days=5)},
        )
        site.recalculate_health_score()
        site.refresh_from_db()
        assert site.health_score == 80  # 100 - 20

    def test_score_clamped_to_zero(self, site):
        script = Script.objects.create(
            website=site, src_url="https://x.com/a.js", src_domain="x.com",
            provider="unknown", category="unknown", location="head", scope="GLOBAL",
            review_status=Script.ReviewStatus.APPROVED,
        )
        for i in range(3):
            ScriptChange.objects.create(
                website=site, script=script,
                change_type=ScriptChange.ChangeType.ADDED,
                severity=ScriptChange.Severity.CRITICAL,
                description=f"c {i}",
            )
            ScriptChange.objects.create(
                website=site, script=script,
                change_type=ScriptChange.ChangeType.ADDED,
                severity=ScriptChange.Severity.HIGH,
                description=f"h {i}",
            )
        DomainInfo.objects.update_or_create(
            website=site,
            defaults={
                "ssl_expires_at": timezone.now() + timedelta(days=3),
                "expires_at": timezone.now() + timedelta(days=3),
            },
        )
        site.recalculate_health_score()
        site.refresh_from_db()
        assert site.health_score >= 0


@pytest.mark.django_db
class TestPendingReviewDeduction:
    def _script(self, site, n, **kwargs):
        return Script.objects.create(
            website=site, src_url=f"https://ext{n}.com/a.js", src_domain=f"ext{n}.com",
            provider="unknown", category="unknown", location="head", scope="GLOBAL",
            **kwargs,
        )

    def test_pending_active_scripts_deduct_2_each(self, site):
        for n in range(3):
            self._script(site, n)  # review_status defaults to pending
        site.recalculate_health_score()
        site.refresh_from_db()
        assert site.health_score == 94  # 100 - 3*2

    def test_deduction_capped_at_10(self, site):
        for n in range(8):
            self._script(site, n)
        site.recalculate_health_score()
        site.refresh_from_db()
        assert site.health_score == 90  # 8*2=16 capped at 10

    def test_approving_restores_score(self, site):
        s = self._script(site, 0)
        site.recalculate_health_score()
        site.refresh_from_db()
        assert site.health_score == 98

        Script.objects.filter(pk=s.pk).update(review_status=Script.ReviewStatus.APPROVED)
        site.recalculate_health_score()
        site.refresh_from_db()
        assert site.health_score == 100

    def test_inactive_pending_scripts_not_counted(self, site):
        self._script(site, 0, is_active=False)
        site.recalculate_health_score()
        site.refresh_from_db()
        assert site.health_score == 100
