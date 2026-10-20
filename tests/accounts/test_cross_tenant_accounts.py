"""Account flows must hold up once strangers can own teams.

Stacks Monitor started as an internal tool where every manager was a
colleague, so several account endpoints trusted "a manager of some team".
With public signup every new user owns a team, and those endpoints chained
into a takeover of any account by email:

1. add the victim's email to your own team (no consent asked),
2. read the victim's user id from your member list,
3. request a password reset for them and approve it yourself, reading the
   reset link out of the approval response,
4. switch off their 2FA by user id.

Each test below pins one link of that chain shut.
"""

import pytest
from django.core import mail
from rest_framework.test import APIClient

from apps.accounts.models import (
    PasswordResetRequest,
    SubTeam,
    TeamInvitation,
    TeamMembership,
    User,
)
from apps.accounts.services import TeamService


def _client(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def _owner(email, team_name):
    user = User.objects.create_user(email=email, password="RealPass1!")
    team = TeamService.create(name=team_name, owner=user)
    User.objects.filter(pk=user.pk).update(active_team=team)
    user.refresh_from_db()
    return user, team


def _member(team, email, role):
    user = User.objects.create_user(email=email, password="RealPass1!")
    TeamMembership.objects.create(user=user, team=team, role=role)
    User.objects.filter(pk=user.pk).update(active_team=team)
    user.refresh_from_db()
    return user


@pytest.fixture
def victim(db):
    user, _ = _owner("victim@example.com", "Victim Agency")
    user.totp_enabled = True
    user.save(update_fields=["totp_enabled"])
    return user


@pytest.fixture
def attacker(db):
    user, team = _owner("attacker@example.com", "Attacker Agency")
    return user, team


# --- the full chain ---------------------------------------------------------


@pytest.mark.django_db
def test_the_takeover_chain_is_closed_at_every_step(victim, attacker):
    attacker_user, attacker_team = attacker
    client = _client(attacker_user)

    # 1. Adding the victim's email only sends them an invitation.
    resp = client.post(
        f"/api/v1/auth/teams/{attacker_team.id}/users/",
        {"name": "Victim", "email": victim.email, "role": "developer"},
        format="json",
    )
    assert resp.status_code == 201
    assert "set_password_url" not in resp.data
    assert not TeamMembership.objects.filter(user=victim, team=attacker_team).exists()

    # 2. So the victim is not in the attacker's member list.
    members = client.get(f"/api/v1/auth/teams/{attacker_team.id}/members/")
    listed = [m["user"]["email"] for m in members.data]
    assert victim.email not in listed

    # 3. A reset request mails the victim; nothing comes back to the caller,
    #    and there is no approval endpoint left to read a link from.
    reset = APIClient().post("/api/v1/auth/password-reset/", {"email": victim.email}, format="json")
    assert reset.status_code == 200
    token = PasswordResetRequest.objects.get(user=victim).reset_token
    assert token not in str(reset.data)
    request_id = PasswordResetRequest.objects.get(user=victim).pk
    approve = client.post(f"/api/v1/auth/password-reset/{request_id}/approve/")
    assert approve.status_code == 404

    # 4. 2FA cannot be switched off for someone outside the caller's team.
    disable = client.post("/api/v1/auth/2fa/disable/", {"user_id": str(victim.pk)}, format="json")
    assert disable.status_code == 404
    victim.refresh_from_db()
    assert victim.totp_enabled is True


# --- invitations ------------------------------------------------------------


@pytest.mark.django_db
def test_accepting_an_invitation_never_issues_tokens(victim, attacker):
    """It used to accept email + password and return a session, skipping 2FA."""
    attacker_user, attacker_team = attacker
    invitation = TeamInvitation.objects.create(
        team=attacker_team, invited_by=attacker_user, email=victim.email, role="developer",
    )

    resp = APIClient().post(
        f"/api/v1/auth/invitations/{invitation.token}/accept/",
        {"password": "RealPass1!"},
        format="json",
    )
    assert resp.status_code == 401
    assert "tokens" not in str(resp.data)
    assert not TeamMembership.objects.filter(user=victim, team=attacker_team).exists()


@pytest.mark.django_db
def test_only_the_invited_account_can_accept(victim, attacker):
    attacker_user, attacker_team = attacker
    invitation = TeamInvitation.objects.create(
        team=attacker_team, invited_by=attacker_user, email="someone-else@example.com", role="developer",
    )
    resp = _client(victim).post(f"/api/v1/auth/invitations/{invitation.token}/accept/")
    assert resp.status_code == 403


@pytest.mark.django_db
def test_accepting_joins_with_the_invited_role_and_group(attacker):
    owner, team = attacker
    group = SubTeam.objects.create(team=team, name="Web Team")
    invitee = User.objects.create_user(email="invitee@example.com", password="RealPass1!")
    TeamService.create(name="Invitee Agency", owner=invitee)

    resp = _client(owner).post(
        f"/api/v1/auth/teams/{team.id}/users/",
        {"name": "Invitee", "email": invitee.email, "role": "developer", "sub_team": str(group.pk)},
        format="json",
    )
    assert resp.status_code == 201
    invitation = TeamInvitation.objects.get(team=team, email=invitee.email)

    accepted = _client(invitee).post(f"/api/v1/auth/invitations/{invitation.token}/accept/")
    assert accepted.status_code == 200
    membership = TeamMembership.objects.get(user=invitee, team=team)
    assert membership.role == "developer"
    assert membership.sub_team == group


# --- 2FA reset for others ---------------------------------------------------


@pytest.mark.django_db
def test_a_manager_resets_2fa_for_a_developer_in_their_team(attacker):
    owner, team = attacker
    manager = _member(team, "manager@example.com", "manager")
    dev = _member(team, "dev@example.com", "developer")
    dev.totp_enabled = True
    dev.save(update_fields=["totp_enabled"])

    resp = _client(manager).post("/api/v1/auth/2fa/disable/", {"user_id": str(dev.pk)}, format="json")
    assert resp.status_code == 200
    dev.refresh_from_db()
    assert dev.totp_enabled is False


@pytest.mark.django_db
def test_a_manager_cannot_reset_2fa_for_another_manager(attacker):
    owner, team = attacker
    manager = _member(team, "manager@example.com", "manager")
    peer = _member(team, "peer@example.com", "manager")
    peer.totp_enabled = True
    peer.save(update_fields=["totp_enabled"])

    resp = _client(manager).post("/api/v1/auth/2fa/disable/", {"user_id": str(peer.pk)}, format="json")
    assert resp.status_code == 403
    peer.refresh_from_db()
    assert peer.totp_enabled is True


@pytest.mark.django_db
def test_a_co_owner_cannot_reset_2fa_for_the_primary_owner(attacker):
    owner, team = attacker
    owner.totp_enabled = True
    owner.save(update_fields=["totp_enabled"])
    co_owner = _member(team, "co-owner@example.com", "owner")

    resp = _client(co_owner).post("/api/v1/auth/2fa/disable/", {"user_id": str(owner.pk)}, format="json")
    assert resp.status_code == 403
    owner.refresh_from_db()
    assert owner.totp_enabled is True


@pytest.mark.django_db
def test_an_owner_resets_2fa_for_a_co_owner(attacker):
    owner, team = attacker
    co_owner = _member(team, "co-owner@example.com", "owner")
    co_owner.totp_enabled = True
    co_owner.save(update_fields=["totp_enabled"])

    resp = _client(owner).post("/api/v1/auth/2fa/disable/", {"user_id": str(co_owner.pk)}, format="json")
    assert resp.status_code == 200


# --- self-service password reset -------------------------------------------


@pytest.mark.django_db
def test_reset_mails_a_one_hour_link_to_the_account_only(victim):
    resp = APIClient().post("/api/v1/auth/password-reset/", {"email": victim.email}, format="json")
    assert resp.status_code == 200

    pr = PasswordResetRequest.objects.get(user=victim)
    assert pr.status == PasswordResetRequest.Status.APPROVED
    assert 59 * 60 < (pr.expires_at - pr.created_at).total_seconds() <= 60 * 60 + 5
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == [victim.email]
    assert pr.reset_token in mail.outbox[0].body

    confirm = APIClient().post(
        "/api/v1/auth/password-reset/confirm/",
        {"token": pr.reset_token, "password": "BrandNewPass9!"},
        format="json",
    )
    assert confirm.status_code == 200
    victim.refresh_from_db()
    assert victim.check_password("BrandNewPass9!")


@pytest.mark.django_db
def test_reset_reply_is_the_same_for_unknown_and_known_emails(victim):
    known = APIClient().post("/api/v1/auth/password-reset/", {"email": victim.email}, format="json")
    unknown = APIClient().post("/api/v1/auth/password-reset/", {"email": "nobody@example.com"}, format="json")
    assert known.status_code == unknown.status_code == 200
    assert known.data == unknown.data
    assert len(mail.outbox) == 1


@pytest.mark.django_db
def test_reset_is_not_sent_to_a_deactivated_account(victim):
    User.objects.filter(pk=victim.pk).update(is_active=False)
    APIClient().post("/api/v1/auth/password-reset/", {"email": victim.email}, format="json")
    assert len(mail.outbox) == 0
    assert not PasswordResetRequest.objects.filter(user=victim).exists()


@pytest.mark.django_db
def test_a_second_reset_within_the_cooldown_sends_nothing(victim):
    client = APIClient()
    client.post("/api/v1/auth/password-reset/", {"email": victim.email}, format="json")
    client.post("/api/v1/auth/password-reset/", {"email": victim.email}, format="json")
    assert len(mail.outbox) == 1
    assert PasswordResetRequest.objects.filter(user=victim).count() == 1


@pytest.mark.django_db
def test_a_new_reset_link_retires_the_older_ones(victim):
    old = PasswordResetRequest.objects.create(
        user=victim, status=PasswordResetRequest.Status.APPROVED, reset_token="old-onboarding-token",
    )
    PasswordResetRequest.objects.filter(pk=old.pk).update(
        created_at=old.created_at.replace(year=old.created_at.year - 1)
    )

    APIClient().post("/api/v1/auth/password-reset/", {"email": victim.email}, format="json")

    old.refresh_from_db()
    assert old.status == PasswordResetRequest.Status.USED
    assert old.reset_token is None


# --- team settings across teams ---------------------------------------------


@pytest.mark.django_db
def test_renaming_a_team_checks_the_role_in_that_team(attacker):
    """TeamRolePermission reads the active team. A manager of their active
    team who is only a viewer in another must not rename the other one."""
    owner, team = attacker
    other_owner, other_team = _owner("other@example.com", "Other Agency")
    user = _member(team, "both@example.com", "manager")
    TeamMembership.objects.create(user=user, team=other_team, role="viewer")

    resp = _client(user).patch(f"/api/v1/auth/teams/{other_team.id}/", {"name": "Hijacked"}, format="json")
    assert resp.status_code == 403
    other_team.refresh_from_db()
    assert other_team.name == "Other Agency"
