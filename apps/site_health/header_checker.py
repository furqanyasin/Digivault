"""HTTP security-header validation + grading.

`grade_headers` is a pure, network-free function (testable in isolation). It
takes a case-insensitive dict of response headers and returns a structured
report: per-header status + an overall weighted score and letter grade.

The fetch lives in `seo_checker.fetch`, which already enforces SSRF guards.
"""
from __future__ import annotations

# Each header carries a weight (sum = 100) used for the overall score. `check`
# takes (value, all_headers) and returns ("pass" | "warn" | "fail", value,
# recommendation). A "warn" earns half the weight — the header is present but
# weaker than recommended. Most checks only need their own value; the full dict
# is passed so a check can consider related headers (see `_csp` and Report-Only).
#
# Header name keys are stored lowercase to match `seo_checker.fetch`, which
# lowercases header names.


def _hsts(value: str | None, headers: dict):
    if not value:
        return "fail", "", "Add Strict-Transport-Security to force HTTPS and prevent SSL-stripping."
    v = value.lower()
    max_age = 0
    for part in v.split(";"):
        part = part.strip()
        if part.startswith("max-age="):
            try:
                max_age = int(part.split("=", 1)[1])
            except ValueError:
                max_age = 0
    if max_age < 15552000:  # < 180 days
        return "warn", value, "Increase max-age to at least 6 months (15552000) and add includeSubDomains."
    if "includesubdomains" not in v:
        return "warn", value, "Add includeSubDomains so subdomains are also protected."
    return "pass", value, ""


def _csp(value: str | None, headers: dict):
    if not value:
        # Stacks Monitor's own fix guide tells operators to deploy a starter policy in
        # Report-Only first and read the violation reports. Grading that as a flat
        # failure would contradict our own advice, so it earns partial credit —
        # the site is mid-rollout, not unprotected by neglect.
        if headers.get("content-security-policy-report-only"):
            return (
                "warn",
                "",
                "Report-Only CSP found: violations are being reported but nothing is blocked yet. "
                "Once the reports are clean, send the same policy as Content-Security-Policy to enforce it.",
            )
        return "fail", "", "Add a Content-Security-Policy to mitigate XSS and data-injection attacks."
    v = value.lower()
    if "unsafe-inline" in v or "unsafe-eval" in v:
        return "warn", value, "Policy allows 'unsafe-inline'/'unsafe-eval' — tighten to use nonces or hashes."
    if "default-src" not in v and "script-src" not in v:
        return "warn", value, "Define a default-src or script-src directive to restrict script sources."
    return "pass", value, ""


def _x_frame(value: str | None, headers: dict):
    if not value:
        return "fail", "", "Add X-Frame-Options: SAMEORIGIN (or a CSP frame-ancestors) to prevent clickjacking."
    v = value.strip().upper()
    if v in ("DENY", "SAMEORIGIN") or v.startswith("ALLOW-FROM"):
        return "pass", value, ""
    return "warn", value, "Use DENY or SAMEORIGIN."


def _x_content_type(value: str | None, headers: dict):
    if not value:
        return "fail", "", "Add X-Content-Type-Options: nosniff to stop MIME-type sniffing."
    if value.strip().lower() == "nosniff":
        return "pass", value, ""
    return "warn", value, "Value should be exactly 'nosniff'."


def _referrer_policy(value: str | None, headers: dict):
    if not value:
        return "fail", "", "Add a Referrer-Policy (e.g. strict-origin-when-cross-origin) to limit referrer leakage."
    weak = {"unsafe-url", "no-referrer-when-downgrade", ""}
    if value.strip().lower() in weak:
        return "warn", value, "Use a stricter policy such as strict-origin-when-cross-origin."
    return "pass", value, ""


def _permissions_policy(value: str | None, headers: dict):
    if not value:
        return "fail", "", "Add a Permissions-Policy to disable unused browser features (camera, geolocation, etc.)."
    return "pass", value, ""


def _coop(value: str | None, headers: dict):
    # Optional by design, and the recommendation is deliberately allow-popups:
    # plain same-origin severs window.opener, which breaks Google/Microsoft/
    # Facebook sign-in and Stripe and PayPal popup checkouts.
    if not value:
        return (
            "warn",
            "",
            "Optional: Cross-Origin-Opener-Policy: same-origin-allow-popups isolates the browsing "
            "context while keeping third-party sign-in and payment popups working. Test those flows first.",
        )
    if value.strip().lower() in ("same-origin", "same-origin-allow-popups"):
        return "pass", value, ""
    return "warn", value, "Use same-origin-allow-popups (or same-origin if the site opens no third-party popups)."


# (header key, display label, weight, check fn)
_CHECKS = [
    ("strict-transport-security", "HSTS (Strict-Transport-Security)", 25, _hsts),
    ("content-security-policy", "Content-Security-Policy", 25, _csp),
    ("x-frame-options", "X-Frame-Options", 15, _x_frame),
    ("x-content-type-options", "X-Content-Type-Options", 10, _x_content_type),
    ("referrer-policy", "Referrer-Policy", 10, _referrer_policy),
    ("permissions-policy", "Permissions-Policy", 10, _permissions_policy),
    ("cross-origin-opener-policy", "Cross-Origin-Opener-Policy", 5, _coop),
]

_SCORE_WEIGHT = {"pass": 1.0, "warn": 0.5, "fail": 0.0}


def grade(score: int) -> str:
    """Map a 0–100 score to a letter grade."""
    if score >= 95:
        return "A+"
    if score >= 85:
        return "A"
    if score >= 70:
        return "B"
    if score >= 55:
        return "C"
    if score >= 40:
        return "D"
    return "F"


def grade_headers(headers: dict) -> dict:
    """Grade a set of response headers.

    `headers` keys are matched case-insensitively. Returns:
        {
          "score": int 0-100,
          "grade": "A+".."F",
          "headers": [ {name, key, present, status, value, recommendation, weight}, ... ],
          "pass_count": int, "warn_count": int, "fail_count": int,
        }
    """
    lower = {str(k).lower(): v for k, v in (headers or {}).items()}
    results = []
    earned = 0.0
    total = 0
    counts = {"pass": 0, "warn": 0, "fail": 0}
    for key, label, weight, fn in _CHECKS:
        raw = lower.get(key)
        status, value, recommendation = fn(raw, lower)
        earned += weight * _SCORE_WEIGHT[status]
        total += weight
        counts[status] += 1
        results.append({
            "name": label,
            "key": key,
            "present": raw is not None,
            "status": status,
            "value": (value or "")[:500],
            "recommendation": recommendation,
            "weight": weight,
        })
    score = round(100 * earned / total) if total else 0
    return {
        "score": score,
        "grade": grade(score),
        "headers": results,
        "pass_count": counts["pass"],
        "warn_count": counts["warn"],
        "fail_count": counts["fail"],
    }
