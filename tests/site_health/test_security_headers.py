import pytest

from apps.site_health import header_checker, seo_checker
from apps.site_health.header_checker import grade, grade_headers
from apps.site_health.models import SecurityHeaderReport
from apps.site_health.tasks import run_security_header_check
from apps.websites.models import Website

# A fully-hardened set of response headers.
STRONG = {
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains; preload",
    "Content-Security-Policy": "default-src 'self'; script-src 'self'",
    "X-Frame-Options": "SAMEORIGIN",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=(), camera=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}


# ── pure grading function ───────────────────────────────────────────────

def test_strong_headers_score_perfect():
    result = grade_headers(STRONG)
    assert result["score"] == 100
    assert result["grade"] == "A+"
    assert result["fail_count"] == 0
    assert result["warn_count"] == 0
    assert result["pass_count"] == len(STRONG)


def test_no_headers_score_zero_grade_f():
    result = grade_headers({})
    # COOP is advisory: missing → "warn" (half of weight 5), everything else fails.
    assert result["score"] <= 5
    assert result["grade"] == "F"
    assert result["fail_count"] == 6
    assert result["warn_count"] == 1
    assert all(not h["present"] for h in result["headers"])
    assert all(h["recommendation"] for h in result["headers"])


def test_header_keys_matched_case_insensitively():
    # seo_checker.fetch lowercases header names; grading must still find them.
    lowered = {k.lower(): v for k, v in STRONG.items()}
    assert grade_headers(lowered)["score"] == 100


def test_weak_hsts_is_warn_not_pass():
    result = grade_headers({**STRONG, "Strict-Transport-Security": "max-age=600"})
    hsts = next(h for h in result["headers"] if h["key"] == "strict-transport-security")
    assert hsts["status"] == "warn"
    assert result["score"] < 100


def test_csp_with_unsafe_inline_is_warn():
    result = grade_headers({**STRONG, "Content-Security-Policy": "default-src 'self' 'unsafe-inline'"})
    csp = next(h for h in result["headers"] if h["key"] == "content-security-policy")
    assert csp["status"] == "warn"


def test_grade_thresholds():
    assert grade(100) == "A+"
    assert grade(95) == "A+"
    assert grade(90) == "A"
    assert grade(72) == "B"
    assert grade(60) == "C"
    assert grade(45) == "D"
    assert grade(10) == "F"


def test_value_is_truncated():
    long_csp = "default-src 'self'; " + "img-src example.com " * 100
    result = grade_headers({**STRONG, "Content-Security-Policy": long_csp})
    csp = next(h for h in result["headers"] if h["key"] == "content-security-policy")
    assert len(csp["value"]) <= 500


# ── celery task ─────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_run_security_header_check_grades_and_persists(monkeypatch, team):
    w = Website.objects.create(team=team, name="H", domain="hdr.example")
    monkeypatch.setattr(
        seo_checker, "fetch", lambda url, timeout=15: (200, "<html></html>", {k.lower(): v for k, v in STRONG.items()})
    )

    run_security_header_check(str(w.pk))

    r = SecurityHeaderReport.objects.get(website=w)
    assert r.check_status == "done"
    assert r.score == 100
    assert r.grade == "A+"
    assert r.status_code == 200
    assert r.final_url == "https://hdr.example/"
    assert len(r.headers) == 7


@pytest.mark.django_db
def test_run_security_header_check_handles_fetch_failure(monkeypatch, team):
    w = Website.objects.create(team=team, name="H", domain="hdr.example")

    def _boom(url, timeout=15):
        raise OSError("connection refused")

    monkeypatch.setattr(seo_checker, "fetch", _boom)
    run_security_header_check(str(w.pk))

    r = SecurityHeaderReport.objects.get(website=w)
    assert r.check_status == "failed"
    assert r.error
