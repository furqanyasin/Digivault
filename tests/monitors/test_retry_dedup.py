import pytest
from unittest.mock import patch

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.monitors.models import Monitor


@pytest.fixture
def owner(db):
    return User.objects.create_user(email="owner@montest.com", password="SecurePass1!")


@pytest.fixture
def team(owner):
    return TeamService.create(name="Monitor Team", owner=owner)


@pytest.fixture
def monitor(team):
    return Monitor.objects.create(
        team=team,
        name="Test Site",
        url="https://example.com",
        monitor_type="http",
        retry_count=3,
        status="up",
        is_alerting=False,
        consecutive_failures=0,
    )


def run_task_with_result(monitor_id, result_status):
    from apps.monitors.tasks import check_single_monitor

    fake_result = {
        "status": result_status,
        "response_time_ms": 200 if result_status == "up" else None,
        "status_code": 200 if result_status == "up" else None,
        "error_message": "" if result_status == "up" else "Connection refused",
    }
    with patch("apps.monitors.checker.run_check", return_value=fake_result):
        with patch("apps.monitors.tasks.notify_status_change") as mock_notify:
            check_single_monitor(str(monitor_id))
            return mock_notify


@pytest.mark.django_db
def test_first_failure_does_not_alert(monitor):
    mock_notify = run_task_with_result(monitor.pk, "down")
    monitor.refresh_from_db()
    assert monitor.consecutive_failures == 1
    assert monitor.is_alerting is False
    mock_notify.assert_not_called()


@pytest.mark.django_db
def test_second_failure_does_not_alert(monitor):
    Monitor.objects.filter(pk=monitor.pk).update(consecutive_failures=1)
    mock_notify = run_task_with_result(monitor.pk, "down")
    monitor.refresh_from_db()
    assert monitor.consecutive_failures == 2
    assert monitor.is_alerting is False
    mock_notify.assert_not_called()


@pytest.mark.django_db
def test_third_failure_fires_alert(monitor):
    Monitor.objects.filter(pk=monitor.pk).update(consecutive_failures=2)
    mock_notify = run_task_with_result(monitor.pk, "down")
    monitor.refresh_from_db()
    assert monitor.consecutive_failures == 3
    assert monitor.is_alerting is True
    mock_notify.assert_called_once()
    args = mock_notify.call_args[0]
    assert args[1] == "up"
    assert args[2] == "down"


@pytest.mark.django_db
def test_subsequent_failure_does_not_re_alert(monitor):
    Monitor.objects.filter(pk=monitor.pk).update(
        consecutive_failures=3, is_alerting=True, status="down"
    )
    mock_notify = run_task_with_result(monitor.pk, "down")
    monitor.refresh_from_db()
    assert monitor.consecutive_failures == 4
    assert monitor.is_alerting is True
    mock_notify.assert_not_called()


@pytest.mark.django_db
def test_recovery_fires_alert_and_resets(monitor):
    Monitor.objects.filter(pk=monitor.pk).update(
        consecutive_failures=3, is_alerting=True, status="down"
    )
    mock_notify = run_task_with_result(monitor.pk, "up")
    monitor.refresh_from_db()
    assert monitor.consecutive_failures == 0
    assert monitor.is_alerting is False
    mock_notify.assert_called_once()
    args = mock_notify.call_args[0]
    assert args[1] == "down"
    assert args[2] == "up"


@pytest.mark.django_db
def test_recovery_without_alert_no_notification(monitor):
    Monitor.objects.filter(pk=monitor.pk).update(
        consecutive_failures=1, is_alerting=False, status="down"
    )
    mock_notify = run_task_with_result(monitor.pk, "up")
    monitor.refresh_from_db()
    assert monitor.consecutive_failures == 0
    assert monitor.is_alerting is False
    mock_notify.assert_not_called()
