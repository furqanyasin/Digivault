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

        state.last_scanned_at = timezone.now()
        state.scan_status = "done"
        state.save(update_fields=["last_scanned_at", "scan_status", "plugins_detected"])
        website.recalculate_health_score()

    except Exception as exc:
        logger.exception("Security scan failed for website %s", website_id)
        state.scan_status = "failed"
        state.error = str(exc)
        state.save(update_fields=["scan_status", "error"])


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
