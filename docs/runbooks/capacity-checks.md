# Runbook — Monthly capacity checks

Two infrastructure changes are deliberately **not built** yet because nothing
has shown they are needed. Each has a trigger. This runbook measures both. Run
it monthly, and after onboarding a large client.

Run on the server from the repo root. `C` means
`docker compose -f docker-compose.production.cloudpanel.yml`.

---

## 1. Ingest lock contention: should a page load's posts be batched?

Every ingest post locks its website's row while it diffs, and a pageview sends
six or more posts. If they queue behind each other, the fix is to buffer a page
load's posts and diff them once ("Phase 3": roughly 5× less ingest work, and a
large change to the detection pipeline). The task logs `ingest_lock` only when
a post waited more than 0.5 s for the lock or held it more than 2 s.

```bash
# How often, and for which sites, over the logs Docker still has:
$C logs --since 168h celery 2>/dev/null | grep -c "ingest_lock:"
$C logs --since 168h celery 2>/dev/null | grep "ingest_lock:" \
  | sed -E 's/.*site_id=([^ ]+).*/\1/' | sort | uniq -c | sort -rn | head

# Is the ingest queue keeping up right now?
$C exec redis redis-cli -n 2 llen ingest
```

**Trigger for Phase 3:** more than about 100 `ingest_lock` lines a day, or any
day the heartbeat was withheld for an `ingest=` backlog. Below that, batching
would add risk to the detection rules for no measurable gain.

### Turning batching on (Phase 3 is built, and off by default)

Batching is switched on per site. A site's posts are then buffered per page for
15 s and diffed once, instead of once per post (`apps/scripts/ingest_batch.py`).
Start with the sites the `ingest_lock` lines name:

```bash
# .env.production: comma-separated site_ids from the ingest_lock lines, or * for all
INGEST_BATCH_SITES=AbC123...,XyZ789...
./deploy.sh
```

A week later, compare those sites' `ingest_lock` count with the week before.
Check their change log too: it should read the same, with no new add/remove
pairs.

**Rollback:** remove the site_ids and `./deploy.sh`. Anything still buffered is
flushed anyway, because flushes and the 5-minute sweeper don't check the
switch.

## 2. Table growth: should snapshots be partitioned?

The weekly purges delete old rows in batches. On a very large table that leaves
bloat behind and competes with live traffic. Monthly partitions turn the purge
into an instant `DROP` ("Phase 4").

```bash
$C exec db psql -U digivault -c "
  select relname, pg_size_pretty(pg_total_relation_size(relid)) as size
  from pg_statio_user_tables order by pg_total_relation_size(relid) desc limit 8;"

$C exec db psql -U digivault -c "
  select date(captured_at) as day, count(*) from scripts_scriptsnapshot
  where captured_at > now() - interval '7 days' group by 1 order by 1;"
```

**Trigger for Phase 4:** `scripts_scriptsnapshot` or `monitors_monitorcheck`
past about 20 GB, or the Sunday purge (`purge_old_snapshots`, `purge_old_checks`)
running longer than an hour:
`$C logs --since 168h celery-slow | grep -E "purge_old_snapshots|purge_old_checks"`.

### Converting a table (Phase 4 is built; nothing changes until you run this)

`manage.py partition_table` converts one table in place. **It copies no data:**
the existing table becomes the first partition (`apps/common/partitions.py`).
It is a command, not a migration, so no deploy can trigger it by accident.

```bash
# 1. See what it would do: size, row count and the cutoff date.
$C exec api python manage.py partition_table scripts_scriptsnapshot --dry-run

# 2. Convert. Run it at a quiet hour. The first step builds an index
#    CONCURRENTLY: minutes on a large table, with writes carrying on. The
#    switch itself holds an exclusive lock for about a second.
$C exec api python manage.py partition_table scripts_scriptsnapshot

# 3. Same for monitor checks, if that table also crossed the threshold.
$C exec api python manage.py partition_table monitors_monitorcheck
```

Afterwards:

- The weekly purges drop every partition that has fully aged out, then delete
  rows only from the month straddling the cutoff. The old table
  (`<table>_legacy`) is dropped whole once everything in it is past retention:
  up to 90 days for snapshots, 35 for checks.
- `common.maintain_partitions` (daily, 03:30) keeps three months of partitions
  ready. If it ever logs `rows in <table>_default`, it fell behind and rows
  landed in the catch-all partition. They are still readable, but a month
  can't be created over them until they're moved out.
- Django still treats `id` as the primary key. The database key is now
  `(id, <column>)`, and ids remain unique on their own because they are UUIDs.
  Later migrations that add columns or indexes work on the partitioned table as
  usual.

If the command fails partway, nothing is half-converted: the switch is one
transaction and rolls back whole, and the online preparation (the
`<table>_partkey` index and `<table>_legacy_bound` check) is rebuilt if it was
left behind. Run the command again.

## 3. Redis headroom

```bash
$C exec redis redis-cli info memory | grep -E "used_memory_human|maxmemory_human"
$C exec redis redis-cli -n 3 dbsize    # result backend: should stay ~0 since task results are no longer stored
```

**Trigger:** `used_memory` above 70% of `maxmemory`. Raise `REDIS_MAXMEMORY`
in `.env` (compose reads it) before Redis starts refusing writes. Under
`noeviction`, a full Redis stops the broker.
