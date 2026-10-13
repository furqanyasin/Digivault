"""Convert a purge-by-age table to monthly partitions, without copying rows.

Usage (on the server, once the capacity check says so):
    docker compose -f docker-compose.production.cloudpanel.yml exec api \
        python manage.py partition_table scripts_scriptsnapshot --dry-run
    ... then the same without --dry-run.

Runs the key index build CONCURRENTLY, so it must not be wrapped in a
transaction, and on a large table that step takes minutes while writes carry
on. The switch itself holds an exclusive lock for a moment. See
apps/common/partitions.py for the steps, and docs/runbooks/capacity-checks.md
for when to run it.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.common import partitions


class Command(BaseCommand):
    help = "Convert scripts_scriptsnapshot or monitors_monitorcheck to monthly partitions."

    def add_arguments(self, parser):
        parser.add_argument("table", choices=sorted(partitions.PARTITIONED_TABLES))
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report the table's size and the cutoff that would be used, and change nothing.",
        )
        parser.add_argument(
            "--months-ahead",
            type=int,
            default=partitions.DEFAULT_MONTHS_AHEAD,
            help="Monthly partitions to create past the current month (default 3).",
        )

    def handle(self, *args, table, dry_run, months_ahead, **options):
        p = partitions.plan(table)
        self.stdout.write(
            f"{table}: {p['rows']} rows, {p['size']}, partitioned on {p['column']}\n"
            f"  existing rows become the first partition, covering everything before {p['cutoff']:%Y-%m-%d}"
        )
        if p["already_partitioned"]:
            self.stdout.write(self.style.SUCCESS("  already partitioned; nothing to do"))
            return
        if p["referenced_by"]:
            raise CommandError(f"referenced by foreign keys from {p['referenced_by']}; not converting")
        if dry_run:
            self.stdout.write("  dry run: nothing changed")
            return

        result = partitions.convert(table, concurrently=True, months_ahead=months_ahead)
        self.stdout.write(self.style.SUCCESS(
            f"  converted; created {', '.join(result['created']) or 'no future partitions'}"
        ))
