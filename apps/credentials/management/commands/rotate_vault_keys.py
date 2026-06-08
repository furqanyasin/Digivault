"""Re-encrypt every credential blob under the current primary vault key.

Usage (during key rotation):
    1. Prepend the new key to VAULT_ENCRYPTION_KEYS (it becomes primary).
    2. Deploy so all workers can decrypt old + new.
    3. Run:  python manage.py rotate_vault_keys
    4. Once complete, remove the old key from VAULT_ENCRYPTION_KEYS.

Idempotent and resumable: re-running re-rotates already-rotated rows harmlessly
(they're simply re-encrypted under the same primary key again).
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.credentials import encryption
from apps.credentials.models import Credential

ENCRYPTED_FIELDS = ("_username", "_password", "_notes")


class Command(BaseCommand):
    help = "Re-encrypt all credential blobs under the current primary vault key."

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch-size",
            type=int,
            default=200,
            help="Number of credentials per transaction (default 200).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report how many credentials would be rotated without writing.",
        )

    def handle(self, *args, **options):
        batch_size = options["batch_size"]
        dry_run = options["dry_run"]

        qs = Credential.objects.all().order_by("pk")
        total = qs.count()
        self.stdout.write(f"Found {total} credential(s) to rotate.")
        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run — no changes written."))
            return

        rotated = 0
        ids = list(qs.values_list("pk", flat=True))
        for start in range(0, len(ids), batch_size):
            chunk = ids[start : start + batch_size]
            with transaction.atomic():
                for cred in Credential.objects.filter(pk__in=chunk).select_for_update():
                    changed = False
                    for field in ENCRYPTED_FIELDS:
                        blob = getattr(cred, field)
                        if blob:
                            setattr(cred, field, encryption.rotate_token(bytes(blob)))
                            changed = True
                    if changed:
                        cred.save(update_fields=list(ENCRYPTED_FIELDS))
                        rotated += 1
            self.stdout.write(f"  rotated {min(start + batch_size, len(ids))}/{total}")

        self.stdout.write(self.style.SUCCESS(f"Done. Rotated {rotated} credential(s)."))
