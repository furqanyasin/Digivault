"""A team can hold more than one owner.

Ownership used to be a single seat that only Django admin could move: the role
picker hid "owner", and the member endpoint refused any write to a membership
whose role was owner. That is what made "the owner is unavailable" a structural
problem rather than an inconvenience, and it is why the credential-group gate
kept being asked to widen to managers instead — which would have handed every
manager the power to grant other people access to the vault.

So the seat is now plural. `Team.owner` remains the **primary** owner and is
still immovable here — `Team.save` re-creates their membership and the FK is
PROTECTed — but every other owner is an ordinary membership an owner can create,
demote and remove.
"""

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import SubTeam, TeamMembership, User


def _client(user, password="SecurePass1!"):
    c = APIClient()
    resp = c.post(
        "/api/v1/auth/token/",
        {"email": user.email, "password": password},
        format="json",
    )
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")
    return c


def _member(team, email, role):
    u = User.objects.create_user(email=email, password="SecurePass1!")
    m = TeamMembership.objects.create(user=u, team=team, role=role)
    u.active_team = team
    u.save(update_fields=["active_team"])
    return u, m


def _members_url(team, membership):
    return f"/api/v1/auth/teams/{team.pk}/members/{membership.pk}/"


# ── Promoting ────────────────────────────────────────────────────────────────


def test_an_owner_promotes_a_manager_to_owner(auth_client, team):
    _, m = _member(team, "promote@x.io", TeamMembership.Role.MANAGER)
    resp = auth_client.patch(
        _members_url(team, m), {"role": "owner"}, format="json"
    )
    assert resp.status_code == 200, resp.data
    m.refresh_from_db()
    assert m.role == "owner"


def test_a_manager_cannot_promote_anyone_to_owner(team):
    """`ROLE_LEVELS[new_role] > my_level` already said this; pinned because it is
    the whole safety property of making the role assignable — only an owner can
    mint an owner."""
    manager, _ = _member(team, "mgr_promote@x.io", TeamMembership.Role.MANAGER)
    _, target = _member(team, "target@x.io", TeamMembership.Role.DEVELOPER)
    resp = _client(manager).patch(
        _members_url(team, target), {"role": "owner"}, format="json"
    )
    assert resp.status_code == 403
    target.refresh_from_db()
    assert target.role == "developer"


def test_a_new_owner_can_administer_credential_groups(auth_client, team):
    """The point of the whole change: a second owner is what covers an absent
    one, so group administration must actually work for them — this is the
    alternative to widening that gate to every manager."""
    promoted, m = _member(team, "newowner@x.io", TeamMembership.Role.MANAGER)
    assert auth_client.patch(
        _members_url(team, m), {"role": "owner"}, format="json"
    ).status_code == 200

    resp = _client(promoted).post(
        f"/api/v1/auth/teams/{team.pk}/sub-teams/", {"name": "Web Team"},
        format="json",
    )
    assert resp.status_code == 201, resp.data
    assert SubTeam.objects.filter(team=team, name="Web Team").exists()


# ── Demoting and removing ────────────────────────────────────────────────────


def test_an_owner_demotes_a_co_owner(auth_client, team):
    """Promotion that cannot be undone is not delegation, it is a one-way door."""
    _, m = _member(team, "demote@x.io", TeamMembership.Role.OWNER)
    resp = auth_client.patch(
        _members_url(team, m), {"role": "manager"}, format="json"
    )
    assert resp.status_code == 200, resp.data
    m.refresh_from_db()
    assert m.role == "manager"


def test_an_owner_removes_a_co_owner(auth_client, team):
    _, m = _member(team, "rmco@x.io", TeamMembership.Role.OWNER)
    resp = auth_client.delete(_members_url(team, m))
    assert resp.status_code in (200, 204), resp.data
    assert not TeamMembership.objects.filter(pk=m.pk).exists()


def test_a_manager_cannot_demote_a_co_owner(team):
    """A co-owner outranks a manager exactly as the primary owner does —
    `ROLE_LEVELS[target.role] > my_level` is what holds here, and it is why
    making the role assignable does not hand managers a back door to it."""
    manager, _ = _member(team, "mgr_demote@x.io", TeamMembership.Role.MANAGER)
    _, co = _member(team, "co_demote@x.io", TeamMembership.Role.OWNER)
    resp = _client(manager).patch(
        _members_url(team, co), {"role": "viewer"}, format="json"
    )
    assert resp.status_code == 403
    co.refresh_from_db()
    assert co.role == "owner"


