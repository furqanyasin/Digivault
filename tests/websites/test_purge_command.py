"""The purge command runs against production, so its guard rails need tests.

Two failure modes matter more than the happy path: a dry run that deletes
anything, and a "delete the websites" run that leaves monitors behind still
checking (``Monitor.website`` is SET_NULL, so the cascade does not take them).
"""

import json

import pytest
from django.core.management import CommandError, call_command

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.monitors.models import Monitor
from apps.scripts.models import Script, ScriptSnapshot
from apps.websites.models import Website


@pytest.fixture
def team(db):
    owner = User.objects.create_user(email="owner@purge.com", password="SecurePass1!")
    return TeamService.create(name="Purge Team", owner=owner)


@pytest.fixture
def other_team(db):
    owner = User.objects.create_user(email="other@purge.com", password="SecurePass1!")
    return TeamService.create(name="Other Team", owner=owner)


def _site(team, domain, **kw):
    return Website.objects.create(team=team, name=domain, domain=domain, **kw)


@pytest.mark.django_db
def test_dry_run_deletes_nothing(team):
    _site(team, "alpha.test")
    _site(team, "beta.test")

    call_command("purge_websites_and_monitors")

    assert Website.objects.count() == 2
    assert Monitor.objects.count() == 2


@pytest.mark.django_db
def test_confirm_deletes_websites_and_their_monitors(team, tmp_path):
    _site(team, "alpha.test")
    _site(team, "beta.test")
    assert Monitor.objects.count() == 2

    call_command(
        "purge_websites_and_monitors",
        "--confirm",
        export=str(tmp_path / "out.json"),
    )

    assert Website.objects.count() == 0
    # The whole point: SET_NULL would have left these two behind, orphaned and
    # still claimed by run_due_checks.
    assert Monitor.objects.count() == 0


@pytest.mark.django_db
def test_cascade_takes_script_history(team, tmp_path):
    site = _site(team, "alpha.test")
    ScriptSnapshot.objects.create(website=site, page_url="https://alpha.test/", scripts_data=[])
    Script.objects.create(
        website=site, src_url="https://cdn.test/a.js", normalized_url="https://cdn.test/a.js"
    )

    call_command(
        "purge_websites_and_monitors", "--confirm", export=str(tmp_path / "out.json")
    )

    assert ScriptSnapshot.objects.count() == 0
    assert Script.objects.count() == 0


@pytest.mark.django_db
def test_team_scope_does_not_reach_other_teams(team, other_team, tmp_path):
    _site(team, "alpha.test")
    keep = _site(other_team, "keep.test")

    call_command(
        "purge_websites_and_monitors",
        "--confirm",
        team=team.slug,
        export=str(tmp_path / "out.json"),
    )

    assert list(Website.objects.values_list("pk", flat=True)) == [keep.pk]
    # A scoped run must not delete the other team's monitor either.
    assert Monitor.objects.filter(website=keep).exists()


@pytest.mark.django_db
def test_domain_filter_selects_only_matching_sites(team, tmp_path):
    _site(team, "shop.alpha.test")
    keep = _site(team, "beta.test")

    call_command(
        "purge_websites_and_monitors",
        "--confirm",
        domain=["alpha"],
        export=str(tmp_path / "out.json"),
    )

    assert list(Website.objects.values_list("pk", flat=True)) == [keep.pk]


@pytest.mark.django_db
def test_export_records_what_is_needed_to_re_add(team, tmp_path):
    _site(team, "alpha.test", platform=Website.Platform.WORDPRESS, is_vip=True,
          seo_scan_interval_days=3, notes="flagship")
    path = tmp_path / "out.json"

    call_command("purge_websites_and_monitors", "--confirm", export=str(path))

    data = json.loads(path.read_text(encoding="utf-8"))
    site = data["websites"][0]
    assert site["domain"] == "alpha.test"
    assert site["platform"] == "wordpress"
    assert site["is_vip"] is True
    assert site["seo_scan_interval_days"] == 3
    assert site["notes"] == "flagship"
    assert data["monitors"][0]["website_domain"] == "alpha.test"
    assert data["monitors"][0]["retry_count"] == 3


@pytest.mark.django_db
def test_monitors_only_keeps_websites_and_history(team, tmp_path):
    site = _site(team, "alpha.test")
    ScriptSnapshot.objects.create(website=site, page_url="https://alpha.test/", scripts_data=[])

    call_command("purge_websites_and_monitors", "--confirm", monitors_only=True)

    assert Monitor.objects.count() == 0
    assert Website.objects.count() == 1
    assert ScriptSnapshot.objects.count() == 1


@pytest.mark.django_db
def test_status_pages_are_kept_by_default(team, tmp_path):
    from apps.status_pages.models import StatusPage

    _site(team, "alpha.test")
    assert StatusPage.objects.count() == 1

    call_command(
        "purge_websites_and_monitors", "--confirm", export=str(tmp_path / "out.json")
    )

    # Kept so the public URL survives; re-adding re-attaches the new monitor.
    assert StatusPage.objects.count() == 1


@pytest.mark.django_db
def test_delete_status_pages_flag_removes_them(team, tmp_path):
    from apps.status_pages.models import StatusPage

    _site(team, "alpha.test")

    call_command(
        "purge_websites_and_monitors",
        "--confirm",
        delete_status_pages=True,
        export=str(tmp_path / "out.json"),
    )

    assert StatusPage.objects.count() == 0


@pytest.mark.django_db
def test_delete_status_pages_stays_inside_the_domain_scope(team, tmp_path):
    """Filtering pages by team instead of by slug reached outside the scope."""
    from apps.status_pages.models import StatusPage

    _site(team, "shop.alpha.test")
    _site(team, "beta.test")
    assert StatusPage.objects.count() == 2

    call_command(
        "purge_websites_and_monitors",
        "--confirm",
        domain=["alpha"],
        delete_status_pages=True,
        export=str(tmp_path / "out.json"),
    )

    remaining = list(StatusPage.objects.values_list("slug", flat=True))
    assert remaining == ["beta-test"]


@pytest.mark.django_db
def test_credentials_survive_unlinked(team, tmp_path):
    from apps.credentials.models import Credential

    site = _site(team, "alpha.test")
    cred = Credential.objects.create(
        team=team, website=site, label="wp-admin"
    )

    call_command(
        "purge_websites_and_monitors", "--confirm", export=str(tmp_path / "out.json")
    )

    cred.refresh_from_db()
    assert cred.website_id is None


@pytest.mark.django_db
def test_conflicting_scope_flags_are_rejected(team):
    with pytest.raises(CommandError):
        call_command(
            "purge_websites_and_monitors", websites_only=True, monitors_only=True
        )


@pytest.mark.django_db
def test_unknown_team_is_rejected(team):
    with pytest.raises(CommandError):
        call_command("purge_websites_and_monitors", team="no-such-team")


@pytest.mark.django_db
def test_unscoped_run_also_takes_standalone_monitors(team, tmp_path):
    """A monitor nobody attached to a website is exactly what gets left paging."""
    _site(team, "alpha.test")
    Monitor.objects.create(team=team, name="standalone", url="https://solo.test")

    call_command(
        "purge_websites_and_monitors", "--confirm", export=str(tmp_path / "out.json")
    )

    assert Monitor.objects.count() == 0
