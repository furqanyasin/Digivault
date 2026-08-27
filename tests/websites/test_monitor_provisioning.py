"""Auto-provisioned monitors must inherit the model's retry budget."""

import pytest

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.monitors.models import Monitor
from apps.websites.models import Website


@pytest.fixture
def team(db):
    owner = User.objects.create_user(email="owner@prov.com", password="SecurePass1!")
    return TeamService.create(name="Prov Team", owner=owner)


@pytest.mark.django_db
def test_auto_created_monitor_uses_the_model_retry_default(team):
    """The signal used to override retry_count down to 1.

    The model's default is 3 for a reason: one 403 or one TCP reset should not
    page anyone. Provisioning silently undid that for every website ever added
    through the UI, which is every website.
    """
    website = Website.objects.create(team=team, name="Prov", domain="prov.test")
    monitor = Monitor.objects.filter(website=website).first()

    assert monitor is not None
    assert monitor.retry_count == Monitor._meta.get_field("retry_count").default
    assert monitor.retry_count == 3
