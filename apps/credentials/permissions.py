from apps.accounts.models import TeamMembership


def _user_role(user, team) -> str | None:
    if user is None or not user.is_authenticated or team is None:
        return None
    membership = TeamMembership.objects.filter(user=user, team=team).first()
    return membership.role if membership else None


def can_modify_credential(user, credential) -> bool:
    """Edit / delete / share / unshare permission.

    Allowed when the user is an owner or manager of the credential's
    team, or is the credential's creator.  A shared developer cannot
    modify.
    """
    role = _user_role(user, credential.team)
    if role in (TeamMembership.Role.OWNER, TeamMembership.Role.MANAGER):
        return True
    return credential.created_by_id == getattr(user, "id", None)
