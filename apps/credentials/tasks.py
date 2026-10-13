import logging

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(name="credentials.purge_expired_shares")
def purge_expired_shares() -> int:
    """Delete temporary shares that expired more than a day ago.

    Housekeeping only: an expired share is already ignored by every access
    check (`CredentialShare.objects.active()`). The day's grace keeps a share
    that lapsed minutes ago visible in the share list's history while someone
    is still asking why they lost access.
    """
    from apps.credentials.models import CredentialShare

    cutoff = timezone.now() - timezone.timedelta(days=1)
    deleted, _ = CredentialShare.objects.filter(expires_at__lt=cutoff).delete()
    logger.info("credentials.purge_expired_shares: removed %d shares", deleted)
    return deleted
