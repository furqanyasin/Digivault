"""Merging Script rows that a widened volatile-param list turned into duplicates.

`merge_duplicate_scripts` shipped with the 0009 migration; these tests re-run it
against the identities the *current* normalizer produces, which is what migration
0016 does after gtag runtime params and filename content hashes became volatile.

The dangerous part is not the merge — it is what the merge throws away. A
reviewer's Approve/Block decision and the change history attached to a row must
survive, or cleaning up the list would quietly undo someone's work.
"""
import datetime

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.scripts.dedup import merge_duplicate_scripts
from apps.scripts.models import Script, ScriptChange
from apps.websites.models import Website

GTAG = "https://www.googletagmanager.com/gtag/js"


@pytest.fixture
def site(db):
    owner = User.objects.create_user(email="dedupe@x.io", password="Pass123!")
    team = TeamService.create(name="Dedupe Co", owner=owner)
    return Website.objects.create(team=team, name="Acme Agency", domain="acme-agency.com")


def _script(site, src_url, *, normalized=None, pages=None, review="pending", days_ago=0, active=True):
    """Create a Script with a stale normalized_url, as pre-fix rows have."""
    s = Script.objects.create(
        website=site,
        src_url=src_url,
        # Pre-fix rows stored the raw URL as identity, gtm= and all.
        normalized_url=normalized if normalized is not None else src_url,
        src_domain="www.googletagmanager.com",
        provider="google_tag_manager",
        seen_on_pages=pages or [],
        review_status=review,
        is_active=active,
    )
    when = timezone.now() - datetime.timedelta(days=days_ago)
    Script.objects.filter(pk=s.pk).update(first_seen_at=when, last_seen_at=when)
    s.refresh_from_db()
    return s


def _merge():
    """Returns the number of rows deleted."""
    return merge_duplicate_scripts(Script, ScriptChange)


def test_gtm_republishes_collapse_into_one_row(site):
    _script(site, f"{GTAG}?id=G-ABC&cx=c&gtm=4e6840", days_ago=5)
    _script(site, f"{GTAG}?id=G-ABC&cx=c&gtm=45He51r0", days_ago=1)

    assert _merge() == 1
    remaining = Script.objects.filter(website=site)
    assert remaining.count() == 1
    assert remaining.first().normalized_url == f"{GTAG}?id=G-ABC"


def test_hotjar_module_releases_collapse_into_one_row(site):
    """The hash is in the filename, so nothing about the query params helps."""
    _script(site, "https://script.hotjar.com/modules.75bf3488a101739acfe9.js", days_ago=5)
    _script(site, "https://script.hotjar.com/modules.0f1e2d3c4b5a69788796.js", days_ago=1)

    assert _merge() == 1
    assert (
        Script.objects.filter(website=site).get().normalized_url
        == "https://script.hotjar.com/modules.js"
    )


def test_the_hotjar_container_stays_separate_from_its_module_bundle(site):
    """Two real Hotjar files — the account script and the module bundle."""
    _script(site, "https://static.hotjar.com/c/hotjar-3065386.js?sv=6")
    _script(site, "https://script.hotjar.com/modules.75bf3488a101739acfe9.js")

    assert _merge() == 0
    assert Script.objects.filter(website=site).count() == 2


def test_two_different_containers_are_left_alone(site):
    """Different GTM containers are different scripts, not duplicates."""
    _script(site, "https://www.googletagmanager.com/gtm.js?id=GTM-N32TK6DJ")
    _script(site, "https://www.googletagmanager.com/gtm.js?id=GTM-NDF77KHJ")

    assert _merge() == 0
    assert Script.objects.filter(website=site).count() == 2


def test_the_oldest_row_survives_so_first_seen_keeps_meaning(site):
    old = _script(site, f"{GTAG}?id=G-ABC&gtm=aaa", days_ago=30)
    _script(site, f"{GTAG}?id=G-ABC&gtm=bbb", days_ago=1)

    _merge()

    assert Script.objects.filter(website=site).get().pk == old.pk


def test_pages_are_unioned_across_the_merged_rows(site):
    _script(site, f"{GTAG}?id=G-ABC&gtm=aaa", pages=["https://acme-agency.com/"], days_ago=5)
    _script(
        site, f"{GTAG}?id=G-ABC&gtm=bbb",
        pages=["https://acme-agency.com/", "https://acme-agency.com/open-positions"], days_ago=1,
    )

    _merge()

    pages = Script.objects.filter(website=site).get().seen_on_pages
    assert sorted(pages) == ["https://acme-agency.com/", "https://acme-agency.com/open-positions"]


