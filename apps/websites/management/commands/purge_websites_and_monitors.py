"""Management command: delete websites and monitors so they can be re-added by hand.

Written for the production database, where the cost of a mistake is a client's
whole history. Three things follow from that:

* It is a dry run unless ``--confirm`` is passed, and the dry run prints the
  real cascade (via the admin's ``NestedObjects`` collector) rather than a guess
  at it.
* It exports what it is about to delete first, unless told not to. The point of
  the purge is to re-add the sites manually, and nobody remembers 40 domains,
  their platform, client, VIP flag and SEO interval. The export is that list.
* It deletes one website at a time inside one transaction, so a failure
  half-way leaves the database as it was and the operator can see how far it got.

``Monitor.website`` is ``SET_NULL``, not ``CASCADE`` — deleting a Website leaves
its Monitor behind pointing at nothing, still checking, still alerting. So
monitors are deleted explicitly, and before their websites.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone as dt_timezone

from django.contrib.admin.utils import NestedObjects
from django.core.management.base import BaseCommand, CommandError
from django.db import router, transaction

from apps.monitors.models import Monitor
from apps.websites.models import Website


class Command(BaseCommand):
    help = (
        "Delete websites (and their monitors) so they can be re-added manually. "
        "Dry run unless --confirm is passed."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirm", action="store_true",
            help="Actually delete. Without this the command only reports.",
        )
        parser.add_argument(
            "--team", default=None, metavar="SLUG",
            help="Limit to one team by slug (or name). Default: every team.",
        )
        parser.add_argument(
            "--domain", action="append", default=[], metavar="SUBSTRING",
            help="Limit to websites whose domain contains this. Repeatable.",
        )
        parser.add_argument(
            "--export", default=None, metavar="PATH",
            help="Where to write the re-add list. Default: a timestamped file "
                 "in the current directory.",
        )
        parser.add_argument(
            "--no-export", action="store_true",
            help="Skip the export. You will have no record of what was deleted.",
        )
        parser.add_argument(
            "--websites-only", action="store_true",
            help="Delete websites but leave monitors (they will be orphaned).",
        )
        parser.add_argument(
            "--monitors-only", action="store_true",
            help="Delete monitors but leave websites and all script history.",
        )
        parser.add_argument(
            "--delete-status-pages", action="store_true",
            help="Also delete status pages. Default is to keep them: their "
                 "public slugs are already shared, and re-adding a website "
                 "re-attaches the new monitor to the existing page.",
        )

    # ── main ──────────────────────────────────────────────────────────────────

    def handle(self, *args, **opts):
        if opts["websites_only"] and opts["monitors_only"]:
            raise CommandError(
                "--websites-only and --monitors-only are mutually exclusive."
            )

        team = self._resolve_team(opts["team"])
        scoped = bool(team or opts["domain"])
        websites = self._select_websites(team, opts["domain"])
        monitors = self._select_monitors(websites, scoped)

        do_websites = not opts["monitors_only"]
        do_monitors = not opts["websites_only"]

        if do_websites and not websites.exists():
            self.stdout.write(self.style.WARNING("No websites matched. Nothing to do."))
            return
        if opts["monitors_only"] and not monitors.exists():
            self.stdout.write(self.style.WARNING("No monitors matched. Nothing to do."))
            return

        self._report(websites, monitors, do_websites, do_monitors, opts)

        if not opts["confirm"]:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING(
                "DRY RUN — nothing was deleted. Re-run with --confirm to apply."
            ))
            return

        if not opts["no_export"] and do_websites:
            path = self._export(websites, monitors, opts["export"])
            self.stdout.write(self.style.SUCCESS(f"Exported re-add list to {path}"))

        self._delete(websites, monitors, do_websites, do_monitors, opts)

    # ── selection ─────────────────────────────────────────────────────────────

    def _resolve_team(self, ident):
        if not ident:
            return None
        from apps.accounts.models import Team

        team = (
            Team.objects.filter(slug=ident).first()
            or Team.objects.filter(name=ident).first()
        )
        if team is None:
            known = ", ".join(Team.objects.values_list("slug", flat=True)[:20]) or "(none)"
            raise CommandError(
                f"No team with slug or name {ident!r}. Known slugs: {known}"
            )
        return team

    def _select_websites(self, team, domains):
        qs = Website.objects.all()
        if team:
            qs = qs.filter(team=team)
        if domains:
            from django.db.models import Q

            q = Q()
            for d in domains:
                q |= Q(domain__icontains=d)
            qs = qs.filter(q)
        return qs.order_by("domain")

    def _select_monitors(self, websites, scoped):
        """Which monitors go with this run.

        Unscoped (no --team, no --domain) means every monitor, including the
        standalone ones nobody attached to a website — leaving those behind is
        how a purged fleet keeps paging someone. Once the run is scoped, only
        monitors belonging to the selected websites are in range; a scoped run
        must not reach outside its scope.
        """
        if not scoped:
            return Monitor.objects.all().order_by("name")
        return Monitor.objects.filter(website__in=websites).order_by("name")

    # ── reporting ─────────────────────────────────────────────────────────────

    def _report(self, websites, monitors, do_websites, do_monitors, opts):
        w_count, m_count = websites.count(), monitors.count()
        self.stdout.write(self.style.MIGRATE_HEADING("Selected"))
        if do_websites:
            self.stdout.write(f"  websites : {w_count}")
            for w in websites.select_related("team")[:60]:
                self.stdout.write(f"    - {w.domain}  ({w.name}, team={w.team.slug})")
            if w_count > 60:
                self.stdout.write(f"    ... and {w_count - 60} more")
        if do_monitors:
            self.stdout.write(f"  monitors : {m_count}")

        self.stdout.write("")
        self.stdout.write(
            self.style.MIGRATE_HEADING("Rows this will delete (full cascade, approx)")
        )
        counts = self._cascade_counts(websites, monitors, do_websites, do_monitors)
        for label in sorted(counts):
            self.stdout.write(f"  {counts[label]:>9,}  {label}")

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Survives the delete"))
        if do_websites:
            from apps.credentials.models import Credential

            cred_n = Credential.objects.filter(website__in=websites).count()
            self.stdout.write(
                f"  {cred_n:>9,}  credentials - Credential.website is SET_NULL, so "
                "vault entries are kept but unlinked; re-link them by hand."
            )
        if not opts["delete_status_pages"]:
            self.stdout.write(
                "             status pages - kept, so public URLs keep working. "
                "Re-adding a website re-attaches its new monitor to the page."
            )
        if do_websites:
            self.stdout.write(
                "             clients - never touched (Website.client is SET_NULL)."
            )

        if do_websites:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING(
                "Re-adding generates a NEW site_id and a NEW wp_sso_secret for every "
                "site. The tracking snippet and the WP Connect snippet must be "
                "re-pasted on each client site, or detection silently stops."
            ))

    def _cascade_counts(self, websites, monitors, do_websites, do_monitors):
        """Ask Django's own collector what goes, so the preview cannot drift.

        Sampled, not exhaustive: the collector loads every related row into
        memory, and one production website carries 90 days of ScriptSnapshots.
        Counting a slice and scaling keeps the preview honest about magnitude
        without an OOM on the dry run — hence the "approx" in the heading.
        """
        counts: dict[str, int] = {}
        sample_size = 5

        def collect(objs, total):
            if not objs:
                return
            first = objs[0]
            using = router.db_for_write(first.__class__, instance=first)
            collector = NestedObjects(using=using)
            collector.collect(objs)
            scale = total / len(objs)
            for model, instances in collector.data.items():
                label = model._meta.label
                counts[label] = counts.get(label, 0) + int(round(len(instances) * scale))

        if do_websites:
            collect(list(websites[:sample_size]), websites.count())
        if do_monitors:
            collect(list(monitors[:sample_size]), monitors.count())

        return counts

    def _status_page_ids(self, websites):
        """Status pages belonging to the selected websites, and only those.

        Matched by slug rather than by team, because a page has no FK to the
        website that spawned it. Filtering on team instead would make
        ``--domain shop`` delete the status pages of every other site the team
        owns — a scoped run silently reaching outside its scope.

        The slug rule mirrors ``signals._create_status_page`` exactly, including
        its ``-N`` collision variants, so the two cannot drift apart.
        """
        import re as _re

        from django.db.models import Q

        from apps.status_pages.models import StatusPage
        from apps.websites.signals import _slugify

        teams = set(websites.values_list("team_id", flat=True))
        q = Q(pk__in=[])
        for domain in websites.values_list("domain", flat=True):
            base = _slugify(domain.replace("https://", "").replace("http://", ""))
            q |= Q(slug=base) | Q(slug__regex=rf"^{_re.escape(base)}-\d+$")

        return list(
            StatusPage.objects.filter(team_id__in=teams).filter(q).values_list("pk", flat=True)
        )

    # ── export ────────────────────────────────────────────────────────────────

    def _export(self, websites, monitors, path):
        stamp = datetime.now(dt_timezone.utc).strftime("%Y%m%d-%H%M%S")
        path = path or f"digivault-websites-{stamp}.json"

        payload = {
            "exported_at": datetime.now(dt_timezone.utc).isoformat(),
            "note": "Field list for re-adding these websites by hand. old_site_id "
                    "is recorded for reference only - re-adding generates a new one.",
            "websites": [
                {
                    "name": w.name,
                    "domain": w.domain,
                    "platform": w.platform,
                    "status": w.status,
                    "team": w.team.slug,
                    "client": w.client.name if w.client_id else None,
                    "is_vip": w.is_vip,
                    "seo_scan_interval_days": w.seo_scan_interval_days,
                    "tags": w.tags,
                    "notes": w.notes,
                    "old_site_id": w.site_id,
                    "had_wp_sso": bool(w.wp_sso_secret),
                    "snippet_status": w.snippet_status,
                    "health_score": w.health_score,
                }
                for w in websites.select_related("team", "client")
            ],
            "monitors": [
                {
                    "name": m.name,
                    "url": m.url,
                    "monitor_type": m.monitor_type,
                    "team": m.team.slug,
                    "website_domain": m.website.domain if m.website_id else None,
                    "check_interval": m.check_interval,
                    "timeout": m.timeout,
                    "retry_count": m.retry_count,
                    "expected_status_code": m.expected_status_code,
                    "request_method": m.request_method,
                    "keyword": m.keyword,
                    "port": m.port,
                    "is_active": m.is_active,
                    "tags": m.tags,
                    "notes": m.notes,
                }
                for m in monitors.select_related("team", "website")
            ],
        }

        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
        return path

    # ── deletion ──────────────────────────────────────────────────────────────

    def _delete(self, websites, monitors, do_websites, do_monitors, opts):
        # Snapshot the ids up front: the querysets are lazy, and deleting
        # monitors changes what a re-evaluated queryset would return.
        monitor_ids = list(monitors.values_list("pk", flat=True)) if do_monitors else []
        website_ids = list(websites.values_list("pk", flat=True)) if do_websites else []
        page_ids = self._status_page_ids(websites) if (
            opts["delete_status_pages"] and do_websites
        ) else []

        with transaction.atomic():
            # Monitors first — a monitor left orphaned mid-run is still claimed
            # by run_due_checks and could alert on a site being purged.
            if monitor_ids:
                n, _ = Monitor.objects.filter(pk__in=monitor_ids).delete()
                self.stdout.write(self.style.SUCCESS(
                    f"Deleted {len(monitor_ids)} monitor(s) "
                    f"({n:,} rows including check history)."
                ))

            # One website at a time: bounded memory against a 90-day snapshot
            # table, and visible progress on a long production run.
            total_rows = 0
            for i, pk in enumerate(website_ids, start=1):
                w = Website.objects.filter(pk=pk).first()
                if w is None:
                    continue
                domain = w.domain
                n, _ = w.delete()
                total_rows += n
                self.stdout.write(f"  [{i}/{len(website_ids)}] {domain} - {n:,} rows")
            if website_ids:
                self.stdout.write(self.style.SUCCESS(
                    f"Deleted {len(website_ids)} website(s) ({total_rows:,} rows total)."
                ))

            if page_ids:
                from apps.status_pages.models import StatusPage

                n, _ = StatusPage.objects.filter(pk__in=page_ids).delete()
                self.stdout.write(self.style.SUCCESS(
                    f"Deleted {len(page_ids)} status page(s) ({n:,} rows)."
                ))

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            "Done. Re-add the sites from the export file."
        ))
