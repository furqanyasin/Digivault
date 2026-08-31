"""A site that rejects our credential is disarmed, not retried nightly.

Everything Digivault sends leaves from one IP. Repeated 401s against a client
origin is how that IP earns a ban, and the ban would take uptime monitoring with
it — a far more valuable signal than a recipient address.
"""

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.credentials.models import Credential
from apps.websites import wp_api_forms
from apps.websites.models import Website


@pytest.fixture
def team(db):
    owner = User.objects.create_user(email="wpaf_o@test.com", password="Pass123!")
    return TeamService.create(name="Auth Failure Agency", owner=owner)


@pytest.fixture
def website(team):
    return Website.objects.create(team=team, name="AF Site", domain="authfail.test")


def _wp_credential(team, website, password="wrong"):
    cred = Credential(
        team=team,
        website=website,
        label="wp",
        credential_type=Credential.CredentialType.WORDPRESS,
    )
    cred.set_username("admin")
    cred.set_password(password)
    cred.save()
    return cred


def _answer(monkeypatch, status, calls=None):
    def _fetch(site, path, credential, **kwargs):
        if calls is not None:
            calls.append(path)
        return None, status

    monkeypatch.setattr(wp_api_forms, "fetch_json", _fetch)


def test_a_401_is_recorded_on_the_website(team, website, monkeypatch):
    _wp_credential(team, website)
    _answer(monkeypatch, 401)

    assert wp_api_forms.sync_website(website) == 0

    website.refresh_from_db()
    assert website.wp_api_auth_failed_at is not None


def test_a_403_is_recorded_too(team, website, monkeypatch):
    _wp_credential(team, website)
    _answer(monkeypatch, 403)

    wp_api_forms.sync_website(website)

    website.refresh_from_db()
    assert website.wp_api_auth_failed_at is not None


def test_a_404_is_not_an_auth_failure(team, website, monkeypatch):
    """Gravity simply not being installed must not disarm the whole site."""
    _wp_credential(team, website)
    _answer(monkeypatch, 404)

    wp_api_forms.sync_website(website)

    website.refresh_from_db()
    assert website.wp_api_auth_failed_at is None


def test_a_disarmed_website_makes_no_requests(team, website, monkeypatch):
    _wp_credential(team, website)
    website.wp_api_auth_failed_at = timezone.now()
    website.save(update_fields=["wp_api_auth_failed_at"])

    calls: list[str] = []
    _answer(monkeypatch, 401, calls)

    assert wp_api_forms.sync_website(website) == 0
    assert calls == []


def test_correcting_the_credential_re_arms_the_site(team, website):
    cred = _wp_credential(team, website)
    website.wp_api_auth_failed_at = timezone.now()
    website.save(update_fields=["wp_api_auth_failed_at"])

    cred.set_password("the right one")
    cred.save()

    website.refresh_from_db()
    assert website.wp_api_auth_failed_at is None


def test_a_credential_for_another_service_does_not_re_arm(team, website):
    other = Credential(
        team=team,
        website=website,
        label="cpanel",
        credential_type=Credential.CredentialType.CPANEL,
    )
    other.set_username("root")
    other.set_password("first")
    other.save()

    website.wp_api_auth_failed_at = timezone.now()
    website.save(update_fields=["wp_api_auth_failed_at"])

    other.set_password("second")
    other.save()

    website.refresh_from_db()
    assert website.wp_api_auth_failed_at is not None
