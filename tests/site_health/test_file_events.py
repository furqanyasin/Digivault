import pytest
from django.utils import timezone

from apps.site_health.file_events import record_file_changes
from apps.site_health.models import FileManifest, SiteEvent
from apps.websites.models import Website


@pytest.fixture
def website(db, team):
    return Website.objects.create(team=team, name="Acme", domain="acme.test")


def manifest(website, walk_id, entries, complete=True, minutes_ago=0):
    from django.utils.timezone import timedelta

    row = FileManifest.objects.create(
        website=website,
        walk_id=walk_id,
        entries=entries,
        is_complete=complete,
        walked_at=timezone.now() - timedelta(minutes=minutes_ago),
    )
    return row


def test_first_complete_walk_records_no_events(website):
    current = manifest(website, "w1", {"plugins/a/x.php": "h1"})
    assert record_file_changes(website, current) == 0
    assert SiteEvent.objects.filter(website=website).count() == 0


def test_modified_file_records_an_event(website):
    manifest(website, "w1", {"plugins/a/x.php": "h1"}, minutes_ago=60)
    current = manifest(website, "w2", {"plugins/a/x.php": "h2"})
    assert record_file_changes(website, current) == 1
    event = SiteEvent.objects.get(website=website)
    assert event.category == SiteEvent.Category.FILES
    assert event.source == SiteEvent.Source.PASSIVE
    assert "plugins/a/x.php" in event.summary


def test_an_incomplete_manifest_is_never_diffed(website):
    manifest(website, "w1", {"plugins/a/x.php": "h1"}, minutes_ago=60)
    partial = manifest(website, "w2", {}, complete=False)
    assert record_file_changes(website, partial) == 0
    assert SiteEvent.objects.count() == 0


def test_executable_dropped_into_uploads_is_critical(website):
    manifest(website, "w1", {"plugins/a/x.php": "h1"}, minutes_ago=60)
    current = manifest(
        website, "w2", {"plugins/a/x.php": "h1", "uploads/2026/09/shell.php": "h9"}
    )
    record_file_changes(website, current)
    event = SiteEvent.objects.get(website=website)
    assert event.severity == SiteEvent.Severity.CRITICAL


def test_an_ordinary_plugin_file_change_is_only_a_warning(website):
    manifest(website, "w1", {"plugins/a/x.php": "h1"}, minutes_ago=60)
    current = manifest(website, "w2", {"plugins/a/x.php": "h2"})
    record_file_changes(website, current)
    assert SiteEvent.objects.get(website=website).severity == SiteEvent.Severity.WARNING


def test_rerunning_against_the_same_walk_does_not_duplicate(website):
    manifest(website, "w1", {"plugins/a/x.php": "h1"}, minutes_ago=60)
    current = manifest(website, "w2", {"plugins/a/x.php": "h2"})
    record_file_changes(website, current)
    record_file_changes(website, current)
    assert SiteEvent.objects.filter(website=website).count() == 1


def test_superseded_manifests_are_pruned(website):
    """Manifests are large. Keeping every historical walk would grow without
    bound for no benefit — only the previous one is ever compared against."""
    for i in range(5):
        manifest(website, f"w{i}", {"plugins/a/x.php": f"h{i}"}, minutes_ago=100 - i)
    current = manifest(website, "w9", {"plugins/a/x.php": "h9"})
    record_file_changes(website, current)
    remaining = set(
        FileManifest.objects.filter(website=website).values_list("walk_id", flat=True)
    )
    assert remaining == {"w9", "w4"}


def test_the_same_file_changing_again_later_is_a_new_event(website):
    """Dedup must be scoped to the walk. A file modified in one walk and
    modified again in a later one is two findings, not one — and swallowing the
    second is exactly how a re-infection goes unnoticed."""
    manifest(website, "w1", {"plugins/a/x.php": "h1"}, minutes_ago=180)
    second = manifest(website, "w2", {"plugins/a/x.php": "h2"}, minutes_ago=120)
    assert record_file_changes(website, second) == 1

    third = manifest(website, "w3", {"plugins/a/x.php": "h3"}, minutes_ago=60)
    assert record_file_changes(website, third) == 1
    assert SiteEvent.objects.filter(website=website).count() == 2
