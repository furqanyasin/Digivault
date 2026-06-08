"""Phase 1.4 — credential password health (age + strength + stale query)."""

import datetime

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.services import TeamService
from apps.credentials.models import Credential, score_password_strength


@pytest.fixture
def team(db):
    owner = User.objects.create_user(email="owner@pwhealth.com", password="SecurePass1!")
    return TeamService.create(name="PW Health Team", owner=owner)


def test_strength_scoring_weak_vs_strong():
    assert score_password_strength("") == 0
    assert score_password_strength("abc") <= 1
    assert score_password_strength("aB3$xY9!kLmn") == 4  # long + mixed + digit + symbol


@pytest.mark.django_db
def test_set_password_records_change_time_and_strength(team):
    cred = Credential(team=team, label="WP")
    cred.set_password("aB3$xY9!kLmn")
    cred.save()
    cred.refresh_from_db()
    assert cred.last_password_changed_at is not None
    assert cred.password_strength == 4


@pytest.mark.django_db
def test_password_age_days(team):
    cred = Credential(team=team, label="WP")
    cred.set_password("hunter2")
    cred.save()
    # Backdate the change time 200 days.
    Credential.objects.filter(pk=cred.pk).update(
        last_password_changed_at=timezone.now() - datetime.timedelta(days=200)
    )
    cred.refresh_from_db()
    assert cred.password_age_days == 200


@pytest.mark.django_db
def test_stale_passwords_queryset(team):
    fresh = Credential(team=team, label="fresh")
    fresh.set_password("x")
    fresh.save()

    stale = Credential(team=team, label="stale")
    stale.set_password("y")
    stale.save()
    Credential.objects.filter(pk=stale.pk).update(
        last_password_changed_at=timezone.now() - datetime.timedelta(days=200)
    )

    stale_ids = set(
        Credential.objects.stale_passwords(older_than_days=180).values_list(
            "pk", flat=True
        )
    )
    assert stale.pk in stale_ids
    assert fresh.pk not in stale_ids
