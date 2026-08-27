"""Resolving a WordPress credential for an unattended read.

The sweep that reads a site's own REST API has no user, so this covers both
halves of that: which credential it picks, and the audit row it leaves behind.
"""

import pytest

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.credentials.models import Credential, CredentialAccessLog
from apps.credentials.wp_access import log_system_read, resolve_wp_credential
from apps.websites.models import Website


@pytest.fixture
def team(db):
    owner = User.objects.create_user(email="wpa_o@test.com", password="Pass123!")
    return TeamService.create(name="WP Access Agency", owner=owner)


@pytest.fixture
def website(team):
    return Website.objects.create(team=team, name="WP Site", domain="wpaccess.test")


def _credential(team, website, credential_type, username, password):
    cred = Credential(
        team=team, website=website, label="wp", credential_type=credential_type
    )
    cred.set_username(username)
    cred.set_password(password)
    cred.save()
    return cred


def test_returns_none_when_the_site_has_no_wordpress_credential(website):
    assert resolve_wp_credential(website) is None


def test_returns_the_wordpress_credential(website, team):
    _credential(team, website, Credential.CredentialType.WORDPRESS, "admin", "hunter2")

    got = resolve_wp_credential(website)

    assert got.username == "admin"
    assert got.password == "hunter2"
    assert got.is_app_password is False


def test_an_application_password_outranks_the_admin_login(website, team):
    _credential(team, website, Credential.CredentialType.WORDPRESS, "admin", "hunter2")
    _credential(
        team,
        website,
        Credential.CredentialType.WORDPRESS_APP_PASSWORD,
        "admin",
        "abcd efgh ijkl mnop qrst uvwx",
    )

    got = resolve_wp_credential(website)

    assert got.is_app_password is True
    assert got.password == "abcd efgh ijkl mnop qrst uvwx"


def test_a_credential_of_another_type_is_ignored(website, team):
    _credential(team, website, Credential.CredentialType.CPANEL, "root", "hunter2")

    assert resolve_wp_credential(website) is None


def test_a_credential_that_cannot_be_decrypted_is_skipped(website, team, monkeypatch):
    """A rotated key must degrade to "no credential", not crash the sweep."""
    _credential(team, website, Credential.CredentialType.WORDPRESS, "admin", "hunter2")

    def _boom(self):
        raise ValueError("bad key")

    monkeypatch.setattr(Credential, "get_password", _boom)

    assert resolve_wp_credential(website) is None


def test_a_system_read_is_audited_without_a_user(website, team):
    cred = _credential(
        team, website, Credential.CredentialType.WORDPRESS, "admin", "hunter2"
    )

    log_system_read(cred.pk)

    entry = CredentialAccessLog.objects.get(credential=cred)
    assert entry.user is None
    assert entry.action == CredentialAccessLog.Action.SYSTEM_READ
