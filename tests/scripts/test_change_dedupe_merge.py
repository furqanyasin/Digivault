"""Collapsing the duplicate ScriptChange rows that pre-normalization ingest left behind.

Before `normalize_script_url` learned about epoch path segments (0017) and dotted
version segments (0019), a HubSpot analytics tag or a Clarity recorder minted a
fresh Script row on every vendor release, and with it a fresh "Unknown script
detected" change. The site-wide dedupe in `process_ingest_payload` keys on the
Script row, so a new row meant a new change every time.

0017/0019 merged the Script rows and repointed the changes onto one keeper, which
is why the dashboard now shows the same script eight times over with eight
different raw URLs quoted in the description. The Script rows are fixed; the
change rows they minted were never cleaned up. `collapse_duplicate_changes` is
that cleanup, and it is what the runtime dedupe would have produced had the
normalizer known about those URLs at the time.
"""
import datetime

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.alerts.models import Notification
from apps.scripts.dedup import collapse_duplicate_changes
from apps.scripts.models import Script, ScriptChange
from apps.websites.models import Website

HS = "https://js.hs-analytics.net/analytics/46377927.js"


@pytest.fixture
def site(db):
    owner = User.objects.create_user(email="chdedupe@x.io", password="Pass123!")
    team = TeamService.create(name="Change Dedupe Co", owner=owner)
    return Website.objects.create(team=team, name="Digilatics", domain="digilatics.com")


@pytest.fixture
def script(site):
    return Script.objects.create(
        website=site,
        src_url="https://js.hs-analytics.net/analytics/1786015800000/46377927.js",
        normalized_url=HS,
        src_domain="js.hs-analytics.net",
        provider="unknown",
    )


def _change(site, *, script=None, change_type="added", description="dup",
            hours_ago=0, acked=False, severity="high"):
    c = ScriptChange.objects.create(
        website=site, script=script, change_type=change_type,
        severity=severity, description=description,
        acknowledged_at=timezone.now() if acked else None,
    )
    ScriptChange.objects.filter(pk=c.pk).update(
        created_at=timezone.now() - datetime.timedelta(hours=hours_ago)
    )
    c.refresh_from_db()
    return c


def _collapse():
    """Returns the number of rows deleted."""
    return collapse_duplicate_changes(ScriptChange, Notification)


def test_repeat_detections_of_one_script_collapse_to_one_row(site, script):
    """The eight HubSpot 'added' rows the dashboard is showing."""
    for hours in (14, 9, 6, 5, 2, 1):
        _change(site, script=script, description=f"Unknown script detected: ...{hours}", hours_ago=hours)

    assert _collapse() == 5
    assert ScriptChange.objects.filter(website=site).count() == 1


def test_the_newest_row_survives_so_the_description_matches_the_script(site, script):
    """Deliberately the opposite keeper rule to `merge_duplicate_scripts`.

    A Script row is an identity, so its oldest row carries the true first_seen.
    A change row is one observation, and its description quotes the raw URL seen
    at the time — keeping the oldest would pin the list to a URL the merged
    Script no longer displays, which is the contradiction that made the
    dashboard look broken in the first place.
    """
    _change(site, script=script, description="stale epoch URL", hours_ago=14)
    newest = _change(site, script=script, description="current epoch URL", hours_ago=1)

    _collapse()

    survivor = ScriptChange.objects.get(website=site)
    assert survivor.pk == newest.pk
    assert survivor.description == "current epoch URL"


def test_different_change_types_on_one_script_are_not_duplicates(site, script):
    _change(site, script=script, change_type="added")
    _change(site, script=script, change_type="removed")
    _change(site, script=script, change_type="url_changed")

    assert _collapse() == 0
    assert ScriptChange.objects.filter(website=site).count() == 3


def test_two_scripts_with_the_same_change_type_are_not_duplicates(site, script):
    other = Script.objects.create(
        website=site, src_url="https://js.hsadspixel.net/pixels.js",
        normalized_url="https://js.hsadspixel.net/pixels.js",
        src_domain="js.hsadspixel.net", provider="unknown",
    )
    _change(site, script=script, change_type="added")
    _change(site, script=other, change_type="added")

    assert _collapse() == 0


def test_an_acknowledged_change_is_history_and_is_left_alone(site, script):
    """Acknowledging is a record of someone acting. Never delete it."""
    acked = _change(site, script=script, hours_ago=20, acked=True)
    _change(site, script=script, hours_ago=2)
    _change(site, script=script, hours_ago=1)

    assert _collapse() == 1
    assert ScriptChange.objects.filter(pk=acked.pk).exists()
    assert ScriptChange.objects.filter(website=site).count() == 2


def test_open_duplicates_are_collapsed_against_existing_history(site, script):
    """A later cleanup can remove duplicates created after the first migration."""
    old = _change(site, script=script, hours_ago=3)
    newest = _change(site, script=script, hours_ago=1)

    assert _collapse() == 1
    assert ScriptChange.objects.filter(pk=newest.pk).exists()
    assert not ScriptChange.objects.filter(pk=old.pk).exists()


def test_scriptless_changes_fall_back_to_the_description(site):
    """Mirrors the runtime dedupe, which keys on description when there is no Script."""
    _change(site, description="Critical script removed: Google Tag Manager", hours_ago=5)
    _change(site, description="Critical script removed: Google Tag Manager", hours_ago=1)
    _change(site, description="Critical script removed: Meta Pixel", hours_ago=1)

    assert _collapse() == 1
    assert ScriptChange.objects.filter(website=site).count() == 2


def test_notifications_are_repointed_not_orphaned(site, script):
    loser = _change(site, script=script, hours_ago=5)
    _change(site, script=script, hours_ago=1)
    notif = Notification.objects.create(
        team=site.team, website=site, script_change=loser, channel="in_app"
    )

    _collapse()

    notif.refresh_from_db()
    survivor = ScriptChange.objects.get(website=site)
    assert notif.script_change_id == survivor.pk


def test_the_same_duplicate_on_two_websites_stays_separate(site, script):
    other = Website.objects.create(team=site.team, name="Other", domain="other.io")
    other_script = Script.objects.create(
        website=other, src_url=HS, normalized_url=HS,
        src_domain="js.hs-analytics.net", provider="unknown",
    )
    _change(site, script=script)
    _change(other, script=other_script)

    assert _collapse() == 0


def test_running_it_twice_changes_nothing_the_second_time(site, script):
    _change(site, script=script, hours_ago=5)
    _change(site, script=script, hours_ago=1)

    assert _collapse() == 1
    assert _collapse() == 0
