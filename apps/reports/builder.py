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
    def gather(website, period_start: date, period_end: date, sections=None) -> dict:
        """Collect a website's report data for the [start, end] window.

        `sections` is an iterable of section keys (Report.SECTION_KEYS) to
        include; None or empty means all sections. "overview" is always
        gathered. Excluded sections skip their queries entirely.
        """
        from apps.reports.models import Report
        from apps.scripts.models import ScriptChange
        from apps.site_health.models import PhpError
        from apps.site_health.models import VulnerabilityReport
        from apps.performance.models import PerformanceReport

        included = set(sections) if sections else set(Report.SECTION_KEYS)

        start_dt = _as_dt(period_start)
        end_dt = _as_dt(period_end, end=True)

        # Script changes in the window
        change_counts: dict = {}
        high_risk: list = []
        if "script_changes" in included:
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

        # Active scripts currently running on the site, grouped by domain and
        # excluding Digivault's own infra (the tracking snippet) — matches the
        # website detail "Active Scripts" list.
        active_scripts: list = []
        if "active_scripts" in included:
            from apps.scripts.models import Script
            from apps.scripts.tasks import _internal_hosts

            internal = _internal_hosts()
            grouped: dict[str, dict] = {}
            for s in Script.objects.filter(website=website, is_active=True).order_by("provider", "src_domain"):
                blob = f"{s.src_url or ''} {s.src_domain or ''}".lower()
                if any(h in blob for h in internal):
                    continue
                key = (s.src_domain or s.src_url or "").lower()
                if key not in grouped:
                    grouped[key] = {
                        "domain": s.src_domain or s.src_url or "—",
                        "provider": s.provider,
                        "category": s.category,
                        "files": 0,
                    }
                grouped[key]["files"] += 1
            active_scripts = sorted(
                grouped.values(),
                key=lambda r: (r["provider"] == "unknown", r["provider"], r["domain"]),
            )

        # Domain / SSL
        domain = None
        if "domain_ssl" in included:
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

        # Uptime / downtime per monitor over the window
        uptime = []
        if "uptime" in included:
            from apps.monitors.models import Monitor, MonitorCheck

            for m in Monitor.objects.filter(website=website).order_by("name"):
                checks = MonitorCheck.objects.filter(
                    monitor=m, checked_at__gte=start_dt, checked_at__lte=end_dt
                )
                total = checks.count()
                up = checks.filter(status=MonitorCheck.Status.UP).count()
                down = checks.filter(status=MonitorCheck.Status.DOWN).count()
                uptime.append({
                    "name": m.name,
                    "url": m.url,
                    "status": m.status,
                    "uptime_pct": round(up / total * 100, 2) if total else None,
                    "checks": total,
                    "down_checks": down,
                })

        # Latest performance per strategy
        performance = []
        if "performance" in included:
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
        vuln_counts: dict = {}
        php_error_count = 0
        if "security" in included:
            vuln_counts = {
                row["severity"]: row["n"]
                for row in VulnerabilityReport.objects.filter(website=website)
                .values("severity")
                .annotate(n=Count("id"))
            }
            php_error_count = PhpError.objects.filter(
                website=website, captured_at__gte=start_dt, captured_at__lte=end_dt
            ).count()

        recommendations = (
            ReportBuilder._recommendations(domain, vuln_counts, high_risk)
            if "recommendations" in included
            else []
        )

        return {
            "sections": sorted(included),
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
            "scripts": {
                "active_total": sum(r["files"] for r in active_scripts),
                "active_domains": len(active_scripts),
                "active": active_scripts,
            },
            "script_changes": {
                "total": sum(change_counts.values()),
                "by_type": change_counts,
                "high_risk": high_risk,
            },
            "domain": domain,
            "performance": performance,
            "uptime": uptime,
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
    def _included(data: dict) -> set:
        from apps.reports.models import Report

        return set(data.get("sections") or Report.SECTION_KEYS)

    @staticmethod
    def render_csv(data: dict) -> str:
        inc = ReportBuilder._included(data)
        buf = io.StringIO()
        w = csv.writer(buf)
        site = data["website"]
        w.writerow(["Digivault Report", site["name"], site["domain"]])
        w.writerow(["Period", data["period"]["start"], data["period"]["end"]])
        w.writerow([])
        w.writerow(["Health score", site["health_score"]])
        w.writerow(["Status", site["status"]])
        w.writerow([])
        if "active_scripts" in inc:
            scripts = data.get("scripts", {})
            w.writerow(["Active scripts (total)", scripts.get("active_total", 0)])
            for s in scripts.get("active", []):
                w.writerow([f"  {s['provider']} — {s['domain']}", s.get("category") or "", "Active"])
            w.writerow([])
        if "script_changes" in inc:
            w.writerow(["Script changes (total)", data["script_changes"]["total"]])
            for ct, n in data["script_changes"]["by_type"].items():
                w.writerow([f"  {ct}", n])
            w.writerow([])
        if "uptime" in inc:
            w.writerow(["Uptime & Downtime"])
            w.writerow(["  Monitor", "Status", "Uptime %", "Checks", "Down checks"])
            for u in data.get("uptime", []):
                w.writerow([
                    f"  {u['name']}", u["status"],
                    "—" if u["uptime_pct"] is None else u["uptime_pct"],
                    u["checks"], u["down_checks"],
                ])
            w.writerow([])
        if "security" in inc:
            sec = data["security"]
            w.writerow(["PHP errors", sec["php_errors"]])
            for sev, n in sec["vulnerabilities_by_severity"].items():
                w.writerow([f"Vulnerabilities ({sev})", n])
            w.writerow([])
        if "domain_ssl" in inc and data.get("domain"):
            dom = data["domain"]
            w.writerow(["Registrar", dom.get("registrar") or ""])
            w.writerow(["Hosting provider", dom.get("hosting_provider") or ""])
            w.writerow(["Domain expires in (days)", dom.get("domain_days_until_expiry")])
            w.writerow(["SSL expires in (days)", dom.get("ssl_days_until_expiry")])
            w.writerow([])
        if "recommendations" in inc:
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

        inc = ReportBuilder._included(data)

        # Overview
        overview_rows = [
            ["Health score", f"{site['health_score']} / 100"],
            ["Status", str(site["status"]).title()],
            ["Platform", site["platform"] or "—"],
        ]
        if "active_scripts" in inc:
            overview_rows.append(["Active scripts", str(data.get("scripts", {}).get("active_total", 0))])
        if "script_changes" in inc:
            overview_rows.append(["Script changes (period)", str(data["script_changes"]["total"])])
        if "security" in inc:
            overview_rows.append(["PHP errors (period)", str(data["security"]["php_errors"])])
        story.append(Paragraph("Overview", section_style))
        story.append(styled_table(overview_rows, [6 * cm, 9 * cm]))

        # Active scripts
        if "active_scripts" in inc:
            story.append(Paragraph("Active Scripts", section_style))
            active = data.get("scripts", {}).get("active") or []
            if active:
                story.append(Paragraph(
                    f"{data['scripts']['active_total']} active script(s) across "
                    f"{data['scripts']['active_domains']} domain(s).", body_style))
                story.append(Spacer(1, 0.2 * cm))
                cap = 60
                as_rows = [["Provider", "Domain", "Category", "Status"]]
                for s in active[:cap]:
                    prov = s["provider"] if s["provider"] and s["provider"] != "unknown" else "—"
                    cat = s["category"] if s["category"] and s["category"] != "unknown" else "—"
                    as_rows.append([
                        Paragraph(str(prov), body_style),
                        Paragraph(str(s["domain"]), body_style),
                        Paragraph(str(cat).replace("_", " ").title(), body_style),
                        Paragraph('<font color="#16A34A"><b>Active</b></font>', body_style),
                    ])
                story.append(styled_table(as_rows, [4 * cm, 6 * cm, 3 * cm, 2 * cm], header=True))
                if len(active) > cap:
                    story.append(Paragraph(
                        f"… and {len(active) - cap} more active script domain(s).", body_style))
            else:
                story.append(Paragraph("No active third-party scripts detected.", body_style))

        # Script changes
        if "script_changes" in inc:
            story.append(Paragraph("Script Changes", section_style))
            by_type = data["script_changes"]["by_type"]
            if by_type:
                rows = [["Change type", "Count"]] + [
                    [str(ct).replace("_", " ").title(), str(n)] for ct, n in by_type.items()
                ]
                story.append(styled_table(rows, [9 * cm, 6 * cm], header=True))
            else:
                story.append(Paragraph("No script changes recorded this period.", body_style))

        # Performance
        if "performance" in inc and data["performance"]:
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

        # Uptime & Downtime
        if "uptime" in inc:
            story.append(Paragraph("Uptime & Downtime", section_style))
            monitors = data.get("uptime") or []
            if monitors:
                up_rows = [["Monitor", "Status", "Uptime", "Checks", "Down"]]
                for u in monitors:
                    up = u["status"] == "up"
                    color = "#16A34A" if up else ("#DC2626" if u["status"] == "down" else "#D97706")
                    pct = "—" if u["uptime_pct"] is None else f"{u['uptime_pct']}%"
                    up_rows.append([
                        Paragraph(str(u["name"]), body_style),
                        Paragraph(f'<font color="{color}"><b>{str(u["status"]).title()}</b></font>', body_style),
                        pct,
                        str(u["checks"]),
                        str(u["down_checks"]),
                    ])
                story.append(styled_table(up_rows, [5 * cm, 3 * cm, 3 * cm, 2 * cm, 2 * cm], header=True))
            else:
                story.append(Paragraph("No uptime monitors configured for this site.", body_style))

        # Security
        if "security" in inc:
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
        if "domain_ssl" in inc and data["domain"]:
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
        if "recommendations" in inc:
            story.append(Paragraph("Recommendations", section_style))
            story.append(ListFlowable(
                [ListItem(Paragraph(r, body_style), leftIndent=12) for r in data["recommendations"]],
                bulletType="bullet",
                bulletColor=brand,
            ))

        doc.build(story, canvasmaker=_ReportCanvas)
        return buf.getvalue()
