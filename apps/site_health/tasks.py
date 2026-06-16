"""Celery tasks for site health — security scanning."""
from __future__ import annotations

import json
import logging
import urllib.request

from celery import shared_task
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def _wpscan_api_key() -> str:
    return getattr(settings, "WPSCAN_API_KEY", "")


def _fetch_wpscan(endpoint: str) -> dict | None:
    key = _wpscan_api_key()
    if not key:
        return None
    url = f"https://wpscan.com/api/v3/{endpoint}"
    req = urllib.request.Request(url, headers={"Authorization": f"Token token={key}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as exc:
        logger.warning("WPScan API error for %s: %s", endpoint, exc)
        return None


def _slug_from_plugin_name(name: str) -> str:
    """Convert 'Yoast SEO' → 'wordpress-seo', etc. Best-effort slugification."""
    return name.lower().replace(" ", "-").replace("_", "-")


@shared_task(name="site_health.run_security_scan")
def run_security_scan(website_id: str) -> None:
    from apps.site_health.models import SiteScanState, VulnerabilityReport
    from apps.scripts.models import Script
    from apps.websites.models import Website

    try:
        website = Website.objects.get(pk=website_id)
    except Website.DoesNotExist:
        return

    state, _ = SiteScanState.objects.get_or_create(website=website)
    state.scan_status = "running"
    state.error = ""
    state.save(update_fields=["scan_status", "error"])

    try:
        # Gather unique plugin slugs from detected scripts
        plugin_names = list(
            Script.objects.filter(website=website, is_active=True)
            .exclude(wp_plugin="")
            .values_list("wp_plugin", flat=True)
            .distinct()
        )
        state.plugins_detected = plugin_names
        found_vulns: list[dict] = []

        if _wpscan_api_key():
            for plugin_name in plugin_names:
                slug = _slug_from_plugin_name(plugin_name)
                data = _fetch_wpscan(f"plugins/{slug}")
                if not data or slug not in data:
                    continue
                for vuln in data[slug].get("vulnerabilities", []):
                    severity = _map_cvss_to_severity(vuln.get("cvss", {}).get("score"))
                    cves = vuln.get("references", {}).get("cve", [])
                    found_vulns.append({
                        "component_type": "plugin",
                        "component_name": plugin_name,
                        "component_version": "",
                        "cve_ids": [f"CVE-{c}" for c in cves],
                        "severity": severity,
                        "title": vuln.get("title", "Unknown vulnerability"),
                        "description": "",
                        "fixed_in_version": vuln.get("fixed_in") or "",
                        "references": list(vuln.get("references", {}).get("url", [])),
                        "source": "wpscan",
                    })

            # Check WP core version if known
            if state.wp_version:
                ver_key = state.wp_version.replace(".", "")
                data = _fetch_wpscan(f"wordpresses/{ver_key}")
                if data and ver_key in data:
                    for vuln in data[ver_key].get("vulnerabilities", []):
                        severity = _map_cvss_to_severity(vuln.get("cvss", {}).get("score"))
                        cves = vuln.get("references", {}).get("cve", [])
                        found_vulns.append({
                            "component_type": "core",
                            "component_name": "WordPress Core",
                            "component_version": state.wp_version,
                            "cve_ids": [f"CVE-{c}" for c in cves],
                            "severity": severity,
                            "title": vuln.get("title", "Core vulnerability"),
                            "description": "",
                            "fixed_in_version": vuln.get("fixed_in") or "",
                            "references": list(vuln.get("references", {}).get("url", [])),
                            "source": "wpscan",
                        })
        else:
            # No API key — use built-in heuristics
            found_vulns.extend(_heuristic_scan(plugin_names))

        # Persist: clear old results then insert fresh ones
        VulnerabilityReport.objects.filter(website=website).delete()
        for v in found_vulns:
            VulnerabilityReport.objects.update_or_create(
                website=website,
                component_name=v["component_name"],
                title=v["title"],
                defaults=v,
            )

        # CMS update-available: compare detected WP core version to the latest.
        if state.wp_version:
            latest = _fetch_latest_wp_version()
            if latest:
                state.wp_latest_version = latest
                state.wp_update_available = _version_lt(state.wp_version, latest)

        state.last_scanned_at = timezone.now()
        state.scan_status = "done"
        state.save(update_fields=[
            "last_scanned_at", "scan_status", "plugins_detected",
            "wp_latest_version", "wp_update_available",
        ])
        website.recalculate_health_score()

    except Exception as exc:
        logger.exception("Security scan failed for website %s", website_id)
        state.scan_status = "failed"
        state.error = str(exc)
        state.save(update_fields=["scan_status", "error"])


def _version_tuple(v: str) -> tuple[int, ...]:
    parts = []
    for chunk in str(v).split("."):
        num = "".join(c for c in chunk if c.isdigit())
        parts.append(int(num) if num else 0)
    return tuple(parts)


def _version_lt(current: str, latest: str) -> bool:
    """True if `current` is an older version than `latest`."""
    return _version_tuple(current) < _version_tuple(latest)


def _fetch_latest_wp_version() -> str | None:
    """Return the current stable WordPress core version, or None on failure."""
    try:
        req = urllib.request.Request(
            "https://api.wordpress.org/core/version-check/1.7/",
            headers={"User-Agent": "Digivault/1.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        offers = data.get("offers", [])
        for offer in offers:
            if offer.get("response") == "upgrade" or offer.get("current"):
                return offer.get("current")
        return offers[0].get("current") if offers else None
    except Exception as exc:
        logger.warning("Failed to fetch latest WP version: %s", exc)
        return None


def _map_cvss_to_severity(score) -> str:
    try:
        s = float(score)
    except (TypeError, ValueError):
        return "medium"
    if s >= 9.0:
        return "critical"
    if s >= 7.0:
        return "high"
    if s >= 4.0:
        return "medium"
    return "low"


# Known high-risk plugin patterns (slug substring → description)
_RISKY_PLUGINS = [
    ("file-manager", "high", "File Manager plugins have a history of critical RCE vulnerabilities"),
    ("wp-file-manager", "high", "File Manager plugins have a history of critical RCE vulnerabilities"),
    ("revslider", "high", "Revolution Slider had critical CVEs — ensure it is up to date"),
    ("revolution-slider", "high", "Revolution Slider had critical CVEs — ensure it is up to date"),
    ("wp-super-cache", "medium", "WP Super Cache had XSS vulnerabilities in older versions"),
    ("contact-form-7", "medium", "Contact Form 7 had unrestricted file upload CVEs — verify version"),
    ("woocommerce", "medium", "WooCommerce regularly releases security patches — keep updated"),
    ("elementor", "medium", "Elementor had privilege escalation CVEs — keep updated"),
    ("wpforms", "medium", "WPForms had stored XSS vulnerabilities in some versions"),
    ("ninja-forms", "medium", "Ninja Forms had critical injection CVEs"),
]


def _heuristic_scan(plugin_names: list[str]) -> list[dict]:
    results = []
    for name in plugin_names:
        slug = _slug_from_plugin_name(name)
        for pattern, severity, desc in _RISKY_PLUGINS:
            if pattern in slug:
                results.append({
                    "component_type": "plugin",
                    "component_name": name,
                    "component_version": "",
                    "cve_ids": [],
                    "severity": severity,
                    "title": f"{name} — known risk pattern detected",
                    "description": desc + " (Configure WPSCAN_API_KEY for precise CVE data.)",
                    "fixed_in_version": "",
                    "references": [],
                    "source": "heuristic",
                })
    return results


@shared_task(name="site_health.purge_old_php_errors")
def purge_old_php_errors(days: int = 90) -> int:
    """Delete PhpError rows older than `days`. Chunked to avoid long locks."""
    from apps.site_health.models import PhpError

    cutoff = timezone.now() - timezone.timedelta(days=days)
    total = 0
    chunk = 1000
    while True:
        ids = list(
            PhpError.objects.filter(captured_at__lt=cutoff).values_list(
                "pk", flat=True
            )[:chunk]
        )
        if not ids:
            break
        deleted, _ = PhpError.objects.filter(pk__in=ids).delete()
        total += deleted

    logger.info("site_health.purge_old_php_errors: removed %d rows", total)
    return total


@shared_task(name="site_health.run_seo_check")
def run_seo_check(website_id: str) -> None:
    from apps.site_health import seo_checker
    from apps.site_health.models import SeoReport, SiteEvent
    from apps.site_health.notifications import notify_team
    from apps.websites.models import Website

    try:
        website = Website.objects.get(pk=website_id)
    except Website.DoesNotExist:
        return

    report, _ = SeoReport.objects.get_or_create(website=website)
    prev = {
        "homepage_indexable": report.homepage_indexable,
        "robots_blocks_all": report.robots_blocks_all,
        "sitemap_status": report.sitemap_status,
        "first_run": report.check_status == "never",
        "meta_title": report.meta_title,
        "meta_description": report.meta_description,
        "h1": report.h1,
        "canonical_url": report.canonical_url,
        "schema_types": list(report.schema_types or []),
    }
    report.check_status = "running"
    report.error = ""
    report.save(update_fields=["check_status", "error"])

    domain = website.domain if website.domain.startswith("http") else f"https://{website.domain}"
    base = domain.rstrip("/")

    try:
        # --- robots.txt ---
        robots = {"blocks_all": False, "sitemaps": []}
        try:
            status_code, body, _h = seo_checker.fetch(f"{base}/robots.txt")
            if status_code == 200 and body.strip():
                robots = seo_checker.parse_robots(body)
                report.robots_status = "found"
                report.robots_content = body[:20000]
            else:
                report.robots_status = "missing"
                report.robots_content = ""
        except Exception:
            report.robots_status = "missing"
            report.robots_content = ""
        report.robots_blocks_all = robots["blocks_all"]

        # --- sitemap ---
        sitemap_url = robots["sitemaps"][0] if robots["sitemaps"] else f"{base}/sitemap.xml"
        sitemap_urls: list[str] = []
        try:
            status_code, body, _h = seo_checker.fetch(sitemap_url)
            if status_code == 200 and body.strip():
                count, sitemap_urls = seo_checker.count_sitemap_urls(body, seo_checker.fetch)
                report.sitemap_status = "found"
                report.sitemap_url = sitemap_url
                report.sitemap_url_count = count
                report.sitemap_pages = [u for u in sitemap_urls if seo_checker.same_origin(base, u)][:1000]
            else:
                report.sitemap_status = "missing"
        except Exception:
            report.sitemap_status = "missing"

        # --- indexability: rotating window of the page universe ---
        # The universe is the homepage + pages the snippet has actually observed
        # (where a hidden noindex turns up — noindex pages are kept out of the
        # sitemap) + sitemap pages. Each run checks the homepage plus a rotating
        # window of ~15 pages and MERGES results into the cumulative record, so
        # over a few daily runs every page is covered without one heavy scan.
        from apps.scripts.models import Script

        seen_pages: list[str] = []
        for lst in Script.objects.filter(website=website, is_active=True).values_list("seen_on_pages", flat=True):
            for u in (lst or []):
                if u not in seen_pages:
                    seen_pages.append(u)

        home = base + "/"
        universe = [home]
        for source in (seen_pages, sitemap_urls):
            for u in source:
                if u and seo_checker.same_origin(base, u) and u not in universe:
                    universe.append(u)

        rest = universe[1:]
        batch = [home]
        if rest:
            window = seo_checker.MAX_PAGES - 1  # others per scan (homepage always checked)
            start = report.scan_cursor % len(rest)
            picked = rest[start:start + window]
            if len(picked) < window:
                picked += rest[: window - len(picked)]  # wrap around
            batch += picked
            report.scan_cursor = (start + window) % len(rest)
        else:
            report.scan_cursor = 0

        now_iso = timezone.now().isoformat()
        fresh: dict[str, dict] = {}
        home_indexable = None
        home_meta = None
        for url in batch:
            try:
                _sc, html, headers = seo_checker.fetch(url)
                indexable, reason = seo_checker.page_indexability(html, headers.get("x-robots-tag", ""))
            except Exception:
                continue
            fresh[url] = {"url": url, "indexable": indexable, "reason": reason, "checked_at": now_iso}
            if url == home:
                home_indexable = indexable
                home_meta = seo_checker.parse_homepage_meta(html)

        # Merge fresh results over the cumulative record; keep only pages still
        # in the universe (drops pages removed from the site over time).
        merged = {p["url"]: p for p in (report.pages_checked or [])}
        merged.update(fresh)
        universe_set = set(universe)
        pages_checked = [p for p in merged.values() if p["url"] in universe_set][:1000]

        report.pages_checked = pages_checked
        report.noindex_count = sum(1 for p in pages_checked if not p["indexable"])
        if home_indexable is not None:
            report.homepage_indexable = home_indexable
        else:
            home_entry = next((p for p in pages_checked if p["url"] == home), None)
            report.homepage_indexable = home_entry["indexable"] if home_entry else None

        if home_meta is not None:
            report.meta_title = home_meta["meta_title"]
            report.meta_description = home_meta["meta_description"]
            report.h1 = home_meta["h1"]
            report.canonical_url = home_meta["canonical_url"]
            report.schema_types = home_meta["schema_types"]

        report.check_status = "done"
        report.last_checked_at = timezone.now()
        report.save()
    except Exception as exc:
        logger.exception("run_seo_check failed for %s", website_id)
        report.check_status = "failed"
        report.error = str(exc)[:500]
        report.save(update_fields=["check_status", "error"])
        return

    # --- regression alerts (skip on the first-ever run) ---
    if prev["first_run"]:
        return

    def _alert(event_type, severity, summary):
        SiteEvent.objects.create(
            website=website, event_type=event_type, severity=severity, summary=summary,
        )
        notify_team(website, f"[Digivault] {summary}", f"{summary} — {website.domain}")

    label = website.name or website.domain
    if prev["homepage_indexable"] is True and report.homepage_indexable is False:
        _alert(SiteEvent.EventType.SEO_NOINDEX_DETECTED, SiteEvent.Severity.CRITICAL,
               f"{label} homepage is now set to noindex")
    if not prev["robots_blocks_all"] and report.robots_blocks_all:
        _alert(SiteEvent.EventType.SEO_ROBOTS_BLOCK, SiteEvent.Severity.CRITICAL,
               f"{label} robots.txt now blocks all crawlers")
    if prev["sitemap_status"] == "found" and report.sitemap_status == "missing":
        _alert(SiteEvent.EventType.SEO_SITEMAP_MISSING, SiteEvent.Severity.WARNING,
               f"{label} sitemap is no longer reachable")

    # On-page meta change detection. Only compare fields that have ever been
    # populated (skips the transition from a never-captured blank to a value).
    meta_fields = [
        ("meta_title", "title"),
        ("meta_description", "meta description"),
        ("h1", "H1"),
        ("canonical_url", "canonical URL"),
    ]
    changes = []
    for field, human in meta_fields:
        old, new = prev[field], getattr(report, field)
        if old and old != new:
            changes.append({"field": human, "old": old, "new": new})
    old_schema, new_schema = set(prev["schema_types"]), set(report.schema_types or [])
    if prev["schema_types"] and old_schema != new_schema:
        changes.append({
            "field": "schema types",
            "old": ", ".join(sorted(old_schema)) or "—",
            "new": ", ".join(sorted(new_schema)) or "—",
        })
    if changes:
        what = ", ".join(c["field"] for c in changes)
        SiteEvent.objects.create(
            website=website,
            event_type=SiteEvent.EventType.SEO_META_CHANGED,
            severity=SiteEvent.Severity.WARNING,
            summary=f"{label} on-page SEO changed: {what}",
            details={"changes": changes},
        )
        notify_team(
            website,
            f"[Digivault] {label} on-page SEO changed: {what}",
            f"On-page SEO changed on {website.domain}: {what}",
        )


@shared_task(name="site_health.run_security_header_check")
def run_security_header_check(website_id: str) -> None:
    """Fetch the website homepage and grade its HTTP security headers."""
    from apps.site_health import header_checker, seo_checker
    from apps.site_health.models import SecurityHeaderReport
    from apps.websites.models import Website

    try:
        website = Website.objects.get(pk=website_id)
    except Website.DoesNotExist:
        return

    report, _ = SecurityHeaderReport.objects.get_or_create(website=website)
    report.check_status = "running"
    report.error = ""
    report.save(update_fields=["check_status", "error"])

    domain = website.domain if website.domain.startswith("http") else f"https://{website.domain}"
    base = domain.rstrip("/") + "/"

    try:
        status_code, _body, headers = seo_checker.fetch(base)
        result = header_checker.grade_headers(headers)
        report.final_url = base
        report.status_code = status_code
        report.score = result["score"]
        report.grade = result["grade"]
        report.headers = result["headers"]
        report.pass_count = result["pass_count"]
        report.warn_count = result["warn_count"]
        report.fail_count = result["fail_count"]
        report.check_status = "done"
        report.last_checked_at = timezone.now()
        report.save()
    except Exception as exc:
        logger.exception("run_security_header_check failed for %s", website_id)
        report.check_status = "failed"
        report.error = str(exc)[:500]
        report.save(update_fields=["check_status", "error"])


@shared_task(name="site_health.run_due_seo_checks")
def run_due_seo_checks() -> int:
    from apps.site_health.models import SeoReport
    from apps.websites.models import Website

    now = timezone.now()
    enqueued = 0
    for w in Website.objects.exclude(seo_scan_interval_days=0).iterator():
        report = SeoReport.objects.filter(website=w).first()
        due = (
            report is None
            or report.last_checked_at is None
            or report.last_checked_at + timezone.timedelta(days=w.seo_scan_interval_days) <= now
        )
        if due:
            run_seo_check.delay(str(w.pk))
            enqueued += 1
    return enqueued
