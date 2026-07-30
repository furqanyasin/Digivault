"""Populate a team with realistic demo data so the dashboard has something to show.

Every record is tagged so it can be removed again — see ``--purge``. Nothing here
touches real data: objects are matched by the DEMO_TAG marker, never by name
alone, so a genuine site that happens to share a name is never deleted.

    python manage.py seed_demo_data --team "Local Dev Agency"
    python manage.py seed_demo_data --team "Local Dev Agency" --purge

Deterministic: a fixed seed means re-running produces the same numbers, so a
screenshot stays reproducible.
"""

from __future__ import annotations

import random
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

# Written into Website.tags (and mirrored on the client's notes) so --purge can
# find exactly what this command created.
DEMO_TAG = "digivault-demo"

# name, domain, platform, health shape
SITES = [
    ("Northwind Dental", "northwind-dental.example", "wordpress", "healthy"),
    ("Harbour Legal", "harbourlegal.example", "wordpress", "healthy"),
    ("Peak Fitness Studio", "peakfitness.example", "webflow", "warning"),
    ("Ridgeway Motors", "ridgewaymotors.example", "wordpress", "warning"),
    ("Cove Coffee Roasters", "covecoffee.example", "shopify", "critical"),
    ("Alder & Finch Interiors", "alderfinch.example", "squarespace", "critical"),
    ("Summit Roofing", "summitroofing.example", "wordpress", "healthy"),
    ("Lakeside Veterinary", "lakesidevet.example", "wix", "warning"),
    ("Bramble Garden Centre", "bramblegarden.example", "wordpress", "healthy"),
    ("Foxglove Photography", "foxglovephoto.example", "framer", "stale"),
]

THIRD_PARTY = [
    ("https://www.googletagmanager.com/gtag/js?id=G-DEMO", "Google Tag Manager", "analytics"),
    ("https://connect.facebook.net/en_US/fbevents.js", "Meta Pixel", "advertising"),
    ("https://static.hotjar.com/c/hotjar-123.js", "Hotjar", "analytics"),
    ("https://js.stripe.com/v3/", "Stripe", "payments"),
    ("https://cdn.jsdelivr.net/npm/swiper/swiper-bundle.min.js", "jsDelivr", "cdn"),
    ("https://widget.intercom.io/widget/demo", "Intercom", "chat"),
    ("https://cdn.unknown-tracker.example/t.js", "unknown", "unknown"),
    ("https://tag.clickcease.example/monitor.js", "unknown", "unknown"),
]

CHANGE_BLURBS = [
    ("added", "critical", "Unknown script detected: {url}"),
    ("added", "high", "New third-party script added: {url}"),
    ("modified", "medium", "Script attributes changed: {url}"),
    ("removed", "low", "Script no longer present: {url}"),
]

# Everything that decides a site's health band is keyed off its shape, not its
# row index. Driving expiries and monitor state off the index instead put every
# site — including the ones labelled "healthy" — into warning or critical, so the
# donut had no green in it and the whole point of the seed was lost.
#
# open_changes / days_to_expiry are chosen against the real scoring rules in
# Website.recalculate_health_score: expiry inside 30 days deducts and flags, and
# uptime under 99% deducts, so a healthy site needs distant renewals AND a clean
# monitor.
# The weights are tuned to land mid-band, not at the extremes: stacking every
# penalty on the critical sites floored them at 0, which reads as broken data
# rather than a site in trouble. Renewal windows are also spread across the
# forecast's three buckets (<=30 / 31-60 / 61-90) so that chart has all of them.
SHAPES = {
    "healthy": {
        "open_changes": 0,
        "ssl_days": 240, "domain_days": 300, "hosting_days": 275,
        "monitor_status": "up", "uptime_ratio": 1.0,
        "unreviewed_scripts": False, "broken_forms": 0,
    },
    "warning": {
        "open_changes": 1,          # medium only — high would force critical
        "ssl_days": 26, "domain_days": 58, "hosting_days": 40,
        "monitor_status": "up", "uptime_ratio": 1.0,
        "unreviewed_scripts": True, "broken_forms": 0,
    },
    "critical": {
        # One high-severity change plus a down monitor is enough; the score lands
        # around 40 and the status flags read critical for the right reasons.
        "open_changes": 1,
        "ssl_days": 200, "domain_days": 88, "hosting_days": 75,
        "monitor_status": "down", "uptime_ratio": 0.97,
        "unreviewed_scripts": True, "broken_forms": 1,
    },
    "stale": {
        "open_changes": 0,
        "ssl_days": 150, "domain_days": 190, "hosting_days": 75,
        "monitor_status": "up", "uptime_ratio": 1.0,
        "unreviewed_scripts": False, "broken_forms": 0,
    },
}

