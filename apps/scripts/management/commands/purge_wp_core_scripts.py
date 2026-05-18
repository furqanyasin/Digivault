"""Management command: delete all stored wp-includes / wp-admin scripts."""
from django.core.management.base import BaseCommand

from apps.scripts.models import Script


class Command(BaseCommand):
    help = "Delete all Script records whose src_url contains /wp-includes/ or /wp-admin/"

    def handle(self, *args, **options):
        qs = Script.objects.filter(src_url__contains="/wp-includes/") | \
             Script.objects.filter(src_url__contains="/wp-admin/")
        count, _ = qs.delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {count} WordPress core script record(s)."))
