"""Report data gathering + PDF/CSV rendering.

`gather()` is a pure read over existing models; `render_pdf`/`render_csv`
turn the gathered dict into bytes. No DB writes here.
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime, time

from django.db.models import Count
from django.utils import timezone


def _as_dt(d: date, end: bool = False):
    t = time.max if end else time.min
    naive = datetime.combine(d, t)
    return timezone.make_aware(naive) if timezone.is_aware(timezone.now()) else naive


class ReportBuilder:
    @staticmethod
    def gather(website, period_start: date, period_end: date) -> dict:
        """Collect a website's report data for the [start, end] window."""
        from apps.scripts.models import ScriptChange
        from apps.site_health.models import PhpError
        from apps.site_health.models import VulnerabilityReport
        from apps.performance.models import PerformanceReport

        start_dt = _as_dt(period_start)
        end_dt = _as_dt(period_end, end=True)

        # Script changes in the window
        changes = ScriptChange.objects.filter(
            website=website, created_at__gte=start_dt, created_at__lte=end_dt
        )
        change_counts = {
            row["change_type"]: row["n"]
            for row in changes.values("change_type").annotate(n=Count("id"))
        }
        high_risk = list(
            changes.filter(severity__in=["critical", "high"])
            .order_by("-created_at")
            .values("change_type", "severity", "description")[:20]
        )

        # Domain / SSL
        domain = None
        try:
            di = website.domain_info
            domain = {
                "registrar": di.registrar,
                "hosting_provider": di.hosting_provider,
                "domain_days_until_expiry": di.domain_days_until_expiry,
                "ssl_days_until_expiry": di.ssl_days_until_expiry,
            }
        except Exception:
            domain = None

        # Latest performance per strategy
        performance = []
        for strategy in ("mobile", "desktop"):
            latest = (
                PerformanceReport.objects.filter(website=website, strategy=strategy)
                .order_by("-checked_at")
                .first()
            )
            if latest:
                performance.append({
                    "strategy": strategy,
                    "performance_score": latest.performance_score,
                    "lcp_ms": latest.lcp_ms,
                })

        # Security
        vuln_counts = {
            row["severity"]: row["n"]
            for row in VulnerabilityReport.objects.filter(website=website)
            .values("severity")
            .annotate(n=Count("id"))
        }

        php_error_count = PhpError.objects.filter(
            website=website, captured_at__gte=start_dt, captured_at__lte=end_dt
        ).count()

        recommendations = ReportBuilder._recommendations(domain, vuln_counts, high_risk)

        return {
            "website": {
                "name": website.name,
                "domain": website.domain,
                "platform": website.platform,
                "status": website.status,
                "health_score": website.health_score,
            },
            "period": {
                "start": period_start.isoformat(),
                "end": period_end.isoformat(),
            },
            "script_changes": {
                "total": sum(change_counts.values()),
                "by_type": change_counts,
                "high_risk": high_risk,
            },
            "domain": domain,
            "performance": performance,
            "security": {
                "vulnerabilities_by_severity": vuln_counts,
                "php_errors": php_error_count,
            },
            "recommendations": recommendations,
        }

    @staticmethod
    def _recommendations(domain, vuln_counts, high_risk) -> list[str]:
        recs = []
        if domain:
            d = domain.get("domain_days_until_expiry")
            s = domain.get("ssl_days_until_expiry")
            if d is not None and d <= 30:
                recs.append(f"Domain expires in {d} days — renew soon.")
            if s is not None and s <= 30:
                recs.append(f"SSL certificate expires in {s} days — renew soon.")
        if vuln_counts.get("critical"):
            recs.append(
                f"{vuln_counts['critical']} critical vulnerability(ies) — patch immediately."
            )
        if vuln_counts.get("high"):
            recs.append(f"{vuln_counts['high']} high-severity vulnerability(ies) to review.")
        if high_risk:
            recs.append(f"{len(high_risk)} high-risk script change(s) need review.")
        if not recs:
            recs.append("No urgent issues detected this period.")
        return recs

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    @staticmethod
    def render_csv(data: dict) -> str:
        buf = io.StringIO()
        w = csv.writer(buf)
        site = data["website"]
        w.writerow(["Digivault Report", site["name"], site["domain"]])
        w.writerow(["Period", data["period"]["start"], data["period"]["end"]])
        w.writerow([])
        w.writerow(["Health score", site["health_score"]])
        w.writerow(["Status", site["status"]])
        w.writerow([])
        w.writerow(["Script changes (total)", data["script_changes"]["total"]])
        for ct, n in data["script_changes"]["by_type"].items():
            w.writerow([f"  {ct}", n])
        w.writerow([])
        sec = data["security"]
        w.writerow(["PHP errors", sec["php_errors"]])
        for sev, n in sec["vulnerabilities_by_severity"].items():
            w.writerow([f"Vulnerabilities ({sev})", n])
        w.writerow([])
        w.writerow(["Recommendations"])
        for rec in data["recommendations"]:
            w.writerow(["", rec])
        return buf.getvalue()

    @staticmethod
    def render_pdf(data: dict) -> bytes:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.platypus import (
            ListFlowable,
            ListItem,
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
        )

        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4, title="Digivault Report")
        styles = getSampleStyleSheet()
        story = []
        site = data["website"]

        story.append(Paragraph(f"Digivault Report — {site['name']}", styles["Title"]))
        story.append(Paragraph(
            f"{site['domain']} · {data['period']['start']} to {data['period']['end']}",
            styles["Normal"],
        ))
        story.append(Spacer(1, 0.6 * cm))

        overview = [
            ["Health score", str(site["health_score"])],
            ["Status", site["status"]],
            ["Platform", site["platform"]],
            ["Script changes", str(data["script_changes"]["total"])],
            ["PHP errors", str(data["security"]["php_errors"])],
        ]
        t = Table(overview, hAlign="LEFT", colWidths=[5 * cm, 8 * cm])
        story.append(t)
        story.append(Spacer(1, 0.6 * cm))

        if data["domain"]:
            story.append(Paragraph("Domain & SSL", styles["Heading2"]))
            dom = data["domain"]
            story.append(Paragraph(
                f"Registrar: {dom.get('registrar') or '—'} · "
                f"Domain expires in: {dom.get('domain_days_until_expiry')} days · "
                f"SSL expires in: {dom.get('ssl_days_until_expiry')} days",
                styles["Normal"],
            ))
            story.append(Spacer(1, 0.4 * cm))

        story.append(Paragraph("Recommendations", styles["Heading2"]))
        story.append(ListFlowable(
            [ListItem(Paragraph(r, styles["Normal"])) for r in data["recommendations"]],
            bulletType="bullet",
        ))

        doc.build(story)
        return buf.getvalue()