# A "warning" site must not be handed a critical/high change, or the urgency
# flags push it straight to critical.
WARNING_BLURB = ("modified", "medium", "Script attributes changed: {url}")


class Command(BaseCommand):
    help = "Seed (or purge) demo websites, scripts, alerts, uptime and renewals for a team."

    def add_arguments(self, parser):
        parser.add_argument(
            "--team",
            required=True,
            help='Team name, e.g. --team "Local Dev Agency".',
        )
        parser.add_argument(
            "--purge",
            action="store_true",
            help="Delete everything this command created for the team, then stop.",
        )
        parser.add_argument(
            "--days", type=int, default=30,
            help="How much history to generate (default 30).",
        )

    def handle(self, *args, **options):
        from apps.accounts.models import Team

        name = options["team"]
        try:
            team = Team.objects.get(name=name)
        except Team.DoesNotExist:
            available = ", ".join(Team.objects.values_list("name", flat=True)) or "(none)"
            raise CommandError(f"No team named {name!r}. Available: {available}")
        except Team.MultipleObjectsReturned:
            raise CommandError(f"More than one team is named {name!r}; rename one first.")

        if options["purge"]:
            self._purge(team)
            return

        random.seed(20260730)
        # Creating a Website fires run_initial_checks, which does live uptime,
        # WHOIS and PageSpeed calls. Against invented .example domains those can
        # only fail, and they made seeding take minutes. Suppressed here — the
        # command writes its own history anyway.
        from unittest.mock import patch

        with patch("apps.websites.tasks.run_initial_checks.delay"):
            with transaction.atomic():
                self._seed(team, options["days"])

    # ------------------------------------------------------------------ purge

    def _purge(self, team):
        from apps.clients.models import Client
        from apps.websites.models import Website

        sites = Website.objects.filter(team=team, tags__contains=[DEMO_TAG])
        n_sites = sites.count()
        # Cascades take scripts, changes, forms, snapshots, monitors and
        # domain info with them.
        sites.delete()
        clients = Client.objects.filter(team=team, notes__contains=DEMO_TAG)
        n_clients = clients.count()
        clients.delete()
        self.stdout.write(
            self.style.SUCCESS(
                f"Purged {n_sites} demo website(s) and {n_clients} demo client(s) from {team.name!r}."
            )
        )

    # ------------------------------------------------------------------- seed

    def _seed(self, team, days: int):
        from apps.clients.models import Client
        from apps.domains.models import DomainInfo
        from apps.monitors.models import Monitor, MonitorCheck
        from apps.scripts.models import (
            DetectedForm, FormSubmissionError, Script, ScriptChange,
        )
        from apps.websites.models import Website

        now = timezone.now()
        tiers = ["gold", "silver", "bronze", ""]
        departments = [
            ["seo", "ads"], ["seo", "content"], ["dev"], ["seo", "lead_insight"],
            ["social_media", "ads"], ["seo", "social_media", "content"],
        ]

        created_sites = []
        for idx, (site_name, domain, platform, shape) in enumerate(SITES):
            client, _ = Client.objects.update_or_create(
                team=team,
                name=site_name,
                defaults={
                    "website_url": f"https://{domain}",
                    "status": "active" if shape != "stale" else "paused",
                    "tier": tiers[idx % len(tiers)],
                    "departments": departments[idx % len(departments)],
                    "hosting_platform": ["wpengine", "siteground", "cloudways", "godaddy"][idx % 4],
                    "hosting_renewal_date": (now + timedelta(days=[18, 40, 75, 120][idx % 4])).date(),
                    "domain_renewal_date": (now + timedelta(days=[25, 58, 88, 200][idx % 4])).date(),
                    "domain_access_location": "Digilatics GoDaddy account",
                    "website_access_level": ["full_admin", "delegate", "none", "not_working"][idx % 4],
                    "website_built_by_digi": "YES" if idx % 3 else "NO",
                    "website_maintained_by_digi": "YES" if idx % 2 else "NO",
                    "running_ppc_ads": ["yes", "no", ""][idx % 3],
                    # The purge marker. Kept in notes because Client has no tags.
                    "notes": f"Demo record created by seed_demo_data ({DEMO_TAG}).",
                },
            )

            site, _ = Website.objects.update_or_create(
                team=team,
                domain=domain,
                defaults={
                    "name": site_name,
                    "platform": platform,
                    "client": client,
                    "tags": [DEMO_TAG],
                    "is_vip": idx < 3,
                },
            )
            created_sites.append((site, shape, idx))

            spec = SHAPES[shape]

            # --- scripts -------------------------------------------------
            # Healthy sites get only recognised providers: an unreviewed script
            # deducts, so leaving one pending would stop them reaching the band.
            picks = [
                (url, provider, category)
                for url, provider, category in THIRD_PARTY[: 3 + (idx % 5)]
                if spec["unreviewed_scripts"] or provider != "unknown"
            ]
            scripts = []
            for url, provider, category in picks:
                unknown = provider == "unknown"
                scripts.append(
                    Script.objects.update_or_create(
                        website=site,
                        src_url=url,
                        defaults={
                            "src_domain": url.split("/")[2],
                            "provider": provider,
                            "category": category,
                            "location": "head",
                            "scope": "GLOBAL",
                            "is_active": True,
                            "review_status": (
                                Script.ReviewStatus.PENDING if unknown
                                else Script.ReviewStatus.APPROVED
                            ),
                        },
                    )[0]
                )
            # Drop any script left over from an earlier run with a different shape.
            Script.objects.filter(website=site).exclude(
                src_url__in=[u for u, _, _ in picks]
            ).delete()

            # --- open alerts, weighted by the site's shape ----------------
            ScriptChange.objects.filter(website=site).delete()
            for n in range(spec["open_changes"]):
                change_type, severity, blurb = (
                    WARNING_BLURB if shape in ("warning", "stale")
                    else CHANGE_BLURBS[n % len(CHANGE_BLURBS)]
                )
                script = scripts[n % len(scripts)]
                change = ScriptChange.objects.create(
                    website=site,
                    script=script,
                    change_type=change_type,
                    severity=severity,
                    description=blurb.format(url=script.src_url),
                )
                # Spread them across the window so the trend chart has shape.
                ScriptChange.objects.filter(pk=change.pk).update(
                    created_at=now - timedelta(days=random.randint(0, days - 1), hours=random.randint(0, 23))
                )

            # --- forms ---------------------------------------------------
            DetectedForm.objects.update_or_create(
                website=site,
                page_url=f"https://{domain}/contact",
                fingerprint=f"demo-contact-{idx}",
                defaults={
                    "form_name": "Contact form",
                    "form_action": f"https://{domain}/contact",
                    "detection_type": "native",
                    "fields": [
                        {"name": "name", "type": "text", "label": "Name", "required": True},
                        {"name": "email", "type": "email", "label": "Email", "required": True},
                        {"name": "message", "type": "textarea", "label": "Message", "required": False},
                    ],
                    "submission_count": random.randint(3, 90),
                },
            )
            FormSubmissionError.objects.filter(website=site).delete()
            for _ in range(spec["broken_forms"]):
                err = FormSubmissionError.objects.create(
                    website=site,
                    page_url=f"https://{domain}/contact",
                    source="Contact Form 7",
                    message="SMTP connect() failed",
                )
                FormSubmissionError.objects.filter(pk=err.pk).update(
                    created_at=now - timedelta(days=random.randint(0, 5))
                )

            # --- domain / SSL / hosting expiry, by shape -----------------
            DomainInfo.objects.update_or_create(
                website=site,
                defaults={
                    "registrar": "GoDaddy",
                    "hosting_provider": "WPEngine",
                    "expires_at": now + timedelta(days=spec["domain_days"]),
                    "ssl_expires_at": now + timedelta(days=spec["ssl_days"]),
                    "hosting_expires_at": now + timedelta(days=spec["hosting_days"]),
                },
            )

            # --- last_seen_at: "stale" means the snippet went quiet -------
            Website.objects.filter(pk=site.pk).update(
                last_seen_at=(
                    now - timedelta(days=12) if shape == "stale"
                    else now - timedelta(hours=idx)
                )
            )

        # --- uptime history, per site ------------------------------------
        # Each site's dips follow its own shape. Applying one global dip pattern
        # dragged every monitor's 30-day uptime under 99%, which deducts, so even
        # the healthy sites could not reach their band.
        by_site = {site.id: spec_shape for site, spec_shape, _ in created_sites}
        monitors = list(
            Monitor.objects.filter(website__in=[s for s, _, _ in created_sites])
            .select_related("website")
        )
        MonitorCheck.objects.filter(monitor__in=monitors).delete()

        rows, stamps = [], []
        for monitor in monitors:
            shape = by_site.get(monitor.website_id, "healthy")
            ratio = SHAPES[shape]["uptime_ratio"]
            # Healthy sites stay clean; the rest dip on a couple of fixed days so
            # the curve has shape without being noise.
            dip_days = () if ratio >= 1.0 else (4, 11, 18)
            for day in range(days - 1, -1, -1):
                up_ratio = ratio if day in dip_days else 1.0
                for hour in range(0, 24, 4):
                    when = (now - timedelta(days=day)).replace(
                        hour=hour, minute=0, second=0, microsecond=0
                    )
                    if when > now:
                        continue
                    is_up = (hour // 4) % 6 < round(up_ratio * 6)
                    rows.append(
                        MonitorCheck(
                            monitor=monitor,
                            status=MonitorCheck.Status.UP if is_up else MonitorCheck.Status.DOWN,
                            response_time_ms=random.randint(120, 480) if is_up else None,
                        )
                    )
                    stamps.append(when)

        MonitorCheck.objects.bulk_create(rows, batch_size=1000)
        # checked_at is auto_now_add, so the timestamps are written afterwards.
        for check, when in zip(rows, stamps):
            MonitorCheck.objects.filter(pk=check.pk).update(checked_at=when)

        for monitor in monitors:
            monitor.recalculate_uptime()
            # Current status follows the shape too, so "monitors down" is real
            # rather than a couple of arbitrary rows forced red.
            shape = by_site.get(monitor.website_id, "healthy")
            Monitor.objects.filter(pk=monitor.pk).update(
                status=(
                    Monitor.Status.DOWN
                    if SHAPES[shape]["monitor_status"] == "down"
                    else Monitor.Status.UP
                )
            )

        for site, _, _ in created_sites:
            site.refresh_from_db()
            site.recalculate_health_score()

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {len(created_sites)} demo websites, {len(rows)} monitor checks "
                f"and {days} days of history for {team.name!r}.\n"
                f"Remove it all with: manage.py seed_demo_data --team \"{team.name}\" --purge"
            )
        )
