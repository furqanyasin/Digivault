"""Form-error importance filtering and PII sanitisation.

Pure functions, no DB access — used by the form-error ingest endpoint to
decide what to store and to scrub anything sensitive before it lands at rest.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# A message is stored only if it matches one of these — server-side failures
# the agency must act on, not user typos.
IMPORTANT_FORM_ERROR_KEYWORDS = (
    "submission failed",
    "failed to send",
    "could not be sent",
    "could not send",
    "server error",
    "internal error",
    "mail failed",
    "smtp",
    "try again later",
    "error occurred",
    "500",
    "502",
    "503",
    "504",
)

# Pure user-validation noise — never important on its own.
_NOISE_KEYWORDS = (
    "is required",
    "field is required",
    "please fill",
    "invalid email",
    "valid email",
    "must be",
    "too short",
    "too long",
    "captcha",
    "please verify",
)

# Query params whose values may identify a person or grant access.
_SENSITIVE_PARAMS = {"email", "token", "key", "password", "phone", "code", "auth", "session"}

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
# password=..., token=... style fragments leaking into status text
_KV_SECRET_RE = re.compile(r"(?i)\b(password|token|secret|key|auth)\s*[=:]\s*\S+")
# Long digit runs (7+) — phone numbers, order ids with PII risk
_DIGITS_RE = re.compile(r"\d{7,}")


def is_important_form_error(message: str) -> bool:
    """True when the failure text indicates a server-side problem."""
    if not message:
        return False
    lower = message.lower()
    if any(k in lower for k in IMPORTANT_FORM_ERROR_KEYWORDS):
        return True
    return False


def is_validation_noise(message: str) -> bool:
    lower = (message or "").lower()
    return any(k in lower for k in _NOISE_KEYWORDS)


def sanitize_page_url(url: str) -> str:
    """Redact sensitive query-string values; keep the page identity intact."""
    if not url:
        return ""
    try:
        parts = urlsplit(url)
    except ValueError:
        return url[:500]
    if not parts.query:
        return url
    cleaned = [
        (k, "[hidden]" if k.lower() in _SENSITIVE_PARAMS else v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
    ]
    return urlunsplit(parts._replace(query=urlencode(cleaned)))


def sanitize_error_message(text: str) -> str:
    """Scrub emails, secret-looking key=value pairs and long digit runs."""
    if not text:
        return ""
    text = _EMAIL_RE.sub("[hidden]", text)
    text = _KV_SECRET_RE.sub(lambda m: f"{m.group(1)}=[hidden]", text)
    text = _DIGITS_RE.sub("[hidden]", text)
    return text.strip()[:500]
