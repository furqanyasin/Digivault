"""A single failed request must not become an outage.

UptimeRobot re-checks up to three times, 10-20s apart, before marking a monitor
down. Stacks Monitor checked once, and auto-provisioned monitors alerted on that one
result. One 403, one TCP reset or one slow DNS lookup was a page-out.
"""

from unittest.mock import patch

import pytest

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.monitors.models import Monitor, MonitorCheck
from apps.monitors.tasks import check_single_monitor


@pytest.fixture
def owner(db):
    return User.objects.create_user(email="owner@confirm.com", password="SecurePass1!")


@pytest.fixture
def team(owner):
    return TeamService.create(name="Confirm Team", owner=owner)


@pytest.fixture
def monitor(team):
    return Monitor.objects.create(
        team=team,
        name="Confirm Site",
        url="https://example.com",
        monitor_type="http",
        status="up",
        retry_count=1,
    )


DOWN = {"status": "down", "response_time_ms": None, "status_code": 500, "error_message": "HTTP 500"}
UP = {"status": "up", "response_time_ms": 120, "status_code": 200, "error_message": ""}
BLOCKED = {"status": "blocked", "response_time_ms": 90, "status_code": 403, "error_message": "Blocked by Wordfence"}


@pytest.mark.django_db
def test_first_failure_writes_no_check_and_requeues(monitor):
    """Attempt 1 failing is a suspicion, not evidence. Nothing is recorded."""
    with patch("apps.monitors.checker.run_check", return_value=DOWN), \
         patch("apps.monitors.tasks.check_single_monitor.apply_async") as requeue:
        check_single_monitor(str(monitor.pk))

    assert MonitorCheck.objects.filter(monitor=monitor).count() == 0
    monitor.refresh_from_db()
    assert monitor.consecutive_failures == 0
    assert monitor.status == "up"

    requeue.assert_called_once()
    assert requeue.call_args.kwargs["args"] == [str(monitor.pk), 2]
    assert requeue.call_args.kwargs["countdown"] == 15


@pytest.mark.django_db
def test_second_failure_requeues_with_the_longer_delay(monitor):
    with patch("apps.monitors.checker.run_check", return_value=DOWN), \
         patch("apps.monitors.tasks.check_single_monitor.apply_async") as requeue:
        check_single_monitor(str(monitor.pk), attempt=2)

    assert MonitorCheck.objects.filter(monitor=monitor).count() == 0
    assert requeue.call_args.kwargs["args"] == [str(monitor.pk), 3]
    assert requeue.call_args.kwargs["countdown"] == 45


@pytest.mark.django_db
def test_third_failure_writes_one_check_and_increments(monitor):
    with patch("apps.monitors.checker.run_check", return_value=DOWN), \
         patch("apps.monitors.tasks.check_single_monitor.apply_async") as requeue, \
         patch("apps.monitors.tasks.notify_status_change"):
        check_single_monitor(str(monitor.pk), attempt=3)

    assert MonitorCheck.objects.filter(monitor=monitor, status="down").count() == 1
    monitor.refresh_from_db()
    assert monitor.consecutive_failures == 1
    assert monitor.status == "down"
    requeue.assert_not_called()


@pytest.mark.django_db
def test_a_confirmation_sequence_records_exactly_one_check(monitor):
    """Three requests, one data point. The sequence must not triple-count."""
    with patch("apps.monitors.checker.run_check", return_value=DOWN), \
         patch("apps.monitors.tasks.check_single_monitor.apply_async"), \
         patch("apps.monitors.tasks.notify_status_change"):
        check_single_monitor(str(monitor.pk), attempt=1)
        check_single_monitor(str(monitor.pk), attempt=2)
        check_single_monitor(str(monitor.pk), attempt=3)

    assert MonitorCheck.objects.filter(monitor=monitor).count() == 1


@pytest.mark.django_db
def test_recovery_on_attempt_two_ends_sequence_and_writes_up(monitor):
    with patch("apps.monitors.checker.run_check", return_value=UP), \
         patch("apps.monitors.tasks.check_single_monitor.apply_async") as requeue:
        check_single_monitor(str(monitor.pk), attempt=2)

    assert MonitorCheck.objects.filter(monitor=monitor, status="up").count() == 1
    monitor.refresh_from_db()
    assert monitor.status == "up"
    requeue.assert_not_called()


@pytest.mark.django_db
def test_blocked_result_short_circuits_confirmation(monitor):
    """A block is a definite answer about us, not a suspicion about the site."""
    with patch("apps.monitors.checker.run_check", return_value=BLOCKED), \
         patch("apps.monitors.tasks.check_single_monitor.apply_async") as requeue:
        check_single_monitor(str(monitor.pk), attempt=1)

    assert MonitorCheck.objects.filter(monitor=monitor, status="blocked").count() == 1
    monitor.refresh_from_db()
    assert monitor.status == "blocked"
    assert monitor.consecutive_failures == 0
    assert monitor.consecutive_blocks == 1
    requeue.assert_not_called()


@pytest.mark.django_db
def test_attempt_number_is_passed_to_the_checker(monitor):
    with patch("apps.monitors.checker.run_check", return_value=UP) as run, \
         patch("apps.monitors.tasks.check_single_monitor.apply_async"):
        check_single_monitor(str(monitor.pk), attempt=3)

    assert run.call_args.kwargs["attempt"] == 3


@pytest.mark.django_db
def test_recovery_clears_consecutive_blocks(monitor):
    Monitor.objects.filter(pk=monitor.pk).update(consecutive_blocks=4, status="blocked")

    with patch("apps.monitors.checker.run_check", return_value=UP), \
         patch("apps.monitors.tasks.check_single_monitor.apply_async"):
        check_single_monitor(str(monitor.pk))

    monitor.refresh_from_db()
    assert monitor.consecutive_blocks == 0
