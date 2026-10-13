"""Partitioning converts the purge-by-age tables in place, and nothing notices.

`manage.py partition_table` turns scripts_scriptsnapshot / monitors_monitorcheck
into monthly range partitions without copying a row: the old table becomes the
first partition. What must hold afterwards is that the application cannot tell
— every row still there, the ORM reading, writing, updating, deleting and
cascading as before, index names unchanged for later migrations — while the
purges drop whole months instead of deleting rows.

These run inside the test transaction (`concurrently=False`), and Postgres DDL
is transactional, so each conversion is rolled back with the test.
"""

from datetime import timedelta

import pytest
from django.core.management import call_command
from django.db import connection
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.common import partitions
from apps.common.tasks import maintain_partitions
from apps.monitors.models import Monitor, MonitorCheck
from apps.scripts.models import ScriptSnapshot
from apps.scripts.tasks import purge_old_snapshots
from apps.websites.models import Website

pytestmark = pytest.mark.django_db

SNAPSHOTS = "scripts_scriptsnapshot"
CHECKS = "monitors_monitorcheck"


@pytest.fixture
def website(db):
    owner = User.objects.create_user(email="part_o@test.com", password="Pass123!")
    team = TeamService.create(name="Part Agency", owner=owner)
    return Website.objects.create(team=team, name="Part Site", domain="part.io")


def _snapshot(website, days_ago=0, **kw):
    return ScriptSnapshot.objects.create(
        website=website, page_url="https://part.io/", scripts_data=[],
        captured_at=timezone.now() - timedelta(days=days_ago), **kw,
    )


def _index_names(table):
    with connection.cursor() as cur:
        cur.execute("SELECT indexname FROM pg_indexes WHERE tablename = %s", [table])
        return {row[0] for row in cur.fetchall()}


# ── Before conversion: everything is a no-op ───────────────────────────────


def test_unconverted_tables_are_left_alone(website):
    _snapshot(website, days_ago=100)
    assert not partitions.is_partitioned(SNAPSHOTS)
    assert partitions.drop_partitions_before(SNAPSHOTS, timezone.now()) == []
    assert partitions.ensure_future_partitions(SNAPSHOTS) == []
    assert maintain_partitions() == {}


def test_dry_run_changes_nothing(website, capsys):
    _snapshot(website)
    call_command("partition_table", SNAPSHOTS, "--dry-run")
    assert "dry run: nothing changed" in capsys.readouterr().out
    assert not partitions.is_partitioned(SNAPSHOTS)


# ── Conversion ─────────────────────────────────────────────────────────────


def test_conversion_keeps_every_row_and_every_index_name(website):
    old = _snapshot(website, days_ago=100)
    mid = _snapshot(website, days_ago=10)
    new = _snapshot(website)
    names_before = _index_names(SNAPSHOTS)

    result = partitions.convert(SNAPSHOTS, concurrently=False)

    assert partitions.is_partitioned(SNAPSHOTS)
    assert set(ScriptSnapshot.objects.values_list("pk", flat=True)) == {old.pk, mid.pk, new.pk}
    # Later Django migrations address indexes by name; the parent keeps them.
    assert names_before - {f"{SNAPSHOTS}_pkey"} <= _index_names(SNAPSHOTS)
    parts = partitions.partitions(SNAPSHOTS)
    legacy = next(p for p in parts if p.name == f"{SNAPSHOTS}_legacy")
    assert legacy.lower is None and legacy.upper == result["cutoff"]
    assert any(p.is_default for p in parts)
    assert len(result["created"]) >= 3  # months ahead of the cutoff


def test_attaching_reuses_the_existing_indexes_instead_of_building_new_ones(website):
    # On a 20GB table an index build inside the switch's exclusive lock would
    # stall ingest for minutes. Matching indexes are adopted, not rebuilt: if
    # any had been rebuilt, the legacy table would carry both its renamed
    # original and a fresh copy.
    _snapshot(website)
    partitions.convert(SNAPSHOTS, concurrently=False)
    assert len(_index_names(f"{SNAPSHOTS}_legacy")) == len(_index_names(SNAPSHOTS))


