"""Custom per-member feature access."""

import pytest

from apps.accounts.models import TeamMembership, User


@pytest.fixture
def member(team):
    u = User.objects.create_user(email="member@example.com", password="SecurePass1!")
    return TeamMembership.objects.create(user=u, team=team, role="developer")


@pytest.mark.django_db
def test_set_custom_role_sanitizes_features(auth_client, team, member):
    resp = auth_client.patch(
        f"/api/v1/auth/teams/{team.id}/members/{member.id}/",
        {"role": "custom", "feature_access": ["websites", "alerts", "bogus"]},
        format="json",
    )
    assert resp.status_code == 200, resp.data
    member.refresh_from_db()
    assert member.role == "custom"
    # Unknown keys are dropped.
    assert set(member.feature_access) == {"websites", "alerts"}


@pytest.mark.django_db
def test_role_change_applies_default_preset(auth_client, team, member):
    """Changing role without feature_access seeds that role's default preset
    (feature access now applies to every role, not just custom)."""
    from apps.accounts.features import default_features

    member.role = "custom"
    member.feature_access = ["websites"]
    member.save()

    resp = auth_client.patch(
        f"/api/v1/auth/teams/{team.id}/members/{member.id}/",
        {"role": "developer"},
        format="json",
    )
    assert resp.status_code == 200, resp.data
    member.refresh_from_db()
    assert member.role == "developer"
    assert set(member.feature_access) == set(default_features("developer"))


@pytest.mark.django_db
def test_feature_access_editable_for_non_custom_role(auth_client, team, member):
    """A non-custom member's feature_access can be overridden directly."""
    resp = auth_client.patch(
        f"/api/v1/auth/teams/{team.id}/members/{member.id}/",
        {"role": "developer", "feature_access": ["websites", "alerts"]},
        format="json",
    )
    assert resp.status_code == 200, resp.data
    member.refresh_from_db()
    assert member.role == "developer"
    assert set(member.feature_access) == {"websites", "alerts"}


@pytest.mark.django_db
def test_heatmap_is_grantable(auth_client, team, member):
    """Heatmap is a real section key, not an always-on nav item: it survives
    sanitizing and ships in every non-custom role's default preset."""
    from apps.accounts.features import default_features

    assert "heatmap" in default_features("viewer")
    assert "heatmap" in default_features("manager")
    assert "heatmap" not in default_features("custom")

    resp = auth_client.patch(
        f"/api/v1/auth/teams/{team.id}/members/{member.id}/",
        {"role": "custom", "feature_access": ["heatmap"]},
        format="json",
    )
    assert resp.status_code == 200, resp.data
    member.refresh_from_db()
    assert member.feature_access == ["heatmap"]


@pytest.mark.django_db
def test_heatmap_backfill_spares_fine_tuned_members(team, member):
    """The 0012 backfill exists so adding a key doesn't silently revoke Heatmap
    from anyone a manager had already fine-tuned. Custom members are left alone —
    everything they hold was granted one chip at a time."""
    import importlib

    from django.apps import apps as django_apps

    migration = importlib.import_module(
        "apps.accounts.migrations.0012_backfill_heatmap_feature"
    )

    member.feature_access = ["websites", "alerts"]
    member.save()

    custom_user = User.objects.create_user(email="c@example.com", password="SecurePass1!")
    custom = TeamMembership.objects.create(
        user=custom_user, team=team, role="custom", feature_access=["websites"]
    )
    # Legacy row: an empty list means "fall back to the role default", which
    # already includes heatmap. Writing to it would freeze the default in place.
    legacy_user = User.objects.create_user(email="l@example.com", password="SecurePass1!")
    legacy = TeamMembership.objects.create(
        user=legacy_user, team=team, role="viewer", feature_access=[]
    )

    migration.add_heatmap(django_apps, None)

    member.refresh_from_db()
    custom.refresh_from_db()
    legacy.refresh_from_db()
    assert set(member.feature_access) == {"websites", "alerts", "heatmap"}
    assert custom.feature_access == ["websites"]
    assert legacy.feature_access == []


@pytest.mark.django_db
def test_team_serializer_exposes_my_features(team):
    """my_features reflects the requesting user's own membership."""
    from apps.accounts.serializers import TeamSerializer

    owner_membership = team.memberships.get(role="owner")
    owner_membership.role = "custom"
    owner_membership.feature_access = ["clients", "alerts"]
    owner_membership.save()

    class _Req:
        def __init__(self, u):
            self.user = u

    data = TeamSerializer(team, context={"request": _Req(owner_membership.user)}).data
    assert data["my_role"] == "custom"
    assert set(data["my_features"]) == {"clients", "alerts"}
