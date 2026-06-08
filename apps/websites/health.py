"""Website Health Center aggregation (Phase 2.1).

Pulls a single health snapshot together from existing models, including a
derived security score. Read-only — no DB writes.
"""

from __future__ import annotations

from datetime import timedelta

from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Count
from django.utils import timezone


def _security_score(vuln_counts: dict, php_errors: int, ssl_days) -> int:
    """0–100 security score derived from vulnerabilities, PHP errors, SSL."""
    deductions = 0
    deductions += min(vuln_counts.get("critical", 0) * 25, 50)
    deductions += min(vuln_counts.get("high", 0) * 10, 30)
    deductions += min(vuln_counts.get("medium", 0) * 3, 15)
    deductions += min(php_errors, 10)
    if ssl_days is not None and ssl_days <= 14:
        deductions += 15
    return max(0, min(100, 100 - deductions))


def build_health_snapshot(website) -> dict:
    """Assemble the full health picture for a website."""
    from apps.performance.models import PerformanceReport
    from apps.scripts.models import Script, ScriptChange
    from apps.site_health.models import PhpError, VulnerabilityReport

    # Scripts
    active_count = Script.objects.filter(website=website, is_active=True).count()
    pending = ScriptChange.objects.filter(website=website, acknowledged_at__isnull=True)
    pending_count = pending.count()
    high_risk_pending = pending.filter(severity__in=["critical", "high"]).count()

    # Domain / SSL
    domain = None
    ssl_days = None
    try:
        di = website.domain_info
        ssl_days = di.ssl_days_until_expiry
        domain = {
            "registrar": di.registrar,
            "hosting_provider": di.hosting_provider,
            "domain_days_until_expiry": di.domain_days_until_expiry,
            "ssl_days_until_expiry": ssl_days,
        }
    except ObjectDoesNotExist:
        domain = None

    # Performance — latest per strategy
    performance = []
    for strategy in ("mobile", "desktop"):
        latest = (
            PerformanceReport.objects.filter(website=website, strategy=strategy)
            .order_by("-checked_at")
            .first()
        )
        if latest:
            performance.append(
                {"strategy": strategy, "performance_score": latest.performance_score}
            )

    # Security
    vuln_counts = {
        row["severity"]: row["n"]
        for row in VulnerabilityReport.objects.filter(website=website)
        .values("severity")
        .annotate(n=Count("id"))
    }
    php_errors_30d = PhpError.objects.filter(
        website=website, captured_at__gte=timezone.now() - timedelta(days=30)
    ).count()
    security_score = _security_score(vuln_counts, php_errors_30d, ssl_days)

    return {
        "website_id": str(website.id),
        "domain": website.domain,
        "status": website.status,
        "health_score": website.health_score,
        "security": {
            "score": security_score,
            "vulnerabilities_by_severity": vuln_counts,
            "php_errors_30d": php_errors_30d,
        },
        "domain_info": domain,
        "performance": performance,
        "scripts": {
            "active_count": active_count,
            "pending_changes": pending_count,
            "high_risk_pending": high_risk_pending,
        },
    }