# ── The primary owner ────────────────────────────────────────────────────────


def test_the_primary_owner_cannot_be_demoted_by_a_co_owner(team, user):
    """`Team.owner` is the account holder: `Team.save` re-creates their
    owner-level membership and the FK is PROTECTed, so a demotion would either
    silently revert or strand the team. It is also what guarantees a team can
    never run out of owners."""
    co_owner, _ = _member(team, "co_primary@x.io", TeamMembership.Role.OWNER)
    primary = TeamMembership.objects.get(team=team, user=user)

    resp = _client(co_owner).patch(
        _members_url(team, primary), {"role": "manager"}, format="json"
    )
    assert resp.status_code == 403
    primary.refresh_from_db()
    assert primary.role == "owner"


def test_the_primary_owner_cannot_be_removed_by_a_co_owner(team, user):
    co_owner, _ = _member(team, "co_primary2@x.io", TeamMembership.Role.OWNER)
    primary = TeamMembership.objects.get(team=team, user=user)

    resp = _client(co_owner).delete(_members_url(team, primary))
    assert resp.status_code == 403
    assert TeamMembership.objects.filter(pk=primary.pk).exists()


def test_the_member_list_marks_the_primary_owner(auth_client, team, user):
    """`role == "owner"` no longer tells the UI which row it must not offer to
    demote, because owners are plural. `is_primary_owner` does."""
    co_owner, _ = _member(team, "co_flag@x.io", TeamMembership.Role.OWNER)
    resp = auth_client.get(f"/api/v1/auth/teams/{team.pk}/members/")
    assert resp.status_code == 200
    # StandardPagination puts count/next/previous in the envelope's `meta`, so
    # `data` is a bare array — there is no "results" key to reach through.
    flags = {row["user"]["email"]: row["is_primary_owner"] for row in resp.data}
    assert flags[user.email] is True
    assert flags[co_owner.email] is False


# ── Self ─────────────────────────────────────────────────────────────────────


def test_nobody_can_change_their_own_role(team):
    """A co-owner who drops their own role cannot undo it, and nothing about a
    role change says "and lock me out of this page". The UI already refused
    this; the backend now agrees rather than trusting it."""
    co_owner, m = _member(team, "self_demote@x.io", TeamMembership.Role.OWNER)
    resp = _client(co_owner).patch(
        _members_url(team, m), {"role": "manager"}, format="json"
    )
    assert resp.status_code == 403
    m.refresh_from_db()
    assert m.role == "owner"


def test_nobody_can_remove_themselves(team):
    co_owner, m = _member(team, "self_remove@x.io", TeamMembership.Role.OWNER)
    resp = _client(co_owner).delete(_members_url(team, m))
    assert resp.status_code == 403
    assert TeamMembership.objects.filter(pk=m.pk).exists()


def test_a_no_op_patch_of_your_own_membership_is_not_a_role_change(team):
    """The self-guard fires on an actual change, so a PATCH that re-sends the
    role you already hold — which is what the UI's radio group sends when you
    click the selected item — is not turned into a refusal."""
    co_owner, m = _member(team, "self_noop@x.io", TeamMembership.Role.OWNER)
    resp = _client(co_owner).patch(
        _members_url(team, m), {"role": "owner"}, format="json"
    )
    assert resp.status_code == 200, resp.data
    m.refresh_from_db()
    assert m.role == "owner"


# ── Creating a member straight into the role ─────────────────────────────────


@pytest.mark.django_db
def test_an_owner_creates_a_new_user_as_an_owner(auth_client, team):
    resp = auth_client.post(
        f"/api/v1/auth/teams/{team.pk}/users/",
        {"email": "born_owner@x.io", "name": "Co Owner", "role": "owner"},
        format="json",
    )
    assert resp.status_code in (200, 201), resp.data
    m = TeamMembership.objects.get(team=team, user__email="born_owner@x.io")
    assert m.role == "owner"


@pytest.mark.django_db
def test_a_manager_cannot_create_a_new_user_as_an_owner(team):
    manager, _ = _member(team, "mgr_create@x.io", TeamMembership.Role.MANAGER)
    resp = _client(manager).post(
        f"/api/v1/auth/teams/{team.pk}/users/",
        {"email": "nope@x.io", "name": "Nope", "role": "owner"},
        format="json",
    )
    assert resp.status_code == 403
    assert not TeamMembership.objects.filter(
        team=team, user__email="nope@x.io"
    ).exists()
