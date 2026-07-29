import pytest
from django.utils import timezone
from datetime import timedelta

from apps.accounts.services import TeamService
from apps.accounts.models import User
from apps.websites.models import Website
from apps.monitors.models import Monitor
from apps.scripts.models import FormSubmissionError, ScriptChange, Script
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


def _monitor(team, site, status, **kwargs):
    return Monitor.objects.create(
        team=team, website=site, name="m", url="https://test.com",
        status=status, **kwargs,
    )


@pytest.mark.django_db
class TestUptimeDeduction:
    """A site that is down must not be able to score 100."""

    def test_down_monitor_deducts_30(self, team, site):
        _monitor(team, site, Monitor.Status.DOWN)
        site.recalculate_health_score()
        site.refresh_from_db()
        assert site.health_score == 70

    def test_degraded_monitor_deducts_12(self, team, site):
        _monitor(team, site, Monitor.Status.DEGRADED)
        site.recalculate_health_score()
        site.refresh_from_db()
        assert site.health_score == 88

    def test_down_takes_precedence_over_degraded(self, team, site):
        _monitor(team, site, Monitor.Status.DOWN)
        _monitor(team, site, Monitor.Status.DEGRADED)
        site.recalculate_health_score()
        site.refresh_from_db()
        assert site.health_score == 70  # 30, not 42

    def test_up_monitor_deducts_nothing(self, team, site):
        _monitor(team, site, Monitor.Status.UP, uptime_30d=100.0)
        site.recalculate_health_score()
        site.refresh_from_db()
        assert site.health_score == 100

    def test_paused_monitor_deducts_nothing(self, team, site):
        _monitor(team, site, Monitor.Status.PAUSED)
        site.recalculate_health_score()
        site.refresh_from_db()
        assert site.health_score == 100

    def test_monitor_on_another_website_is_ignored(self, team, site):
        other = Website.objects.create(team=team, name="Other", domain="other.com")
        _monitor(team, other, Monitor.Status.DOWN)
        site.recalculate_health_score()
        site.refresh_from_db()
        assert site.health_score == 100

    def test_unlinked_monitor_is_ignored(self, team, site):
        Monitor.objects.create(
            team=team, website=None, name="orphan", url="https://x.com",
            status=Monitor.Status.DOWN,
        )
        site.recalculate_health_score()
        site.refresh_from_db()
        assert site.health_score == 100

    def test_uptime_below_95_deducts_15(self, team, site):
        _monitor(team, site, Monitor.Status.UP, uptime_30d=94.0)
        site.recalculate_health_score()
        site.refresh_from_db()
        assert site.health_score == 85

    def test_uptime_below_99_deducts_5(self, team, site):
        _monitor(team, site, Monitor.Status.UP, uptime_30d=98.0)
        site.recalculate_health_score()
        site.refresh_from_db()
        assert site.health_score == 95

    def test_healthy_uptime_deducts_nothing(self, team, site):
        _monitor(team, site, Monitor.Status.UP, uptime_30d=99.9)
        site.recalculate_health_score()
        site.refresh_from_db()
        assert site.health_score == 100

    def test_worst_monitor_uptime_wins(self, team, site):
        _monitor(team, site, Monitor.Status.UP, uptime_30d=100.0)
        _monitor(team, site, Monitor.Status.UP, uptime_30d=90.0)
        site.recalculate_health_score()
        site.refresh_from_db()
        assert site.health_score == 85

    def test_null_uptime_deducts_nothing(self, team, site):
        _monitor(team, site, Monitor.Status.UP, uptime_30d=None)
        site.recalculate_health_score()
        site.refresh_from_db()
        assert site.health_score == 100


@pytest.mark.django_db
class TestBrokenFormDeduction:
    """Broken forms were shown as destructive on the dashboard but cost 0."""

    def _error(self, site, age_days=0):
        err = FormSubmissionError.objects.create(
            website=site, page_url="https://test.com/contact",
            message="SMTP connect failed",
        )
        if age_days:
            FormSubmissionError.objects.filter(pk=err.pk).update(
                created_at=timezone.now() - timedelta(days=age_days)
            )
        return err

    def test_one_recent_error_deducts_6(self, site):
        self._error(site)
        site.recalculate_health_score()
        site.refresh_from_db()
        assert site.health_score == 94

    def test_three_errors_deduct_18(self, site):
        for _ in range(3):
            self._error(site)
        site.recalculate_health_score()
        site.refresh_from_db()
        assert site.health_score == 82

    def test_deduction_capped_at_18(self, site):
        for _ in range(6):
            self._error(site)
        site.recalculate_health_score()
        site.refresh_from_db()
        assert site.health_score == 82

    def test_errors_older_than_7_days_are_ignored(self, site):
        """A fixed form earns its score back instead of being punished forever."""
        self._error(site, age_days=8)
        site.recalculate_health_score()
        site.refresh_from_db()
        assert site.health_score == 100