def test_an_approval_survives_even_when_the_kept_row_was_pending(site):
    """The whole point of the list is the review decision — never drop it.

    The pending row is created first so it becomes the keeper; the approval has to
    be lifted off the row being deleted.
    """
    _script(site, f"{GTAG}?id=G-ABC&gtm=aaa", review="pending", days_ago=5)
    _script(site, f"{GTAG}?id=G-ABC&gtm=bbb", review="approved", days_ago=1)

    _merge()

    assert Script.objects.filter(website=site).get().review_status == "approved"


def test_a_block_survives_a_pending_duplicate(site):
    _script(site, f"{GTAG}?id=G-ABC&gtm=aaa", review="pending", days_ago=5)
    _script(site, f"{GTAG}?id=G-ABC&gtm=bbb", review="blocked", days_ago=1)

    _merge()

    assert Script.objects.filter(website=site).get().review_status == "blocked"


def test_approved_currently_wins_over_blocked(site):
    """Documents existing 0009 behaviour, which this change makes more reachable.

    _REVIEW_PRIORITY in apps/scripts/dedup.py ranks approved above blocked, so a
    row someone blocked loses to a row someone approved. Worth a second look —
    the protective reading would be the other way round — but flipping it is a
    behaviour change beyond de-duplication, and it would re-decide rows that
    migration 0009 already merged.
    """
    _script(site, f"{GTAG}?id=G-ABC&gtm=aaa", review="blocked", days_ago=5)
    _script(site, f"{GTAG}?id=G-ABC&gtm=bbb", review="approved", days_ago=1)

    _merge()

    assert Script.objects.filter(website=site).get().review_status == "approved"


def test_change_history_is_repointed_not_orphaned(site):
    survivor = _script(site, f"{GTAG}?id=G-ABC&gtm=aaa", days_ago=5)
    loser = _script(site, f"{GTAG}?id=G-ABC&gtm=bbb", days_ago=1)
    change = ScriptChange.objects.create(
        website=site, script=loser, change_type="added",
        description="gtag appeared",
    )

    _merge()

    change.refresh_from_db()
    assert change.script_id == survivor.pk


def test_the_freshest_raw_url_is_kept_for_display(site):
    _script(site, f"{GTAG}?id=G-ABC&gtm=old", days_ago=5)
    _script(site, f"{GTAG}?id=G-ABC&gtm=new", days_ago=1)

    _merge()

    assert Script.objects.filter(website=site).get().src_url == f"{GTAG}?id=G-ABC&gtm=new"


def test_a_blank_id_row_does_not_swallow_a_real_container(site):
    _script(site, "https://www.googletagmanager.com/gtm.js?id=")
    _script(site, "https://www.googletagmanager.com/gtm.js?id=GTM-N32TK6DJ")

    _merge()

    assert Script.objects.filter(website=site).count() == 2


def test_an_active_row_keeps_the_merged_script_active(site):
    _script(site, f"{GTAG}?id=G-ABC&gtm=aaa", active=False, days_ago=5)
    _script(site, f"{GTAG}?id=G-ABC&gtm=bbb", active=True, days_ago=1)

    _merge()

    assert Script.objects.filter(website=site).get().is_active is True


def test_running_it_twice_changes_nothing_the_second_time(site):
    """Migration 0016 re-runs the same merge 0009 already ran — it must be safe."""
    _script(site, f"{GTAG}?id=G-ABC&gtm=aaa", days_ago=5)
    _script(site, f"{GTAG}?id=G-ABC&gtm=bbb", days_ago=1)

    assert _merge() == 1
    assert _merge() == 0


def test_unrelated_scripts_are_untouched(site):
    _script(site, "https://cdn.example.com/a.js?ver=1.0")

    assert _merge() == 0
    assert Script.objects.filter(website=site).count() == 1


def test_the_same_url_on_two_websites_is_not_merged(site):
    """Identity is per website — two clients running the same tag are separate."""
    other = Website.objects.create(team=site.team, name="Other", domain="other.io")
    _script(site, f"{GTAG}?id=G-ABC&gtm=aaa")
    _script(other, f"{GTAG}?id=G-ABC&gtm=bbb")

    assert _merge() == 0
    assert Script.objects.count() == 2