def test_the_orm_works_unchanged_on_a_converted_table(website):
    partitions.convert(SNAPSHOTS, concurrently=False)
    cutoff = next(p.upper for p in partitions.partitions(SNAPSHOTS) if p.name.endswith("_legacy"))

    now_row = _snapshot(website)                                   # legacy partition
    month_row = _snapshot(website, days_ago=-((cutoff - timezone.now()).days + 5))  # a month partition
    far_row = _snapshot(website, days_ago=-3650)                   # beyond every month: DEFAULT

    assert ScriptSnapshot.objects.get(pk=month_row.pk).captured_at == month_row.captured_at
    # An update that moves a row into another partition.
    ScriptSnapshot.objects.filter(pk=now_row.pk).update(captured_at=month_row.captured_at)
    assert ScriptSnapshot.objects.get(pk=now_row.pk).captured_at == month_row.captured_at
    ScriptSnapshot.objects.filter(pk=far_row.pk).delete()
    assert not ScriptSnapshot.objects.filter(pk=far_row.pk).exists()
    # Django's cascade from Website still reaches every partition.
    website.delete()
    assert ScriptSnapshot.objects.count() == 0


def test_converting_twice_is_refused(website):
    partitions.convert(SNAPSHOTS, concurrently=False)
    with pytest.raises(ValueError, match="already partitioned"):
        partitions.convert(SNAPSHOTS, concurrently=False)


def test_monitor_checks_convert_too(website):
    monitor = Monitor.objects.filter(website=website).first() or Monitor.objects.create(
        team=website.team, name="m", url="https://part.io"
    )
    check = MonitorCheck.objects.create(monitor=monitor, status="up")
    partitions.convert(CHECKS, concurrently=False)
    assert partitions.is_partitioned(CHECKS)
    assert MonitorCheck.objects.filter(pk=check.pk).exists()
    monitor.delete()  # cascades into the partitions
    assert not MonitorCheck.objects.filter(pk=check.pk).exists()


# ── Purging drops whole months ─────────────────────────────────────────────


def test_whole_months_past_the_cutoff_are_dropped(website):
    partitions.convert(SNAPSHOTS, concurrently=False)
    months = [p for p in partitions.partitions(SNAPSHOTS) if not p.is_default and p.lower]
    first, second = months[0], months[1]
    in_first = _snapshot(website, days_ago=-((first.lower - timezone.now()).days + 1))
    in_second = _snapshot(website, days_ago=-((second.lower - timezone.now()).days + 1))

    dropped = partitions.drop_partitions_before(SNAPSHOTS, first.upper)

    assert set(dropped) == {f"{SNAPSHOTS}_legacy", first.name}
    assert not ScriptSnapshot.objects.filter(pk=in_first.pk).exists()
    assert ScriptSnapshot.objects.filter(pk=in_second.pk).exists()


def test_purge_still_removes_old_rows_from_a_straddling_partition(website):
    old = _snapshot(website, days_ago=100)
    recent = _snapshot(website, days_ago=5)
    partitions.convert(SNAPSHOTS, concurrently=False)

    purge_old_snapshots()

    # The legacy partition holds this month too, so it is not dropped; its
    # 100-day-old row goes through the row-level delete as before.
    assert partitions.is_partitioned(SNAPSHOTS)
    assert not ScriptSnapshot.objects.filter(pk=old.pk).exists()
    assert ScriptSnapshot.objects.filter(pk=recent.pk).exists()


# ── Maintenance ────────────────────────────────────────────────────────────


def test_maintenance_tops_up_future_months(website):
    partitions.convert(SNAPSHOTS, concurrently=False, months_ahead=0)
    before = {p.name for p in partitions.partitions(SNAPSHOTS)}
    created = maintain_partitions()
    after = {p.name for p in partitions.partitions(SNAPSHOTS)}
    assert created.get(SNAPSHOTS) and set(created[SNAPSHOTS]) == after - before
    assert maintain_partitions() == {}  # idempotent


def test_rows_in_default_are_reported(website, caplog):
    partitions.convert(SNAPSHOTS, concurrently=False)
    _snapshot(website, days_ago=-3650)
    assert partitions.default_partition_rows(SNAPSHOTS) == 1


def test_a_rerun_after_an_interrupted_preparation_still_converts(website):
    # A killed CONCURRENTLY build leaves an invalid index; a failed run leaves
    # the check constraint. Running the command again must still work.
    _snapshot(website)
    with connection.cursor() as cur:
        cur.execute("SET CONSTRAINTS ALL IMMEDIATE")  # the row above has a pending FK check
        cur.execute(f'CREATE UNIQUE INDEX "{SNAPSHOTS}_partkey" ON "{SNAPSHOTS}" (id, captured_at)')
        cur.execute(f"UPDATE pg_index SET indisvalid = false WHERE indexrelid = '{SNAPSHOTS}_partkey'::regclass")
        cur.execute(f'ALTER TABLE "{SNAPSHOTS}" ADD CONSTRAINT "{SNAPSHOTS}_legacy_bound" CHECK (captured_at < now() + interval \'1 day\') NOT VALID')
    partitions.convert(SNAPSHOTS, concurrently=False)
    assert partitions.is_partitioned(SNAPSHOTS)