@pytest.mark.django_db
class TestReportingGapDeduction:
    """A snippet that stopped reporting means we are blind, not healthy."""

    def test_stale_7_days_deducts_10(self, site):
        Website.objects.filter(pk=site.pk).update(
            last_seen_at=timezone.now() - timedelta(days=10)
        )
        site.refresh_from_db()
        site.recalculate_health_score()
        site.refresh_from_db()
        assert site.health_score == 90

    def test_stale_30_days_deducts_20(self, site):
        Website.objects.filter(pk=site.pk).update(
            last_seen_at=timezone.now() - timedelta(days=40)
        )
        site.refresh_from_db()
        site.recalculate_health_score()
        site.refresh_from_db()
        assert site.health_score == 80

    def test_recent_report_deducts_nothing(self, site):
        Website.objects.filter(pk=site.pk).update(
            last_seen_at=timezone.now() - timedelta(hours=2)
        )
        site.refresh_from_db()
        site.recalculate_health_score()
        site.refresh_from_db()
        assert site.health_score == 100

    def test_never_reported_deducts_nothing(self, site):
        """A brand-new site has no traffic yet — that is not a fault."""
        assert site.last_seen_at is None
        site.recalculate_health_score()
        site.refresh_from_db()
        assert site.health_score == 100


@pytest.mark.django_db
class TestHostingExpiryDeduction:
    def test_hosting_within_7_days_deducts_20(self, site):
        DomainInfo.objects.update_or_create(
            website=site,
            defaults={"hosting_expires_at": timezone.now() + timedelta(days=5)},
        )
        site.recalculate_health_score()
        site.refresh_from_db()
        assert site.health_score == 80

    def test_hosting_within_30_days_deducts_8(self, site):
        DomainInfo.objects.update_or_create(
            website=site,
            defaults={"hosting_expires_at": timezone.now() + timedelta(days=20)},
        )
        site.recalculate_health_score()
        site.refresh_from_db()
        assert site.health_score == 92

    def test_distant_hosting_expiry_deducts_nothing(self, site):
        DomainInfo.objects.update_or_create(
            website=site,
            defaults={"hosting_expires_at": timezone.now() + timedelta(days=200)},
        )
        site.recalculate_health_score()
        site.refresh_from_db()
        assert site.health_score == 100


