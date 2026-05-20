import logging

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(name="audit.purge_old_logs")
def purge_old_logs() -> int:
    """Delete ActivityLog records older than 90 days. Chunked to avoid long transactions."""
    from django.utils.timezone import timedelta
    from apps.audit.models import ActivityLog

    cutoff = timezone.now() - timedelta(days=90)
    total = 0
    chunk = 500
    while True:
        ids = list(ActivityLog.objects.filter(created_at__lt=cutoff).values_list("pk", flat=True)[:chunk])
        if not ids:
            break
        deleted, _ = ActivityLog.objects.filter(pk__in=ids).delete()
        total += deleted

    logger.info("audit.purge_old_logs: removed %d records", total)
    return total
