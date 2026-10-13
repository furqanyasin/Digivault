import uuid

from django.db import models


class BaseModel(models.Model):
    """Abstract base for every Stacks Monitor model.

    Provides UUID primary key, immutable created_at, and auto-updated updated_at.
    Never query this class directly — it is always subclassed.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ["-created_at"]
