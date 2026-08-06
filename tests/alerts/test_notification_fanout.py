"""One change must produce one notification per rule — no matter who else is ingesting.

The snippet posts several times per page load, and every post becomes its own
Celery task, so two ingests for the same website overlapping in time is the
normal case rather than an edge case. The dispatch step used to select "every
ScriptChange for this website created since my snapshot was captured", which is
not the same set as "the changes I just created": a task that committed a change
while this one was still working got its change dispatched a second time here,
and a third time by the next overlapping task.

`_record_wp_asset_events` is patched below purely as a seam — it runs after the
snapshot row exists and before the dispatch loop, which is exactly the window a
concurrent ingest commits in.
"""

from unittest.mock import patch

import pytest

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.alerts.models import AlertRule, Notification
from apps.scripts.models import ScriptChange
from apps.scripts.tasks import process_ingest_payload
from apps.websites.models import Website

pytestmark = pytest.mark.django_db

GTM = "https://www.googletagmanager.com/gtm.js?id=GTM-FANOUT"


@pytest.fixture
def website(db):
    owner = User.objects.create_user(email="fanout@test.com", password="Pass123!")
    team = TeamService.create(name="Fanout Agency", owner=owner)
    site = Website.objects.create(team=team, name="Fanout Site", domain="fanout.io")
    AlertRule.objects.create(
        team=team, name="everything", channel="in_app", min_severity="low"
    )
    return site


def _script(src):
    return {
        "src": src, "location": "head", "is_async": True,
        "is_defer": False, "is_inline": False, "inline_hash": "",
        "wp_plugin": "", "wp_post_id": None,
    }


def _ingest(website, page_url, scripts):
    process_ingest_payload(
        str(website.site_id),
        {"page_url": page_url, "scripts": scripts, "forms": []},
    )


def test_one_new_script_notifies_once(website):
    _ingest(website, "https://fanout.io/a", [_script(GTM)])

    assert ScriptChange.objects.filter(website=website).count() == 1
    assert Notification.objects.filter(website=website).count() == 1


def test_a_concurrent_ingests_change_is_not_re_dispatched(website):
    """The other task already notified for its own change. This one must not repeat it."""
    concurrent: dict = {}

    def commit_a_change_mid_task(site, previous, current):
        # Stands in for another ingest task committing while this one runs.
        concurrent["change"] = ScriptChange.objects.create(
            website=site,
            change_type="added",
            severity="high",
            description="Unknown script detected: https://other.example/tag.js",
        )

    with patch(
        "apps.scripts.tasks._record_wp_asset_events",
        side_effect=commit_a_change_mid_task,
    ):
        _ingest(website, "https://fanout.io/a", [_script(GTM)])

    # The neighbour's change gets no notification from this task's dispatch loop.
    assert Notification.objects.filter(script_change=concurrent["change"]).count() == 0
    # This task's own change is still notified exactly once.
    own = ScriptChange.objects.get(website=website, script__isnull=False)
    assert Notification.objects.filter(script_change=own).count() == 1


def test_a_suppressed_repeat_change_notifies_nobody_twice(website):
    """Dedupe skips creating the change; the dispatch step must skip it too."""
    _ingest(website, "https://fanout.io/a", [_script(GTM)])
    _ingest(website, "https://fanout.io/b", [_script(GTM)])
    _ingest(website, "https://fanout.io/c", [_script(GTM)])

    assert ScriptChange.objects.filter(website=website).count() == 1
    assert Notification.objects.filter(website=website).count() == 1
