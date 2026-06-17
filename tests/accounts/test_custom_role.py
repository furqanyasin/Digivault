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
        {"role": "custom", "feature_access": ["websites", "reports", "bogus"]},
        format="json",
    )
    assert resp.status_code == 200, resp.data
    member.refresh_from_db()
    assert member.role == "custom"
    # Unknown keys are dropped.
    assert set(member.feature_access) == {"websites", "reports"}


@pytest.mark.django_db
def test_switching_off_custom_clears_features(auth_client, team, member):
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
    assert member.feature_access == []


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
