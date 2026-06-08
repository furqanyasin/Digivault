"""Celery tasks for alert delivery."""

from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

from apps.alerts.delivery import get_backend
from apps.alerts.models import Notification

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    name="alerts.deliver_notification",
)
def deliver_notification(self, notification_id: str) -> None:
    """Deliver a single Notification via its configured channel backend."""
    try:
        notification = Notification.objects.select_related(
            "website", "script_change", "rule", "team"
        ).get(pk=notification_id)
    except Notification.DoesNotExist:
        return

    if notification.delivery_status == Notification.DeliveryStatus.SENT:
        return

    try:
        backend = get_backend(notification.channel)
        backend.send(notification)
        Notification.objects.filter(pk=notification_id).update(
            delivery_status=Notification.DeliveryStatus.SENT,
            delivered_at=timezone.now(),
        )
    except Exception as exc:
        logger.exception("deliver_notification failed for %s", notification_id)
        Notification.objects.filter(pk=notification_id).update(
            delivery_status=Notification.DeliveryStatus.FAILED,
            error_message=str(exc)[:500],
        )
        raise self.retry(exc=exc)


@shared_task(name="alerts.send_digest")
def send_digest(mode: str = "daily_digest") -> int:
    """Collect all pending digest notifications and batch-deliver them."""
    pending = Notification.objects.filter(
        delivery_status=Notification.DeliveryStatus.PENDING,
        rule__delivery_mode=mode,
    ).select_related("rule")

    count = 0
    for notification in pending:
        deliver_notification.delay(str(notification.pk))
        count += 1

    logger.info("send_digest(%s): queued %d deliveries", mode, count)
    return count


@shared_task(name="alerts.purge_old_notifications")
def purge_old_notifications(days: int = 90) -> int:
    """Delete non-pending Notification rows older than `days`. Chunked."""
    cutoff = timezone.now() - timezone.timedelta(days=days)
    total = 0
    chunk = 1000
    while True:
        ids = list(
            Notification.objects.filter(created_at__lt=cutoff)
            .exclude(delivery_status=Notification.DeliveryStatus.PENDING)
            .values_list("pk", flat=True)[:chunk]
        )
        if not ids:
            break
        deleted, _ = Notification.objects.filter(pk__in=ids).delete()
        total += deleted

    logger.info("alerts.purge_old_notifications: removed %d rows", total)
    return total
