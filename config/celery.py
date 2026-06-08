import logging
import os
import time

from celery import Celery
from celery.signals import task_failure, task_postrun, task_prerun

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

app = Celery("digivault_hub")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

logger = logging.getLogger("celery.task")
_task_started_at: dict[str, float] = {}


@task_prerun.connect
def _on_task_prerun(task_id=None, task=None, **kwargs):
    _task_started_at[task_id] = time.monotonic()


@task_postrun.connect
def _on_task_postrun(task_id=None, task=None, state=None, **kwargs):
    started = _task_started_at.pop(task_id, None)
    duration_ms = round((time.monotonic() - started) * 1000) if started else None
    logger.info(
        "task=%s id=%s state=%s duration_ms=%s",
        getattr(task, "name", "?"),
        task_id,
        state,
        duration_ms,
    )


@task_failure.connect
def _on_task_failure(task_id=None, exception=None, sender=None, **kwargs):
    logger.error(
        "task=%s id=%s FAILED: %s",
        getattr(sender, "name", "?"),
        task_id,
        exception,
    )
