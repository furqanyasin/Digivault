"""The severity vocabulary must be one vocabulary.

`ScriptChange.Severity` has offered `critical` since it was written. The
matcher's private rank map never listed it and read ranks with `.get(sev, 0)`,
so a critical change scored below every possible rule minimum: the one severity
the product exists to surface was the only one that could never be delivered.
These pin the two halves of that — the rank table itself, and the rule matcher
that reads it.
"""

import pytest

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.alerts.models import AlertRule
from apps.alerts.services import AlertService
from apps.common import severity as sev
from apps.scripts.models import ScriptChange
from apps.websites.models import Website


@pytest.fixture
def owner(db):
    return User.objects.create_user(email="sev_owner@test.com", password="Pass123!")


@pytest.fixture
def team(owner):
    return TeamService.create(name="Severity Agency", owner=owner)


@pytest.fixture
def website(team):
    return Website.objects.create(team=team, name="Sev Site", domain="sev.io")


def _change(website, severity):
    return ScriptChange.objects.create(
        website=website,
        change_type=ScriptChange.ChangeType.ADDED,
        severity=severity,
        description=f"{severity} change",
    )


class TestSeverityRanks:
    def test_critical_outranks_high(self):
        assert sev.rank("critical", default=0) > sev.rank("high", default=0)

    def test_every_model_severity_is_ranked(self):
        """Nothing the models can store may fall through to a default."""
        from apps.site_health.models import SiteEvent

        words = [s.value for s in ScriptChange.Severity]
        words += [s.value for s in SiteEvent.Severity]
        for word in words:
            # A sentinel no real rank can equal, so a miss is visible.
            assert sev.rank(word, default=-1) != -1, word

    def test_every_rule_minimum_is_ranked(self):
        for value, _label in sev.MIN_SEVERITY_CHOICES:
            assert sev.rank(value, default=-1) != -1, value

    def test_unknown_observed_severity_is_over_delivered_not_dropped(self):
        """The failure mode of an unmapped word must be noise, never silence."""
        assert sev.meets("some-future-word", "critical") is True

    def test_unknown_rule_minimum_is_cleared_by_anything(self):
        assert sev.meets("low", "some-future-word") is True

    def test_meets_is_inclusive_at_the_threshold(self):
        assert sev.meets("high", "high") is True
        assert sev.meets("medium", "high") is False


@pytest.mark.django_db
class TestCriticalChangesReachRules:
    def test_critical_change_matches_a_high_minimum_rule(self, website, team):
        """The regression itself: this used to produce zero notifications."""
        AlertRule.objects.create(
            team=team,
            website=None,
            channel=AlertRule.Channel.IN_APP,
            min_severity="high",
            delivery_mode=AlertRule.DeliveryMode.IMMEDIATE,
        )
        notifications = AlertService.dispatch_for_change(
            _change(website, ScriptChange.Severity.CRITICAL)
        )
        assert len(notifications) == 1

    def test_critical_only_rule_ignores_a_high_change(self, website, team):
        AlertRule.objects.create(
            team=team,
            website=None,
            channel=AlertRule.Channel.IN_APP,
            min_severity="critical",
            delivery_mode=AlertRule.DeliveryMode.IMMEDIATE,
        )
        assert AlertService.dispatch_for_change(
            _change(website, ScriptChange.Severity.HIGH)
        ) == []
        assert len(
            AlertService.dispatch_for_change(
                _change(website, ScriptChange.Severity.CRITICAL)
            )
        ) == 1
