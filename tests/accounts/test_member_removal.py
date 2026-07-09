"""Removing a member must revoke access; permanent delete removes the account.

TeamScopedMixin trusts user.active_team alone, so removal must clear a stale
active_team pointer and deactivate accounts with no team left — otherwise a
removed member keeps reading team data with a still-valid JWT.
"""

import pytest

from apps.accounts.models import Team, TeamMembership, User


def _add_member(team, email="member@example.com", role="developer"):
    u = User.objects.create_user(email=email, password="RealPass1!")
    m = TeamMembership.objects.create(user=u, team=team, role=role)
    User.objects.filter(pk=u.pk).update(active_team=team)
    u.refresh_from_db()
    return u, m


@pytest.mark.django_db
def test_remove_last_team_deactivates_and_clears_active_team(auth_client, team):
    member, membership = _add_member(team)

    resp = auth_client.delete(f"/api/v1/auth/teams/{team.id}/members/{membership.pk}/")
    assert resp.status_code == 204

    member.refresh_from_db()
    assert member.is_active is False
    assert member.active_team is None
    assert not TeamMembership.objects.filter(user=member).exists()


@pytest.mark.django_db
def test_removed_member_cannot_log_in(auth_client, api_client, team):
    member, membership = _add_member(team)
    auth_client.delete(f"/api/v1/auth/teams/{team.id}/members/{membership.pk}/")

    resp = api_client.post(
        "/api/v1/auth/login/",
        {"email": member.email, "password": "RealPass1!"},
        format="json",
    )
    assert resp.status_code == 401


@pytest.mark.django_db
def test_remove_with_other_team_keeps_account_and_switches_active_team(auth_client, team):
    member, membership = _add_member(team)
    other = Team.objects.create(name="Other Agency", owner=member)  # signal adds owner membership

    resp = auth_client.delete(f"/api/v1/auth/teams/{team.id}/members/{membership.pk}/")
    assert resp.status_code == 204

    member.refresh_from_db()
    assert member.is_active is True
    assert member.active_team == other


@pytest.mark.django_db
def test_permanent_delete_removes_account(auth_client, team):
    member, membership = _add_member(team)

    resp = auth_client.delete(
        f"/api/v1/auth/teams/{team.id}/members/{membership.pk}/?permanent=true"
    )
    assert resp.status_code == 204
    assert not User.objects.filter(email=member.email).exists()


@pytest.mark.django_db
def test_permanent_delete_spares_account_with_other_teams(auth_client, team):
    member, membership = _add_member(team)
    other = Team.objects.create(name="Other Agency", owner=member)  # signal adds owner membership

    resp = auth_client.delete(
        f"/api/v1/auth/teams/{team.id}/members/{membership.pk}/?permanent=true"
    )
    assert resp.status_code == 204
    member.refresh_from_db()
    assert member.is_active is True
    assert TeamMembership.objects.filter(user=member, team=other).exists()


@pytest.mark.django_db
def test_re_add_reactivates_deactivated_account(auth_client, team):
    member, membership = _add_member(team)
    auth_client.delete(f"/api/v1/auth/teams/{team.id}/members/{membership.pk}/")
    member.refresh_from_db()
    assert member.is_active is False

    resp = auth_client.post(
        f"/api/v1/auth/teams/{team.id}/users/",
        {"name": "Member", "email": member.email, "role": "developer"},
        format="json",
    )
    assert resp.status_code == 201
    member.refresh_from_db()
    assert member.is_active is True
    assert member.active_team == team
