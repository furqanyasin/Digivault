from django.db import models
from django.utils import timezone

from apps.common.models import BaseModel


class ClickUpTaskLink(BaseModel):
    """Links a Digivault issue to the ClickUp task that reports it.

    `subject` is a stable key for the *issue*, not the event — e.g.
    "monitor:<uuid>:down". A monitor that stays down keeps firing, and without
    this link every repeat would open another task for the same outage. While a
    link is open, further reports comment on the task it points at; closing the
    link lets the next genuine occurrence open a fresh one.
    """

    team = models.ForeignKey(
        "accounts.Team", on_delete=models.CASCADE, related_name="clickup_task_links"
    )
    subject = models.CharField(max_length=255, db_index=True)
    task_id = models.CharField(max_length=64)
    task_url = models.TextField(blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # Only one OPEN link per subject. Closed ones stay as history, so a
            # plain unique_together would block the second outage.
            models.UniqueConstraint(
                fields=["team", "subject"],
                condition=models.Q(closed_at__isnull=True),
                name="uniq_open_clickup_link_per_subject",
            )
        ]
        indexes = [models.Index(fields=["team", "subject", "closed_at"])]

    def __str__(self) -> str:
        return f"{self.subject} -> {self.task_id}"

    def close(self) -> None:
        self.closed_at = timezone.now()
        self.save(update_fields=["closed_at", "updated_at"])


class ClickUpMemberLink(BaseModel):
    """Maps a Digivault user to their ClickUp user id, per team.

    Email is the only join key ClickUp exposes, and agency people routinely have
    a different address in each system — so this is a stored mapping that can be
    corrected by hand, not a lookup done fresh each time.
    """

    team = models.ForeignKey(
        "accounts.Team", on_delete=models.CASCADE, related_name="clickup_member_links"
    )
    user = models.ForeignKey(
        "accounts.User", on_delete=models.CASCADE, related_name="clickup_member_links"
    )
    clickup_user_id = models.CharField(max_length=32)
    clickup_username = models.CharField(max_length=120, blank=True, default="")

    class Meta:
        ordering = ["-created_at"]
        unique_together = [("team", "user")]
        indexes = [models.Index(fields=["team", "user"])]

    def __str__(self) -> str:
        return f"{self.user_id} -> clickup:{self.clickup_user_id}"
