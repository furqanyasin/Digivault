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

    # Brand palette (kept in sync with the frontend's indigo accent).
    _BRAND = "#4F46E5"
    _INK = "#111827"
    _MUTED = "#6B7280"
    _RULE = "#E5E7EB"
    _SEVERITY_COLORS = {
        "critical": "#DC2626",
        "high": "#EA580C",
        "medium": "#D97706",
        "low": "#2563EB",
    }

    @staticmethod
    def render_pdf(data: dict) -> bytes:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER, TA_RIGHT
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.pdfgen import canvas as _canvas
        from reportlab.platypus import (
            ListFlowable,
            ListItem,
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )

        site = data["website"]
        period = data["period"]
        brand = colors.HexColor(ReportBuilder._BRAND)
        muted = colors.HexColor(ReportBuilder._MUTED)
        rule = colors.HexColor(ReportBuilder._RULE)

        LM = RM = 1.8 * cm
        generated = timezone.localtime(timezone.now()).strftime("%d %b %Y · %H:%M %Z").strip()
        header_title = "Website Monitoring & Security Report"
        header_domain = site["domain"]

        # --- Per-page header + footer, drawn via a two-pass canvas so the ---
        # --- footer can show "Page X of Y". ---------------------------------
        class _ReportCanvas(_canvas.Canvas):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self._saved = []

            def showPage(self):  # noqa: N802 (reportlab API)
                self._saved.append(dict(self.__dict__))
                self._startPage()

            def save(self):
                total = len(self._saved)
                for state in self._saved:
                    self.__dict__.update(state)
                    self._draw_furniture(total)
                    super().showPage()
                super().save()

            def _draw_furniture(self, total):
                w, h = A4
                # Header: brand bar + wordmark + report title/domain.
                self.setFillColor(brand)
                self.rect(0, h - 0.18 * cm, w, 0.18 * cm, stroke=0, fill=1)
                self.setFont("Helvetica-Bold", 13)
                self.drawString(LM, h - 1.25 * cm, "DIGIVAULT")
                self.setFont("Helvetica", 8)
                self.setFillColor(muted)
                self.drawRightString(w - RM, h - 1.05 * cm, header_title)
                self.drawRightString(w - RM, h - 1.45 * cm, header_domain)
                self.setStrokeColor(rule)
                self.setLineWidth(0.5)
                self.line(LM, h - 1.75 * cm, w - RM, h - 1.75 * cm)
                # Footer: rule + generated / domain / page numbers + notice.
                self.line(LM, 1.5 * cm, w - RM, 1.5 * cm)
                self.setFont("Helvetica", 7.5)
                self.setFillColor(muted)
                self.drawString(LM, 1.15 * cm, f"Generated {generated}")
                self.drawCentredString(w / 2, 1.15 * cm, header_domain)
                self.drawRightString(
                    w - RM, 1.15 * cm, f"Page {self._pageNumber} of {total}"
                )
                self.drawString(
                    LM, 0.8 * cm,
                    "Confidential — prepared by Digivault for the named recipient only.",
                )

        # --- Bookmarks: register an outline entry for each section heading, ---
        # --- making the PDF navigable from the viewer's sidebar. -------------
        class _BookmarkDoc(SimpleDocTemplate):
            def afterFlowable(self, flowable):
                if isinstance(flowable, Paragraph) and flowable.style.name == "Section":
                    text = flowable.getPlainText()
                    key = f"sec-{id(flowable)}"
                    self.canv.bookmarkPage(key)
                    self.canv.addOutlineEntry(text, key, level=0)

        buf = io.BytesIO()
        doc = _BookmarkDoc(
            buf,
            pagesize=A4,
            title=f"Digivault Report — {site['name']}",
            author="Digivault",
            leftMargin=LM,
            rightMargin=RM,
            topMargin=2.3 * cm,
            bottomMargin=2.0 * cm,
        )

        base = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "ReportTitle", parent=base["Title"], fontSize=20,
            textColor=colors.HexColor(ReportBuilder._INK), spaceAfter=2,
        )
        subtitle_style = ParagraphStyle(
            "ReportSubtitle", parent=base["Normal"], fontSize=10, textColor=muted,
        )
        section_style = ParagraphStyle(
            "Section", parent=base["Heading2"], fontSize=13,
            textColor=brand, spaceBefore=14, spaceAfter=6,
        )
        body_style = ParagraphStyle("Body", parent=base["Normal"], fontSize=9.5, leading=13)

        story = []

        # Title block
        story.append(Paragraph(f"{site['name']}", title_style))
        domain_link = f'<link href="https://{site["domain"]}" color="{ReportBuilder._BRAND}">{site["domain"]}</link>'
        story.append(Paragraph(
            f'{domain_link} &nbsp;·&nbsp; Reporting period {period["start"]} to {period["end"]}',
            subtitle_style,
        ))
        story.append(Spacer(1, 0.5 * cm))

        def styled_table(rows, col_widths, header=False):
            t = Table(rows, hAlign="LEFT", colWidths=col_widths)
            cmds = [
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 9.5),
                ("TEXTCOLOR", (0, 0), (0, -1), muted),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("LINEBELOW", (0, 0), (-1, -2), 0.5, rule),
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FBFBFE")),
            ]
            if header:
                cmds += [
                    ("BACKGROUND", (0, 0), (-1, 0), brand),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ]
            t.setStyle(TableStyle(cmds))
            return t

        # Overview
        story.append(Paragraph("Overview", section_style))
        story.append(styled_table(
            [
                ["Health score", f"{site['health_score']} / 100"],
                ["Status", str(site["status"]).title()],
                ["Platform", site["platform"] or "—"],
                ["Script changes (period)", str(data["script_changes"]["total"])],
                ["PHP errors (period)", str(data["security"]["php_errors"])],
            ],
            [6 * cm, 9 * cm],
        ))

        # Script changes
        story.append(Paragraph("Script Changes", section_style))
        by_type = data["script_changes"]["by_type"]
        if by_type:
            rows = [["Change type", "Count"]] + [
                [str(ct).replace("_", " ").title(), str(n)] for ct, n in by_type.items()
            ]
            story.append(styled_table(rows, [9 * cm, 6 * cm], header=True))
        else:
            story.append(Paragraph("No script changes recorded this period.", body_style))

        high_risk = data["script_changes"].get("high_risk") or []
        if high_risk:
            story.append(Spacer(1, 0.3 * cm))
            story.append(Paragraph("High-risk changes", ParagraphStyle(
                "Sub", parent=body_style, fontName="Helvetica-Bold")))
            hr_rows = [["Severity", "Type", "Description"]]
            for hr in high_risk:
                sev = str(hr.get("severity", "")).lower()
                color = ReportBuilder._SEVERITY_COLORS.get(sev, ReportBuilder._MUTED)
                hr_rows.append([
                    Paragraph(f'<font color="{color}"><b>{sev.title()}</b></font>', body_style),
                    str(hr.get("change_type", "")).replace("_", " ").title(),
                    Paragraph(hr.get("description") or "—", body_style),
                ])
            story.append(styled_table(hr_rows, [2.6 * cm, 3 * cm, 9.4 * cm], header=True))

        # Performance
        if data["performance"]:
            story.append(Paragraph("Performance", section_style))
            perf_rows = [["Strategy", "Performance score", "LCP"]]
            for p in data["performance"]:
                score = p.get("performance_score")
                lcp = p.get("lcp_ms")
                perf_rows.append([
                    str(p["strategy"]).title(),
                    "—" if score is None else f"{score} / 100",
                    "—" if lcp is None else f"{lcp:,} ms",
                ])
            story.append(styled_table(perf_rows, [5 * cm, 5 * cm, 5 * cm], header=True))

        # Security
        story.append(Paragraph("Security", section_style))
        vulns = data["security"]["vulnerabilities_by_severity"]
        if vulns:
            sev_rows = [["Severity", "Findings"]]
            for sev in ("critical", "high", "medium", "low"):
                if sev in vulns:
                    color = ReportBuilder._SEVERITY_COLORS.get(sev, ReportBuilder._MUTED)
                    sev_rows.append([
                        Paragraph(f'<font color="{color}"><b>{sev.title()}</b></font>', body_style),
                        str(vulns[sev]),
                    ])
            story.append(styled_table(sev_rows, [9 * cm, 6 * cm], header=True))
        else:
            story.append(Paragraph(
                "No known vulnerabilities matched the detected plugins.", body_style))

        # Domain & SSL
        if data["domain"]:
            dom = data["domain"]
            story.append(Paragraph("Domain & SSL", section_style))
            story.append(styled_table(
                [
                    ["Registrar", dom.get("registrar") or "—"],
                    ["Hosting provider", dom.get("hosting_provider") or "—"],
                    ["Domain expires in", f"{dom.get('domain_days_until_expiry')} days"],
                    ["SSL expires in", f"{dom.get('ssl_days_until_expiry')} days"],
                ],
                [6 * cm, 9 * cm],
            ))

        # Recommendations
        story.append(Paragraph("Recommendations", section_style))
        story.append(ListFlowable(
            [ListItem(Paragraph(r, body_style), leftIndent=12) for r in data["recommendations"]],
            bulletType="bullet",
            bulletColor=brand,
        ))

        doc.build(story, canvasmaker=_ReportCanvas)
        return buf.getvalue()
