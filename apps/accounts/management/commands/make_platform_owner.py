"""Give an account platform-owner rights (Django superuser + staff).

    python manage.py make_platform_owner someone@example.com
    python manage.py make_platform_owner          # every PLATFORM_OWNER_EMAILS

The api container runs the second form on every start, so the owner listed
in settings keeps the rights after a fresh deploy. An email with no account
yet is reported and skipped: sign up first, then restart or run this again.
"""

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.accounts.models import User


class Command(BaseCommand):
    help = "Make the given emails (or PLATFORM_OWNER_EMAILS) platform owners."

    def add_arguments(self, parser):
        parser.add_argument("emails", nargs="*")

    def handle(self, *args, emails, **options):
        emails = emails or list(getattr(settings, "PLATFORM_OWNER_EMAILS", []))
        for email in (e.strip().lower() for e in emails if e.strip()):
            user = User.objects.filter(email__iexact=email).first()
            if user is None:
                self.stdout.write(self.style.WARNING(f"{email}: no account yet, skipped."))
                continue
            if user.is_superuser and user.is_staff and user.is_active:
                self.stdout.write(f"{email}: already a platform owner.")
                continue
            User.objects.filter(pk=user.pk).update(is_superuser=True, is_staff=True, is_active=True)
            self.stdout.write(self.style.SUCCESS(f"{email}: is now a platform owner."))
