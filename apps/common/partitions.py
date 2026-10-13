"""Monthly range partitions for the two append-only tables that only age out.

`scripts_scriptsnapshot` (90-day retention) and `monitors_monitorcheck` (35
days) are written constantly and purged by age. As plain tables the weekly
purge deletes old rows 500-1000 at a time: on a table of tens of gigabytes that
is hours of deletes, the space is not returned without a VACUUM FULL, and the
dead rows slow every scan until autovacuum catches up. Partitioned by month,
the purge drops whole months, `DROP TABLE`, instant and fully reclaimed.

**Nothing here runs until an operator converts a table** (`manage.py
partition_table`, docs/runbooks/capacity-checks.md). Before that,
`drop_partitions_before` and `ensure_future_partitions` are no-ops and the
purges behave exactly as they always did. Conversion is a command rather than a
migration on purpose: the api runs `migrate` on every start, and a structural
change to the largest table must be a decision someone makes, at a time they
choose, when the table is large enough to need it.

Conversion copies no data. The existing table becomes the first partition:

1. Online, before any lock: build a unique index on `(id, <column>)` — a
   partitioned table's primary key must include the partition column — and add
   a validated `CHECK (<column> < cutoff)`, where cutoff is the start of next
   month. With that constraint proven, Postgres can attach the table as a
   partition without scanning it.
2. One short transaction: rename the table to `<table>_legacy` (and its
   indexes, since index names are schema-wide), create the partitioned parent
   under the original name with the same columns, checks, foreign keys and
   index *names* (later Django migrations address indexes by name), and attach
   the legacy table for `MINVALUE .. cutoff`. Its indexes match the parent's,
   so none is rebuilt. Then add monthly partitions from the cutoff on, plus a
   DEFAULT partition as a safety net.

The legacy partition is dropped whole once everything in it has aged past
retention, like any other month.

Django is not told the primary key changed. It still treats `id` as the key,
which stays true: ids are UUIDs, unique on their own. Lookups, deletes and
cascades by `id` all work on the parent.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone as dt_timezone

from django.db import connection, transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

# The tables this applies to, and the column each is partitioned (and purged) on.
PARTITIONED_TABLES = {
    "scripts_scriptsnapshot": "captured_at",
    "monitors_monitorcheck": "checked_at",
}

DEFAULT_MONTHS_AHEAD = 3

_BOUND = re.compile(r"FOR VALUES FROM \((.+?)\) TO \((.+?)\)")


@dataclass(frozen=True)
class Partition:
    name: str
    lower: datetime | None  # None = MINVALUE
    upper: datetime | None  # None = MAXVALUE
    is_default: bool = False


def _q(name: str) -> str:
    return connection.ops.quote_name(name)


def _month_start(dt: datetime) -> datetime:
    dt = dt.astimezone(dt_timezone.utc)
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _next_month(dt: datetime) -> datetime:
    return (dt.replace(day=28) + timedelta(days=4)).replace(day=1)


def _literal(dt: datetime) -> str:
    # Our own computed datetimes, never user input; an ISO literal is unambiguous.
    return f"'{dt.astimezone(dt_timezone.utc).isoformat()}'::timestamptz"


def _parse_bound(text: str) -> datetime | None:
    text = text.strip()
    if text in ("MINVALUE", "MAXVALUE"):
        return None
    with connection.cursor() as cur:
        cur.execute(f"SELECT {text}::timestamptz")
        return cur.fetchone()[0]


def is_partitioned(table: str) -> bool:
    with connection.cursor() as cur:
        cur.execute(
            """
            SELECT 1 FROM pg_partitioned_table pt
            JOIN pg_class c ON c.oid = pt.partrelid
            WHERE c.relname = %s AND c.relnamespace = current_schema()::regnamespace
            """,
            [table],
        )
        return cur.fetchone() is not None


def partitions(table: str) -> list[Partition]:
    with connection.cursor() as cur:
        cur.execute(
            """
            SELECT child.relname, pg_get_expr(child.relpartbound, child.oid)
            FROM pg_inherits i
            JOIN pg_class parent ON parent.oid = i.inhparent
            JOIN pg_class child ON child.oid = i.inhrelid
            WHERE parent.relname = %s AND parent.relnamespace = current_schema()::regnamespace
            """,
            [table],
        )
        rows = cur.fetchall()
    out = []
    for name, bound in rows:
        if bound.strip() == "DEFAULT":
            out.append(Partition(name, None, None, is_default=True))
            continue
        m = _BOUND.search(bound)
        if not m:
            continue
        out.append(Partition(name, _parse_bound(m.group(1)), _parse_bound(m.group(2))))
    return sorted(out, key=lambda p: (p.is_default, p.lower or datetime.min.replace(tzinfo=dt_timezone.utc)))


def _create_month(table: str, column: str, start: datetime) -> str:
    end = _next_month(start)
    name = f"{table}_p{start:%Y%m}"
    with connection.cursor() as cur:
        cur.execute(
            f"CREATE TABLE {_q(name)} PARTITION OF {_q(table)} "
            f"FOR VALUES FROM ({_literal(start)}) TO ({_literal(end)})"
        )
    return name


def ensure_future_partitions(table: str, months_ahead: int = DEFAULT_MONTHS_AHEAD, now=None) -> list[str]:
    """Create monthly partitions through `months_ahead` months from now.

    No-op on a table that has not been converted. Rows outside every range land
    in the DEFAULT partition rather than failing the insert, but creating a
    month that overlaps rows already sitting in DEFAULT fails, so that is
    logged loudly: it means this maintenance did not run for months.
    """
    if not is_partitioned(table):
        return []
    column = PARTITIONED_TABLES[table]
    now = now or timezone.now()
    target = _month_start(now)
    for _ in range(months_ahead + 1):
        target = _next_month(target)
    ranged = [p for p in partitions(table) if not p.is_default]
    covered_to = max((p.upper for p in ranged if p.upper), default=_month_start(now))
    created = []
    month = covered_to
    while month < target:
        try:
            with transaction.atomic():
                created.append(_create_month(table, column, month))
        except Exception:
            logger.exception(
                "partitions: could not create %s for %s; rows for that month are "
                "probably sitting in the DEFAULT partition", table, month.date(),
            )
            break
        month = _next_month(month)
    return created


def drop_partitions_before(table: str, cutoff: datetime) -> list[str]:
    """Drop every partition whose rows are all older than `cutoff`.

    No-op on a table that has not been converted. A partition that straddles
    the cutoff is kept; the purge's row-level delete handles its old rows.
    """
    if not is_partitioned(table):
        return []
    dropped = []
    for p in partitions(table):
        if p.is_default or p.upper is None or p.upper > cutoff:
            continue
        with connection.cursor() as cur:
            cur.execute(f"DROP TABLE {_q(p.name)}")
        dropped.append(p.name)
    if dropped:
        logger.info("partitions: dropped %s from %s", ", ".join(dropped), table)
    return dropped


def default_partition_rows(table: str) -> int:
    """Rows in the DEFAULT partition, which should always be zero."""
    for p in partitions(table) if is_partitioned(table) else []:
        if p.is_default:
            with connection.cursor() as cur:
                cur.execute(f"SELECT count(*) FROM {_q(p.name)}")
                return cur.fetchone()[0]
    return 0


# ── Conversion ─────────────────────────────────────────────────────────────


def _one(sql: str, params=None):
    with connection.cursor() as cur:
        cur.execute(sql, params or [])
        row = cur.fetchone()
        return row[0] if row else None


def _all(sql: str, params=None):
    with connection.cursor() as cur:
        cur.execute(sql, params or [])
        return cur.fetchall()


def _exec(sql: str):
    with connection.cursor() as cur:
        cur.execute(sql)


def plan(table: str, now=None) -> dict:
    """What `convert` would do, without doing it."""
    if table not in PARTITIONED_TABLES:
        raise ValueError(f"{table} is not one of {sorted(PARTITIONED_TABLES)}")
    column = PARTITIONED_TABLES[table]
    now = now or timezone.now()
    newest = _one(f"SELECT max({_q(column)}) FROM {_q(table)}")
    cutoff = _next_month(_month_start(now))
    if newest and newest >= cutoff:
        cutoff = _next_month(_month_start(newest))
    referenced_by = _all(
        "SELECT conrelid::regclass::text FROM pg_constraint WHERE contype = 'f' AND confrelid = %s::regclass",
        [table],
    )
    return {
        "table": table,
        "column": column,
        "already_partitioned": is_partitioned(table),
        "rows": _one(f"SELECT count(*) FROM {_q(table)}"),
        "size": _one("SELECT pg_size_pretty(pg_total_relation_size(%s::regclass))", [table]),
        "cutoff": cutoff,
        "referenced_by": [r[0] for r in referenced_by],
    }


def convert(table: str, *, concurrently: bool = True, months_ahead: int = DEFAULT_MONTHS_AHEAD, now=None) -> dict:
    """Turn `table` into a monthly-partitioned table without copying its rows.

    `concurrently=False` builds the key index inside the caller's transaction:
    for tests, and for small tables. Production uses the default, which must
    run outside a transaction.
    """
    p = plan(table, now=now)
    if p["already_partitioned"]:
        raise ValueError(f"{table} is already partitioned")
    if p["referenced_by"]:
        raise ValueError(f"{table} is referenced by foreign keys from {p['referenced_by']}")
    column, cutoff = p["column"], p["cutoff"]
    legacy = f"{table}_legacy"
    key_index = f"{table}_partkey"[:63]
    bound = f"{table}_legacy_bound"[:63]

    if connection.in_atomic_block:
        # Rows written earlier in this transaction carry pending deferred FK
        # checks, and Postgres refuses ALTER TABLE while any are pending.
        # Only reachable with concurrently=False (tests, small tables).
        _exec("SET CONSTRAINTS ALL IMMEDIATE")

    # 1. Online preparation. Neither step blocks writes for long, and both are
    # safe to repeat after a failed run: an interrupted CONCURRENTLY build
    # leaves an *invalid* index behind, which IF NOT EXISTS would keep and the
    # switch would then fail to adopt, so it is dropped and rebuilt.
    concurrent = "CONCURRENTLY " if concurrently else ""
    valid = _one("SELECT indisvalid FROM pg_index WHERE indexrelid = to_regclass(%s)", [key_index])
    if valid is False:
        _exec(f"DROP INDEX {concurrent}{_q(key_index)}")
    _exec(f"CREATE UNIQUE INDEX {concurrent}IF NOT EXISTS {_q(key_index)} ON {_q(table)} (id, {_q(column)})")
    _exec(f"ALTER TABLE {_q(table)} DROP CONSTRAINT IF EXISTS {_q(bound)}")
    _exec(f"ALTER TABLE {_q(table)} ADD CONSTRAINT {_q(bound)} CHECK ({_q(column)} < {_literal(cutoff)}) NOT VALID")
    _exec(f"ALTER TABLE {_q(table)} VALIDATE CONSTRAINT {_q(bound)}")

    # 2. The switch: one short transaction.
    with transaction.atomic():
        _exec(f"LOCK TABLE {_q(table)} IN ACCESS EXCLUSIVE MODE")
        pk = _one("SELECT conname FROM pg_constraint WHERE contype = 'p' AND conrelid = %s::regclass", [table])
        checks = _all(
            "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE contype = 'c' AND conrelid = %s::regclass AND conname <> %s",
            [table, bound],
        )
        fks = _all(
            "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE contype = 'f' AND conrelid = %s::regclass",
            [table],
        )
        # Plain indexes only: the primary key and our key index are handled
        # explicitly, and no other unique index exists on these tables.
        indexes = _all(
            "SELECT i.relname, pg_get_indexdef(i.oid) FROM pg_index x "
            "JOIN pg_class i ON i.oid = x.indexrelid "
            "WHERE x.indrelid = %s::regclass AND NOT x.indisprimary AND NOT x.indisunique",
            [table],
        )

        _exec(f"ALTER TABLE {_q(table)} RENAME TO {_q(legacy)}")
        # A partition takes its parent's primary key and cannot keep its own,
        # so the single-column key goes and the (id, column) index built
        # online above becomes the key. USING INDEX adopts it: no rebuild.
        if pk:
            _exec(f"ALTER TABLE {_q(legacy)} DROP CONSTRAINT {_q(pk)}")
        _exec(
            f"ALTER TABLE {_q(legacy)} ADD CONSTRAINT {_q(('lg_' + (pk or table + '_pkey'))[:63])} "
            f"PRIMARY KEY USING INDEX {_q(key_index)}"
        )
        for name, _ in indexes:
            _exec(f"ALTER INDEX {_q(name)} RENAME TO {_q(('lg_' + name)[:63])}")

        _exec(
            f"CREATE TABLE {_q(table)} (LIKE {_q(legacy)} INCLUDING DEFAULTS INCLUDING GENERATED "
            f"INCLUDING STORAGE INCLUDING COMMENTS) PARTITION BY RANGE ({_q(column)})"
        )
        _exec(f"ALTER TABLE {_q(table)} ADD CONSTRAINT {_q(pk or table + '_pkey')} PRIMARY KEY (id, {_q(column)})")
        for name, definition in checks:
            _exec(f"ALTER TABLE {_q(table)} ADD CONSTRAINT {_q(name)} {definition}")
        for name, definition in fks:
            _exec(f"ALTER TABLE {_q(table)} ADD CONSTRAINT {_q(name)} {definition}")
        for name, definition in indexes:
            # pg_get_indexdef names the (now renamed) legacy index and table.
            on_parent = re.sub(r"^CREATE INDEX \S+ ON (ONLY )?\S+", f"CREATE INDEX {_q(name)} ON {_q(table)}", definition)
            _exec(on_parent)

        _exec(
            f"ALTER TABLE {_q(table)} ATTACH PARTITION {_q(legacy)} "
            f"FOR VALUES FROM (MINVALUE) TO ({_literal(cutoff)})"
        )
        _exec(f"CREATE TABLE {_q(table + '_default')} PARTITION OF {_q(table)} DEFAULT")
        created = ensure_future_partitions(table, months_ahead=months_ahead, now=now)

    logger.warning("partitions: converted %s (legacy partition up to %s; created %s)", table, cutoff, created)
    return {**p, "already_partitioned": True, "created": created}
