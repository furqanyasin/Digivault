import pytest

from apps.audit.models import ActivityLog
from apps.audit.services import AuditService
from apps.accounts.services import TeamService
from apps.accounts.models import User


@pytest.fixture
def owner(db):
    return User.objects.create_user(email="owner@audittest.com", password="SecurePass1!")


@pytest.fixture
def team(owner):
    return TeamService.create(name="Audit Test Team", owner=owner)


@pytest.mark.django_db
def test_log_stores_metadata(owner, team):
    AuditService.log(
        actor=owner,
        action=ActivityLog.Action.TEAM_MEMBER_ROLE_CHANGED,
        team=team,
        description="Changed role",
        metadata={"previous_role": "developer", "new_role": "manager"},
    )
    log = ActivityLog.objects.filter(actor=owner, team=team).first()
    assert log is not None
    assert log.metadata == {"previous_role": "developer", "new_role": "manager"}


@pytest.mark.django_db
def test_log_defaults_empty_metadata(owner, team):
    AuditService.log(
        actor=owner,
        action=ActivityLog.Action.AUTH_LOGIN,
        team=team,
        description="Login",
    )
    log = ActivityLog.objects.filter(actor=owner, team=team).first()
    assert log.metadata == {}