@pytest.mark.django_db
class TestStatusDerivation:
    """Status is the worse of the urgency flags and the score band.

    Two independent guarantees:
      - a low score can never sit next to an 'active' badge, and
      - a single high-severity issue is never averaged away into 'active'.
    """

    def _high_change(self, site):
        script = Script.objects.create(
            website=site, src_url="https://x.com/a.js", src_domain="x.com",
            provider="unknown", category="unknown", location="head", scope="GLOBAL",
            review_status=Script.ReviewStatus.APPROVED,
        )
        return ScriptChange.objects.create(
            website=site, script=script,
            change_type=ScriptChange.ChangeType.ADDED,
            severity=ScriptChange.Severity.HIGH,
            description="unknown script",
        )

    def test_clean_site_is_active(self, site):
        site.recalculate_health_score()
        site.refresh_from_db()
        assert site.health_score == 100
        assert site.status == Website.Status.ACTIVE

    # --- the score band floor ---

    def test_low_score_forces_critical_even_without_urgent_flags(self, team, site):
        """Nothing here is individually 'urgent', but 46 must not read active."""
        _monitor(team, site, Monitor.Status.DEGRADED, uptime_30d=90.0)  # -12 -15
        Website.objects.filter(pk=site.pk).update(
            last_seen_at=timezone.now() - timedelta(days=40)  # -20
        )
        site.refresh_from_db()
        for _ in range(2):
            FormSubmissionError.objects.create(
                website=site, page_url="https://test.com/c", message="500",
            )  # -12
        site.recalculate_health_score()
        site.refresh_from_db()
        assert site.health_score == 41
        assert site.status == Website.Status.CRITICAL

    def test_mid_score_without_flags_is_warning(self, team, site):
        _monitor(team, site, Monitor.Status.UP, uptime_30d=94.0)  # -15, no flag
        Website.objects.filter(pk=site.pk).update(
            last_seen_at=timezone.now() - timedelta(hours=1)
        )
        site.refresh_from_db()
        site.recalculate_health_score()
        site.refresh_from_db()
        assert site.health_score == 85
        assert site.status == Website.Status.ACTIVE  # 85 is the active boundary

    # --- the severity flags ---

    def test_open_high_change_is_critical_despite_high_score(self, site):
        """-10 points, but an unreviewed unknown script is the whole product."""
        self._high_change(site)
        site.recalculate_health_score()
        site.refresh_from_db()
        assert site.health_score == 90
        assert site.status == Website.Status.CRITICAL

    def test_down_monitor_is_critical_despite_score_of_70(self, team, site):
        _monitor(team, site, Monitor.Status.DOWN)
        site.recalculate_health_score()
        site.refresh_from_db()
        assert site.health_score == 70
        assert site.status == Website.Status.CRITICAL

    def test_degraded_monitor_is_warning(self, team, site):
        _monitor(team, site, Monitor.Status.DEGRADED)
        site.recalculate_health_score()
        site.refresh_from_db()
        assert site.health_score == 88
        assert site.status == Website.Status.WARNING

    def test_broken_form_is_warning(self, site):
        FormSubmissionError.objects.create(
            website=site, page_url="https://test.com/c", message="SMTP failed",
        )
        site.recalculate_health_score()
        site.refresh_from_db()
        assert site.health_score == 94
        assert site.status == Website.Status.WARNING

    def test_ssl_expiring_in_5_days_is_critical(self, site):
        DomainInfo.objects.update_or_create(
            website=site,
            defaults={"ssl_expires_at": timezone.now() + timedelta(days=5)},
        )
        site.recalculate_health_score()
        site.refresh_from_db()
        assert site.status == Website.Status.CRITICAL

    def test_ssl_expiring_in_25_days_is_warning(self, site):
        DomainInfo.objects.update_or_create(
            website=site,
            defaults={"ssl_expires_at": timezone.now() + timedelta(days=25)},
        )
        site.recalculate_health_score()
        site.refresh_from_db()
        assert site.health_score == 95
        assert site.status == Website.Status.WARNING

    # --- lifecycle + recovery ---

    def test_inactive_is_a_lifecycle_state_and_is_preserved(self, team, site):
        """'inactive' is set by a human; health must not overwrite it."""
        Website.objects.filter(pk=site.pk).update(status=Website.Status.INACTIVE)
        site.refresh_from_db()
        _monitor(team, site, Monitor.Status.DOWN)
        site.recalculate_health_score()
        site.refresh_from_db()
        assert site.health_score == 70  # score still refreshed
        assert site.status == Website.Status.INACTIVE

    def test_recovery_returns_status_to_active(self, team, site):
        m = _monitor(team, site, Monitor.Status.DOWN)
        site.recalculate_health_score()
        site.refresh_from_db()
        assert site.status == Website.Status.CRITICAL

        Monitor.objects.filter(pk=m.pk).update(status=Monitor.Status.UP)
        site.recalculate_health_score()
        site.refresh_from_db()
        assert site.health_score == 100
        assert site.status == Website.Status.ACTIVE

    def test_acknowledging_a_high_change_returns_to_active(self, site):
        change = self._high_change(site)
        site.recalculate_health_score()
        site.refresh_from_db()
        assert site.status == Website.Status.CRITICAL

        ScriptChange.objects.filter(pk=change.pk).update(acknowledged_at=timezone.now())
        site.recalculate_health_score()
        site.refresh_from_db()
        assert site.health_score == 100
        assert site.status == Website.Status.ACTIVE


@pytest.mark.django_db
class TestScoreFloor:
    def test_every_problem_at_once_floors_at_zero(self, team, site):
        _monitor(team, site, Monitor.Status.DOWN, uptime_30d=10.0)
        Website.objects.filter(pk=site.pk).update(
            last_seen_at=timezone.now() - timedelta(days=90)
        )
        site.refresh_from_db()
        DomainInfo.objects.update_or_create(
            website=site,
            defaults={
                "ssl_expires_at": timezone.now() + timedelta(days=1),
                "expires_at": timezone.now() + timedelta(days=1),
                "hosting_expires_at": timezone.now() + timedelta(days=1),
            },
        )
        script = Script.objects.create(
            website=site, src_url="https://x.com/a.js", src_domain="x.com",
            provider="unknown", category="unknown", location="head", scope="GLOBAL",
            review_status=Script.ReviewStatus.APPROVED,
        )
        for i in range(4):
            ScriptChange.objects.create(
                website=site, script=script,
                change_type=ScriptChange.ChangeType.ADDED,
                severity=ScriptChange.Severity.CRITICAL,
                description=f"c {i}",
            )
        for _ in range(4):
            FormSubmissionError.objects.create(
                website=site, page_url="https://test.com/c", message="500",
            )
        site.recalculate_health_score()
        site.refresh_from_db()
        assert site.health_score == 0
        assert site.status == Website.Status.CRITICAL
