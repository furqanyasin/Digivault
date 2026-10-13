"""Production settings must refuse the silent console email backend.

With EMAIL_URL unset, base settings fall back to consolemail:// — send_mail()
reports success while every onboarding / password-reset email is discarded.
Production must fail fast instead of booting in that state.
"""

import importlib
import sys

import pytest
from django.core.exceptions import ImproperlyConfigured


def _import_production(monkeypatch, email_url):
    monkeypatch.setenv("ALLOWED_HOSTS", "stacksmonitor.com")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://stacksmonitor.com")
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    if email_url is None:
        monkeypatch.delenv("EMAIL_URL", raising=False)
    else:
        monkeypatch.setenv("EMAIL_URL", email_url)
    sys.modules.pop("config.settings.production", None)
    try:
        return importlib.import_module("config.settings.production")
    finally:
        sys.modules.pop("config.settings.production", None)


class TestProductionEmailGuard:
    def test_missing_email_url_refuses_to_boot(self, monkeypatch):
        with pytest.raises(ImproperlyConfigured, match="EMAIL_URL"):
            _import_production(monkeypatch, None)

    def test_consolemail_refuses_to_boot(self, monkeypatch):
        with pytest.raises(ImproperlyConfigured, match="EMAIL_URL"):
            _import_production(monkeypatch, "consolemail://")

    def test_real_smtp_url_boots(self, monkeypatch):
        mod = _import_production(
            monkeypatch, "smtp+tls://user%40smtp-brevo.com:key@smtp-relay.brevo.com:587"
        )
        assert mod.DEBUG is False
