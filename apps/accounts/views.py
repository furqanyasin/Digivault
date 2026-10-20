import logging
import secrets

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import send_mail
from django.utils import timezone
from django.utils.timezone import timedelta
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from apps.accounts.models import (
    PasswordResetRequest,
    SubTeam,
    Team,
    TeamInvitation,
    TeamMembership,
    User,
)
from apps.accounts.serializers import (
    SubTeamSerializer,
    TeamInvitationSerializer,
    TeamMembershipSerializer,
    TeamSerializer,
    TeamSettingsSerializer,
    UserSerializer,
)
from apps.accounts.services import TeamService
from apps.audit.models import ActivityLog
from apps.audit.services import AuditService
from apps.common.permissions import (
    ROLE_LEVELS,
    ROLE_MANAGER,
    IsTeamMember,
    TeamRolePermission,
)
from apps.integrations.clickup import ClickUpClient, ClickUpError
from apps.integrations.members import (
    set_member_link,
    sync_member_links,
    username_for_clickup_id,
)

logger = logging.getLogger(__name__)

# ROLE_LEVELS is imported from apps.common.permissions rather than redefined.
# There were two copies of this ladder — one here, one there — which is how the
# permission class that reads the other copy ended up wired to four views while
# this module went on making its own role decisions by hand.

# Distinguishes "key absent" from an explicit null in a PATCH body.
_UNSET = object()

from apps.accounts.features import FEATURE_KEYS, default_features


def _my_level(user, team):
    try:
        m = TeamMembership.objects.get(user=user, team=team)
        return ROLE_LEVELS.get(m.role, 0), m
    except TeamMembership.DoesNotExist:
        return 0, None


def _require_group_admin(request, team):
    """None when the caller may administer credential groups, else a 403.

    **Owner only** — meaning anyone holding the owner *role* in this team, which
    is now a set of people rather than one. See
    docs/superpowers/specs/2026-09-02-credential-sub-teams-design.md.

    This briefly admitted managers, to answer the lockout the spec named and
    accepted: with the owner unavailable nobody could create a group, grant
    access, or even read the grant list. That cost was real, but paying it by
    widening the gate charged it to the wrong account — a manager already reads
    every credential in the team (`Credential.objects.visible_to`), so what they
    gained was the power to hand that reach to *other* people, which is exactly
    the power the spec set out to keep scarce.

    The lockout is answered instead by letting a team have **more than one
    owner** (`TeamMemberDetailView.patch` will assign the owner role, and
    `Team.owner` marks the one primary owner who cannot be demoted). A second
    owner is a deliberate, audit-logged act by an existing owner, so cover for
    an absent owner is something a team opts into by naming a person, not
    something every manager holds by default.

    Everything done here stays attributable regardless: grants are written with
    `granted_by`, and every create and revoke is audit-logged.
    """
    my_level, _ = _my_level(request.user, team)
    if my_level < ROLE_LEVELS["owner"]:
        return Response(
            {"detail": "Team owner required."},
            status=status.HTTP_403_FORBIDDEN,
        )
    return None


#: Alias kept so nothing importing either name breaks. Both apply the same
#: owner-only gate; `_require_group_admin` says what it is gating.
_require_owner = _require_group_admin


def _resolve_sub_team(request, team):
    """Resolve an optional `sub_team` from the request body.

    Returns `(value, error_response)`. The value is `_UNSET` when the key is
    absent (leave the current group alone), None when explicitly null (clear
    it), or a SubTeam.

    Setting a group is owner-only, so anyone below that is refused the moment
    they include the key rather than having it silently dropped: a silently
    ignored permission change is worse than a visible refusal.
    """
    if "sub_team" not in request.data:
        return _UNSET, None
    err = _require_group_admin(request, team)
    if err:
        return None, err
    raw = request.data.get("sub_team")
    if raw in (None, "", "null"):
        return None, None
    try:
        group = SubTeam.objects.filter(pk=raw, team=team).first()
    except (DjangoValidationError, ValueError, TypeError):
        # A malformed id is a client error, not a 500 out of the ORM.
        group = None
    if group is None:
        return None, Response(
            {"detail": "That group belongs to a different team."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return group, None


def _issue_set_password_link(user, actor):
    """Create an APPROVED password-reset token for `user` and return the
    frontend set-password URL. Used to onboard anyone without a usable password
    — a brand-new account, or an existing one that never finished setup."""
    reset_token = secrets.token_urlsafe(48)
    PasswordResetRequest.objects.create(
        user=user,
        status=PasswordResetRequest.Status.APPROVED,
        reset_token=reset_token,
        approved_by=actor,
        approved_at=timezone.now(),
        expires_at=timezone.now() + timedelta(days=7),
    )
    return f"{settings.FRONTEND_URL}/reset-password?token={reset_token}"


def _upsert_invitation(team, email, role, invited_by, sub_team=None):
    """Create the pending invitation, or refresh an existing one (new role,
    group and 7-day expiry) so resending never piles up duplicates."""
    invitation, _ = TeamInvitation.objects.update_or_create(
        team=team, email=email,
        defaults={
            "invited_by": invited_by,
            "role": role,
            "sub_team": sub_team,
            "accepted": False,
            "accepted_at": None,
            "expires_at": timezone.now() + timedelta(days=7),
        },
    )
    return invitation


def _ensure_seat_for(team, email):
    """Raise the plan-limit error unless the team has a free seat. A resend
    to someone already invited does not take a second seat."""
    from apps.accounts.plans import ensure_can_add

    if TeamInvitation.objects.filter(team=team, email__iexact=email, accepted=False).exists():
        return
    ensure_can_add(team, "members")


def _send_account_email(subject, body, recipient):
    """Send an onboarding email. Returns True if it was delivered, False on
    failure (logged, never raised) so onboarding can fall back to the link."""
    try:
        return bool(send_mail(
            subject=subject, message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient], fail_silently=False,
        ))
    except Exception as exc:
        logger.error("Failed to send account email to %s: %s", recipient, exc)
        return False


class MeView(generics.RetrieveUpdateAPIView):
    """GET/PATCH /api/v1/auth/me/"""

    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user


class TeamListCreateView(generics.ListCreateAPIView):
    """GET/POST /api/v1/auth/teams/"""

    serializer_class = TeamSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return (
            Team.objects.filter(memberships__user=self.request.user)
            .prefetch_related("memberships")
            .distinct()
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        current = request.user.active_team
        if (
            getattr(settings, "ENFORCE_PLAN_LIMITS", True)
            and not (current and current.plan == Team.Plan.INTERNAL)
            and Team.objects.filter(owner=request.user, plan=Team.Plan.FREE).exists()
        ):
            # One free workspace per person, or "1 website" means nothing.
            from apps.accounts.plans import PlanLimitReached
            raise PlanLimitReached("You already have a free workspace. Upgrade it to add more.")
        team = TeamService.create(name=serializer.validated_data["name"], owner=request.user)
        AuditService.log(
            actor=request.user, action=ActivityLog.Action.TEAM_CREATED, team=team,
            description=f"Created department '{team.name}'",
            resource_type="team", resource_id=team.pk,
        )
        return Response(
            TeamSerializer(team, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


class TeamDetailView(generics.RetrieveUpdateAPIView):
    """GET/PATCH /api/v1/auth/teams/<pk>/"""

    serializer_class = TeamSerializer
    # Renaming the department is a settings change, not day-to-day work, and it
    # renames it for everyone. Reading stays open to every member.
    permission_classes = [permissions.IsAuthenticated, IsTeamMember, TeamRolePermission]
    write_role = ROLE_MANAGER

    def get_queryset(self):
        return Team.objects.filter(memberships__user=self.request.user)

    def update(self, request, *args, **kwargs):
        team = self.get_object()
        # TeamRolePermission reads the role in the *active* team. The team in
        # the URL can be a different one where this user is only a viewer.
        if _my_level(request.user, team)[0] < ROLE_LEVELS[ROLE_MANAGER]:
            return Response({"detail": "Manager or higher required."}, status=status.HTTP_403_FORBIDDEN)
        old_name = team.name
        response = super().update(request, *args, **kwargs)
        new_name = response.data.get("data", {}).get("name") or team.name
        if old_name != new_name:
            AuditService.log_request(
                request, ActivityLog.Action.SETTINGS_TEAM_NAME_CHANGED,
                description=f"Renamed team from '{old_name}' to '{new_name}'",
                resource_type="team", resource_id=str(team.pk),
                metadata={"previous_name": old_name, "new_name": new_name},
            )
        return response


class TeamMemberListView(generics.ListAPIView):
    """GET /api/v1/auth/teams/<team_pk>/members/"""

    serializer_class = TeamMembershipSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def get_queryset(self):
        return (
            TeamMembership.objects.filter(
                team_id=self.kwargs["team_pk"],
                team__memberships__user=self.request.user,
            )
            # `team` is joined for the serializer's `is_primary_owner`, which
            # compares against `team.owner_id` — one query instead of one per
            # member.
            .select_related("user", "team")
            .distinct()
        )


class TeamMemberDetailView(APIView):
    """PATCH /api/v1/auth/teams/<team_pk>/members/<pk>/ — change role
    DELETE /api/v1/auth/teams/<team_pk>/members/<pk>/ — remove member
    """

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def _get_objects(self, request, team_pk, pk):
        try:
            team = Team.objects.get(pk=team_pk)
        except Team.DoesNotExist:
            return None, None, None, Response(status=status.HTTP_404_NOT_FOUND)
        my_level, my_membership = _my_level(request.user, team)
        if my_level < ROLE_LEVELS["manager"]:
            return None, None, None, Response(
                {"detail": "Manager or higher required."}, status=status.HTTP_403_FORBIDDEN
            )
        try:
            target = TeamMembership.objects.select_related("user").get(pk=pk, team=team)
        except TeamMembership.DoesNotExist:
            return None, None, None, Response(status=status.HTTP_404_NOT_FOUND)
        return team, my_level, target, None

    def patch(self, request, team_pk, pk):
        team, my_level, target, err = self._get_objects(request, team_pk, pk)
        if err:
            return err

        new_role = request.data.get("role", "").lower()
        if new_role not in ROLE_LEVELS:
            return Response({"detail": f"Invalid role: {new_role}"}, status=status.HTTP_400_BAD_REQUEST)

        # Can't assign a role higher than your own
        if ROLE_LEVELS[new_role] > my_level:
            return Response({"detail": "Cannot assign a role higher than your own."}, status=status.HTTP_403_FORBIDDEN)

        # Can't downgrade someone with a higher role
        if ROLE_LEVELS[target.role] > my_level:
            return Response({"detail": "Cannot modify a member with a higher role."}, status=status.HTTP_403_FORBIDDEN)

        # A team may hold several owners, so "is an owner" is no longer the
        # thing that protects a membership — `Team.owner` is. That one primary
        # owner is the account holder: `Team.save` keeps re-creating their
        # owner-level membership, and `Team.owner` is PROTECTed, so demoting
        # them would either silently revert or strand the team. Every *other*
        # owner is a co-owner an owner named and an owner can unname.
        if target.user_id == team.owner_id:
            return Response({"detail": "Cannot change the primary owner's role."}, status=status.HTTP_403_FORBIDDEN)

        # Demoting yourself is refused rather than guarded by a count: with the
        # primary owner undemotable there is always an owner left, but an owner
        # who drops their own role cannot undo it, and nothing about a role
        # change says "and lock me out of this page".
        if target.user_id == request.user.pk and new_role != target.role:
            return Response(
                {"detail": "You cannot change your own role. Ask another owner."},
                status=status.HTTP_403_FORBIDDEN,
            )

        new_group, group_err = _resolve_sub_team(request, team)
        if group_err:
            return group_err

        old_role = target.role
        target.role = new_role
        # feature_access applies to every role except owner. When the caller
        # supplies a list we save that (a per-member override); otherwise the
        # role's default preset is applied as a starting point.
        raw = request.data.get("feature_access")
        if raw is not None:
            if not isinstance(raw, list):
                return Response({"detail": "feature_access must be a list."}, status=status.HTTP_400_BAD_REQUEST)
            target.feature_access = [k for k in raw if k in FEATURE_KEYS]
        else:
            target.feature_access = default_features(new_role)

        update_fields = ["role", "feature_access", "updated_at"]
        old_group_name = target.sub_team.name if target.sub_team_id else None
        if new_group is not _UNSET:
            target.sub_team = new_group
            update_fields.append("sub_team")
        target.save(update_fields=update_fields)

        if new_group is not _UNSET:
            AuditService.log(
                actor=request.user,
                action=ActivityLog.Action.TEAM_MEMBER_GROUP_CHANGED,
                team=team,
                description=(
                    f"Moved {target.user.email} from "
                    f"{old_group_name or 'no group'} to "
                    f"{new_group.name if new_group else 'no group'}"
                ),
                resource_type="team_membership", resource_id=str(target.pk),
                metadata={
                    "previous_group": old_group_name,
                    "new_group": new_group.name if new_group else None,
                },
            )
        AuditService.log(
            actor=request.user, action=ActivityLog.Action.TEAM_MEMBER_ROLE_CHANGED,
            team=team,
            description=f"Changed {target.user.email}'s role from {old_role} to {new_role}",
            resource_type="team_membership", resource_id=str(target.pk),
            metadata={"previous_role": old_role, "new_role": new_role},
        )
        return Response(TeamMembershipSerializer(target).data)

    def delete(self, request, team_pk, pk):
        team, my_level, target, err = self._get_objects(request, team_pk, pk)
        if err:
            return err

        # The primary owner holds the team (`Team.owner` is PROTECTed and their
        # membership is re-created by `Team.save`); a co-owner is an ordinary
        # membership another owner can remove.
        if target.user_id == team.owner_id:
            return Response({"detail": "Cannot remove the primary team owner."}, status=status.HTTP_403_FORBIDDEN)

        if target.user_id == request.user.pk:
            return Response(
                {"detail": "You cannot remove yourself from the team."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Can't remove someone with a higher role than yourself
        if ROLE_LEVELS[target.role] > my_level:
            return Response({"detail": "Cannot remove a member with a higher role."}, status=status.HTTP_403_FORBIDDEN)

        removed_user = target.user
        removed_email = removed_user.email
        removed_role = target.role
        permanent = str(request.query_params.get("permanent", "")).lower() in ("1", "true", "yes")
        target.delete()

        remaining = TeamMembership.objects.filter(user=removed_user)
        outcome = "removed from the team"
        if remaining.exists():
            # Still belongs to other teams — never touch the account, but make
            # sure active_team no longer points at the team they just left
            # (TeamScopedMixin trusts active_team alone for data isolation).
            if removed_user.active_team_id == team.pk:
                User.objects.filter(pk=removed_user.pk).update(
                    active_team=remaining.first().team
                )
        elif removed_user.is_superuser or removed_user.is_staff:
            User.objects.filter(pk=removed_user.pk).update(active_team=None)
        elif permanent:
            removed_user.delete()
            outcome = "permanently deleted"
        else:
            # No team left — deactivate so the account can no longer log in.
            # Re-adding them to a team reactivates it.
            User.objects.filter(pk=removed_user.pk).update(
                is_active=False, active_team=None
            )
            outcome = "removed and account deactivated"

        AuditService.log(
            actor=request.user, action=ActivityLog.Action.TEAM_MEMBER_REMOVED,
            team=team,
            description=f"{removed_email} ({removed_role}) {outcome}",
            resource_type="team_membership", resource_id=str(pk),
            metadata={"role": removed_role, "permanent": permanent},
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class SubTeamListCreateView(APIView):
    """GET/POST /api/v1/auth/teams/<team_pk>/sub-teams/

    Listing is open to any team member so the UI can render a member's group
    badge. Creating is owner-only.
    """

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def _team_for_member(self, request, team_pk):
        """The team, but only if the caller is a member of it. Otherwise None."""
        team = Team.objects.filter(pk=team_pk).first()
        if team is None or not _my_level(request.user, team)[0]:
            return None
        return team

    def get(self, request, team_pk):
        team = self._team_for_member(request, team_pk)
        if team is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(SubTeamSerializer(team.sub_teams.all(), many=True).data)

    def post(self, request, team_pk):
        team = self._team_for_member(request, team_pk)
        if team is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        err = _require_group_admin(request, team)
        if err:
            return err

        ser = SubTeamSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        name = ser.validated_data["name"].strip()
        if not name:
            return Response(
                {"detail": "Group name is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # Case-insensitive: "Web Team" and "web team" as two groups would be a
        # support call, not a feature.
        if SubTeam.objects.filter(team=team, name__iexact=name).exists():
            return Response(
                {"detail": f"A group called '{name}' already exists."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        group = SubTeam.objects.create(
            team=team,
            name=name,
            description=ser.validated_data.get("description", ""),
        )
        AuditService.log(
            actor=request.user, action=ActivityLog.Action.TEAM_GROUP_CREATED,
            team=team, description=f"Created group '{group.name}'",
            resource_type="sub_team", resource_id=str(group.pk),
        )
        return Response(
            SubTeamSerializer(group).data, status=status.HTTP_201_CREATED
        )


class SubTeamDetailView(APIView):
    """PATCH/DELETE /api/v1/auth/teams/<team_pk>/sub-teams/<pk>/ — owner only.

    Deleting a group sets its members' `sub_team` to NULL and cascades its
    grants away, so members drop back to their own credentials plus individual
    shares. Access can only narrow.
    """

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def _get(self, request, team_pk, pk):
        team = Team.objects.filter(pk=team_pk).first()
        if team is None or not _my_level(request.user, team)[0]:
            return None, None, Response(status=status.HTTP_404_NOT_FOUND)
        err = _require_group_admin(request, team)
        if err:
            return None, None, err
        group = SubTeam.objects.filter(pk=pk, team=team).first()
        if group is None:
            return None, None, Response(status=status.HTTP_404_NOT_FOUND)
        return team, group, None

    def patch(self, request, team_pk, pk):
        team, group, err = self._get(request, team_pk, pk)
        if err:
            return err
        name = (request.data.get("name") or group.name).strip()
        if not name:
            return Response(
                {"detail": "Group name is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if (
            SubTeam.objects.filter(team=team, name__iexact=name)
            .exclude(pk=group.pk)
            .exists()
        ):
            return Response(
                {"detail": f"A group called '{name}' already exists."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        old_name = group.name
        group.name = name
        if "description" in request.data:
            group.description = request.data.get("description") or ""
        group.save(update_fields=["name", "description", "updated_at"])
        AuditService.log(
            actor=request.user, action=ActivityLog.Action.TEAM_GROUP_UPDATED,
            team=team,
            description=f"Renamed group '{old_name}' to '{group.name}'",
            resource_type="sub_team", resource_id=str(group.pk),
        )
        return Response(SubTeamSerializer(group).data)

    def delete(self, request, team_pk, pk):
        team, group, err = self._get(request, team_pk, pk)
        if err:
            return err
        name = group.name
        member_count = group.memberships.count()
        group.delete()
        AuditService.log(
            actor=request.user, action=ActivityLog.Action.TEAM_GROUP_DELETED,
            team=team,
            description=(
                f"Deleted group '{name}', ungrouping {member_count} member(s)"
            ),
            resource_type="sub_team", resource_id=str(pk),
            metadata={"members_ungrouped": member_count},
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class TeamInviteView(APIView):
    """POST /api/v1/auth/teams/<team_pk>/invite/ — send invitation"""

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def post(self, request, team_pk):
        try:
            team = Team.objects.get(pk=team_pk)
        except Team.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        my_level, _ = _my_level(request.user, team)
        if my_level < ROLE_LEVELS["manager"]:
            return Response({"detail": "Manager or higher required to invite."}, status=status.HTTP_403_FORBIDDEN)

        email = (request.data.get("email") or "").strip().lower()
        role = (request.data.get("role") or "developer").lower()

        if not email:
            return Response({"detail": "Email is required."}, status=status.HTTP_400_BAD_REQUEST)
        if role not in ROLE_LEVELS:
            return Response({"detail": f"Invalid role: {role}"}, status=status.HTTP_400_BAD_REQUEST)
        if ROLE_LEVELS[role] > my_level:
            return Response({"detail": "Cannot invite someone to a role higher than your own."}, status=status.HTTP_403_FORBIDDEN)

        # Can't invite existing members
        if TeamMembership.objects.filter(team=team, user__email=email).exists():
            return Response({"detail": "This user is already a team member."}, status=status.HTTP_400_BAD_REQUEST)

        _ensure_seat_for(team, email)
        invitation = _upsert_invitation(team, email, role, request.user)

        from django.conf import settings
        from django.core.mail import send_mail

        # Auto-create account if this email has never signed up.
        # We set an unusable password and issue a set-password token — never email credentials.
        set_password_url = None
        if not User.objects.filter(email__iexact=email).exists():
            new_user = User.objects.create_user(email=email, password=None)
            new_user.set_unusable_password()
            new_user.save(update_fields=["password"])
            # Pre-approve a password reset so the invitee can set their own password
            reset_token = secrets.token_urlsafe(48)
            from apps.accounts.models import PasswordResetRequest
            PasswordResetRequest.objects.create(
                user=new_user,
                status=PasswordResetRequest.Status.APPROVED,
                reset_token=reset_token,
                approved_by=request.user,
                approved_at=timezone.now(),
                expires_at=timezone.now() + timedelta(days=7),
            )
            set_password_url = f"{settings.FRONTEND_URL}/reset-password?token={reset_token}"

        accept_url = f"{settings.FRONTEND_URL}/invite/{invitation.token}"
        logger.info("Invitation for %s to %s: %s", email, team.name, accept_url)

        body = (
            f"Hi,\n\n"
            f"{request.user.email} has invited you to join the {team.name} team on Stacks Monitor.\n\n"
        )
        if set_password_url:
            body += (
                f"We've created an account for you with email: {email}\n\n"
                f"Step 1 — Set your password (link valid for 7 days):\n{set_password_url}\n\n"
                f"Step 2 — Then accept your invitation:\n{accept_url}\n\n"
            )
        else:
            body += f"Accept your invitation:\n{accept_url}\n\nThis link expires in 7 days.\n"

        try:
            send_mail(
                subject=f"You've been invited to join {team.name} on Stacks Monitor",
                message=body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[email],
                fail_silently=False,
            )
        except Exception as exc:
            logger.error("Failed to send invitation email to %s: %s", email, exc)

        AuditService.log_request(
            request, ActivityLog.Action.TEAM_MEMBER_INVITED,
            description=f"Invited {email} as {role}",
            resource_type="team_invitation", resource_id=str(invitation.pk),
        )
        return Response({
            **TeamInvitationSerializer(invitation).data,
            "accept_url": accept_url,
        }, status=status.HTTP_201_CREATED)


class TeamInvitationListView(generics.ListAPIView):
    """GET /api/v1/auth/teams/<team_pk>/invitations/ — pending invitations"""

    serializer_class = TeamInvitationSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def get_queryset(self):
        return TeamInvitation.objects.filter(
            team_id=self.kwargs["team_pk"],
            accepted=False,
            team__memberships__user=self.request.user,
        ).distinct()


class TeamInvitationDeleteView(APIView):
    """DELETE /api/v1/auth/teams/<team_pk>/invitations/<pk>/ — revoke invite"""

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def delete(self, request, team_pk, pk):
        try:
            invite = TeamInvitation.objects.get(pk=pk, team_id=team_pk, accepted=False)
        except TeamInvitation.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        my_level, _ = _my_level(request.user, invite.team)
        if my_level < ROLE_LEVELS["manager"]:
            return Response({"detail": "Manager or higher required."}, status=status.HTTP_403_FORBIDDEN)
        invite.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class TeamSwitchView(APIView):
    """POST /api/v1/auth/teams/<pk>/switch/ — set as active team"""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        if not TeamMembership.objects.filter(user=request.user, team_id=pk).exists():
            return Response({"detail": "Not a member of this team."}, status=status.HTTP_403_FORBIDDEN)
        User.objects.filter(pk=request.user.pk).update(active_team_id=pk)
        return Response({"detail": "Active team updated."})


class InvitationAcceptView(APIView):
    """GET  /api/v1/auth/invitations/<token>/ — view invitation (public)
    POST /api/v1/auth/invitations/<token>/accept/ — accept invitation
    """

    permission_classes = [permissions.AllowAny]

    def _get_invitation(self, token):
        try:
            inv = TeamInvitation.objects.select_related("team", "invited_by").get(token=token, accepted=False)
        except TeamInvitation.DoesNotExist:
            return None, Response({"detail": "Invitation not found or already accepted."}, status=status.HTTP_404_NOT_FOUND)
        if inv.expires_at and inv.expires_at < timezone.now():
            return None, Response({"detail": "This invitation has expired. Please ask your team admin to resend it."}, status=status.HTTP_410_GONE)
        return inv, None

    def get(self, request, token):
        inv, err = self._get_invitation(token)
        if err:
            return err
        return Response({
            "id": str(inv.id),
            "team_name": inv.team.name,
            "team_slug": inv.team.slug,
            "invited_by": inv.invited_by.email,
            "email": inv.email,
            "role": inv.role,
        })

    def post(self, request, token):
        inv, err = self._get_invitation(token)
        if err:
            return err

        # Accepting needs a real login. It used to also take email + password
        # and hand back tokens, which skipped 2FA: anyone holding the password
        # and an invitation they had sent themselves got a full session.
        if not request.user.is_authenticated:
            return Response(
                {"detail": f"Log in as {inv.email} to accept this invitation."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        user = request.user
        if user.email.lower() != inv.email.lower():
            return Response(
                {"detail": f"This invitation is for {inv.email}. Log in with that account."},
                status=status.HTTP_403_FORBIDDEN,
            )

        TeamMembership.objects.get_or_create(
            user=user, team=inv.team,
            defaults={"role": inv.role, "sub_team": inv.sub_team},
        )

        # Set as active team if none
        if not user.active_team:
            User.objects.filter(pk=user.pk).update(active_team=inv.team)

        # Mark accepted
        TeamInvitation.objects.filter(pk=inv.pk).update(accepted=True, accepted_at=timezone.now())

        AuditService.log(
            actor=user, action=ActivityLog.Action.TEAM_MEMBER_JOINED,
            team=inv.team,
            description=f"{user.email} joined as {inv.role}",
            resource_type="team_membership",
        )

        return Response({"detail": f"You have joined {inv.team.name} as {inv.role}."})


class TeamCreateUserView(APIView):
    """POST /api/v1/auth/teams/<team_pk>/users/ — admin creates a new user and adds them to the team."""

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def post(self, request, team_pk):
        try:
            team = Team.objects.get(pk=team_pk)
        except Team.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        my_level, _ = _my_level(request.user, team)
        if my_level < ROLE_LEVELS["manager"]:
            return Response({"detail": "Manager or higher required."}, status=status.HTTP_403_FORBIDDEN)

        email = (request.data.get("email") or "").strip().lower()
        name = (request.data.get("name") or "").strip()
        password = request.data.get("password", "")
        role = (request.data.get("role") or "developer").lower()

        if not email:
            return Response({"detail": "Email is required."}, status=status.HTTP_400_BAD_REQUEST)
        if not name:
            return Response({"detail": "Name is required."}, status=status.HTTP_400_BAD_REQUEST)
        if password and len(password) < 8:
            return Response({"detail": "Password must be at least 8 characters."}, status=status.HTTP_400_BAD_REQUEST)
        if role not in ROLE_LEVELS:
            return Response({"detail": f"Invalid role: {role}"}, status=status.HTTP_400_BAD_REQUEST)
        if ROLE_LEVELS[role] > my_level:
            return Response({"detail": "Cannot assign a role higher than your own."}, status=status.HTTP_403_FORBIDDEN)

        # Owner-only, and refused before the account is touched so a manager
        # attempting it never half-creates a user.
        resolved_group, group_err = _resolve_sub_team(request, team)
        if group_err:
            return group_err
        group = None if resolved_group is _UNSET else resolved_group

        if TeamMembership.objects.filter(team=team, user__email=email).exists():
            return Response({"detail": "A user with this email is already a team member."}, status=status.HTTP_400_BAD_REQUEST)

        _ensure_seat_for(team, email)
        existing_user = User.objects.filter(email__iexact=email).first()
        if existing_user:
            return self._invite_existing_user(request, team, existing_user, role, group)

        parts = name.split(" ", 1)
        first_name = parts[0]
        last_name = parts[1] if len(parts) > 1 else ""

        set_password_url = None
        if password:
            # Path B — admin set a temporary password; force change on first login.
            try:
                validate_password(password)
            except DjangoValidationError as exc:
                return Response({"detail": " ".join(exc.messages)}, status=status.HTTP_400_BAD_REQUEST)
            user = User.objects.create_user(
                email=email, password=password, first_name=first_name, last_name=last_name,
            )
            user.must_change_password = True
            user.save(update_fields=["must_change_password"])
            email_body = (
                f"Hi {first_name},\n\n"
                f"An account has been created for you on Stacks Monitor by {request.user.email}.\n\n"
                f"Email: {email}\n"
                f"Team: {team.name} ({role})\n\n"
                f"Your administrator will share your temporary password separately. "
                f"You'll be asked to set your own password the first time you log in.\n\n"
                f"Log in at: {settings.FRONTEND_URL}/login\n"
            )
        else:
            # Path A — no password; email a set-password link (no credential emailed).
            user = User.objects.create_user(
                email=email, password=None, first_name=first_name, last_name=last_name,
            )
            user.set_unusable_password()
            user.save(update_fields=["password"])
            set_password_url = _issue_set_password_link(user, request.user)
            email_body = (
                f"Hi {first_name},\n\n"
                f"An account has been created for you on Stacks Monitor by {request.user.email}.\n\n"
                f"Email: {email}\n"
                f"Team: {team.name} ({role})\n\n"
                f"Set your password (link valid for 7 days):\n{set_password_url}\n\n"
                f"After setting your password you'll be guided through two-factor "
                f"authentication setup.\n"
            )

        membership = TeamMembership.objects.create(
            user=user, team=team, role=role, sub_team=group
        )
        if not user.active_team:
            User.objects.filter(pk=user.pk).update(active_team=team)

        email_sent = _send_account_email(
            "Your Stacks Monitor account has been created", email_body, email,
        )

        resp_data = TeamMembershipSerializer(membership).data
        resp_data["email_sent"] = email_sent
        # For the no-password path the member cannot log in until they set a
        # password. Return the set-password link to the admin so onboarding never
        # depends on email delivery (e.g. if SMTP is unconfigured/down).
        if set_password_url:
            resp_data["set_password_url"] = set_password_url

        return Response(resp_data, status=status.HTTP_201_CREATED)

    def _invite_existing_user(self, request, team, existing_user, role, group):
        """An account with this email already exists, possibly in another
        tenant. Adding it directly would let any team owner pull a stranger's
        account into their team (and, with the old set-password link in the
        response, take it over). So the person gets an invitation they accept
        while logged in as themselves, and no link ever reaches the admin."""
        invitation = _upsert_invitation(team, existing_user.email, role, request.user, group)
        accept_url = f"{settings.FRONTEND_URL}/invite/{invitation.token}"

        if not existing_user.is_active and not TeamMembership.objects.filter(user=existing_user).exists():
            # Deactivated when removed from their last team. They need to log
            # in to accept, and reviving grants nothing until they do.
            User.objects.filter(pk=existing_user.pk).update(is_active=True)

        first_name = existing_user.first_name or existing_user.email.split("@")[0]
        email_body = (
            f"Hi {first_name},\n\n"
            f"{request.user.email} has invited you to join {team.name} on Stacks Monitor as {role}.\n\n"
        )
        if existing_user.has_usable_password():
            email_body += (
                f"Log in with your existing account, then accept the invitation "
                f"(valid for 7 days):\n{accept_url}\n\n"
                f"Forgot your password? Use \"Forgot password\" on {settings.FRONTEND_URL}/login\n"
            )
        else:
            # Never finished onboarding: they need a password before they can
            # log in and accept. The link goes to their inbox only.
            set_password_url = _issue_set_password_link(existing_user, request.user)
            email_body += (
                f"Step 1: set your password (link valid for 7 days):\n{set_password_url}\n\n"
                f"Step 2: log in and accept the invitation:\n{accept_url}\n"
            )
        email_sent = _send_account_email(
            f"You've been invited to join {team.name} on Stacks Monitor", email_body, existing_user.email,
        )

        AuditService.log(
            actor=request.user, action=ActivityLog.Action.TEAM_MEMBER_INVITED,
            team=team,
            description=f"Invited {existing_user.email} as {role} (existing account)",
            resource_type="team_invitation", resource_id=str(invitation.pk),
        )
        return Response(
            {
                "detail": (
                    f"{existing_user.email} already has an account, so they were sent an "
                    f"invitation. They join {team.name} once they accept it."
                ),
                "invited": True,
                "email_sent": email_sent,
            },
            status=status.HTTP_201_CREATED,
        )


class PasswordResetThrottle(AnonRateThrottle):
    """Requests arrive through the Next.js server, so per-IP limits are loose.
    The per-account cooldown in the view is what actually stops mail floods."""
    scope = "auth"


class PasswordResetRequestView(APIView):
    """POST /api/v1/auth/password-reset/ — self-service reset (public).

    Emails a single-use link straight to the account's address. It used to
    queue the request for a manager to approve, and the approval response
    carried the link: any manager who shared a team with the user could reset
    their password, which is a takeover once strangers can own teams.
    """

    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = [PasswordResetThrottle]

    GENERIC_REPLY = "If that email is registered, we've sent a link to reset your password."
    LINK_LIFETIME = timedelta(hours=1)
    COOLDOWN = timedelta(minutes=2)

    def post(self, request):
        email = (request.data.get("email") or "").strip().lower()
        if not email:
            return Response({"detail": "Email is required."}, status=status.HTTP_400_BAD_REQUEST)

        # Every branch below returns the same reply, so this endpoint never
        # tells a caller which emails have accounts.
        user = User.objects.filter(email__iexact=email, is_active=True).first()
        if user is None:
            return Response({"detail": self.GENERIC_REPLY})

        now = timezone.now()
        if PasswordResetRequest.objects.filter(user=user, created_at__gte=now - self.COOLDOWN).exists():
            return Response({"detail": self.GENERIC_REPLY})

        # Only the newest link works. Older unused ones, including a 7-day
        # onboarding link, are retired so a leaked old email cannot be used.
        PasswordResetRequest.objects.filter(
            user=user, status=PasswordResetRequest.Status.APPROVED,
        ).update(status=PasswordResetRequest.Status.USED, reset_token=None)

        token = secrets.token_urlsafe(48)
        PasswordResetRequest.objects.create(
            user=user,
            status=PasswordResetRequest.Status.APPROVED,
            reset_token=token,
            approved_at=now,
            expires_at=now + self.LINK_LIFETIME,
        )
        reset_url = f"{settings.FRONTEND_URL}/reset-password?token={token}"
        _send_account_email(
            "Reset your Stacks Monitor password",
            (
                "Hi,\n\n"
                "Someone asked to reset the password for your Stacks Monitor account.\n\n"
                f"Set a new password (link valid for 1 hour, works once):\n{reset_url}\n\n"
                "If this wasn't you, ignore this email. Your password stays the same.\n"
            ),
            user.email,
        )
        return Response({"detail": self.GENERIC_REPLY})


class PasswordResetConfirmView(APIView):
    """POST /api/v1/auth/password-reset/confirm/ — user sets new password using approved token."""

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        token = (request.data.get("token") or "").strip()
        new_password = request.data.get("password", "")

        if not token:
            return Response({"detail": "Token is required."}, status=status.HTTP_400_BAD_REQUEST)
        if not new_password or len(new_password) < 8:
            return Response({"detail": "Password must be at least 8 characters."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            reset_req = PasswordResetRequest.objects.select_related("user").get(
                reset_token=token,
                status=PasswordResetRequest.Status.APPROVED,
            )
        except PasswordResetRequest.DoesNotExist:
            return Response({"detail": "Invalid or expired reset token."}, status=status.HTTP_400_BAD_REQUEST)

        if reset_req.expires_at and reset_req.expires_at < timezone.now():
            PasswordResetRequest.objects.filter(pk=reset_req.pk).update(status=PasswordResetRequest.Status.USED)
            return Response({"detail": "This reset link has expired."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            validate_password(new_password, user=reset_req.user)
        except DjangoValidationError as exc:
            return Response({"detail": " ".join(exc.messages)}, status=status.HTTP_400_BAD_REQUEST)

        reset_req.user.set_password(new_password)
        reset_req.user.save(update_fields=["password"])
        PasswordResetRequest.objects.filter(pk=reset_req.pk).update(
            status=PasswordResetRequest.Status.USED,
            reset_token=None,
        )
        return Response({"detail": "Password updated successfully. You can now log in."})


class TeamSettingsView(APIView):
    """GET/PATCH /api/v1/auth/teams/<pk>/settings/ — manage team integration settings."""

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def _get_team(self, request, pk):
        try:
            team = Team.objects.get(pk=pk)
        except Team.DoesNotExist:
            return None, Response(status=status.HTTP_404_NOT_FOUND)
        if not TeamMembership.objects.filter(user=request.user, team=team).exists():
            return None, Response({"detail": "Not a member of this team."}, status=status.HTTP_403_FORBIDDEN)
        return team, None

    def get(self, request, pk):
        team, err = self._get_team(request, pk)
        if err:
            return err
        return Response(TeamSettingsSerializer(team).data)

    def patch(self, request, pk):
        team, err = self._get_team(request, pk)
        if err:
            return err
        my_level, _ = _my_level(request.user, team)
        if my_level < ROLE_LEVELS["manager"]:
            return Response({"detail": "Manager or higher required to update settings."}, status=status.HTTP_403_FORBIDDEN)

        # Each field updates independently. Reading them unconditionally would
        # mean saving one silently clears the other — a PATCH that only carries
        # the list id must not log the team out of ClickUp.
        updated: list[str] = []
        changed_fields: list[str] = []

        if "clickup_api_token" in request.data:
            team.clickup_api_token = (request.data.get("clickup_api_token") or "").strip()
            changed_fields.append("_clickup_api_token")
            updated.append("token")

        if "clickup_list_id" in request.data:
            team.clickup_list_id = (request.data.get("clickup_list_id") or "").strip()
            changed_fields.append("clickup_list_id")
            updated.append("issue list")

        if "clickup_chat_url" in request.data:
            from apps.integrations.clickup import parse_clickup_chat

            chat_url = (request.data.get("clickup_chat_url") or "").strip()
            # A blank value is an intentional clear. A non-blank value that does
            # not parse would store a channel we can never post to, so reject it
            # here rather than failing silently at alert time.
            if chat_url and parse_clickup_chat(chat_url) == (None, None):
                return Response(
                    {"detail": "That does not look like a ClickUp Chat channel link."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            team.clickup_chat_url = chat_url
            changed_fields.append("clickup_chat_url")
            updated.append("team channel")

        if changed_fields:
            team.save(update_fields=changed_fields)
            AuditService.log_request(
                request, ActivityLog.Action.SETTINGS_INTEGRATION_UPDATED,
                description=f"Updated ClickUp integration ({', '.join(updated)})",
                resource_type="team", resource_id=str(team.pk),
            )
        return Response(TeamSettingsSerializer(team).data)


class ClickUpTestView(APIView):
    """POST /api/v1/auth/teams/<pk>/settings/clickup-test/ — verify ClickUp token works."""

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def post(self, request, pk):
        try:
            team = Team.objects.get(pk=pk)
        except Team.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        if not TeamMembership.objects.filter(user=request.user, team=team).exists():
            return Response({"detail": "Not a member."}, status=status.HTTP_403_FORBIDDEN)

        token = team.clickup_api_token
        if not token:
            return Response({"detail": "No ClickUp API token configured.", "connected": False}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user_data = ClickUpClient(token).whoami().get("user", {})
            return Response({
                "connected": True,
                "clickup_user": user_data.get("username") or user_data.get("email", ""),
            })
        except Exception as exc:
            logger.warning("ClickUp connectivity check failed for team %s: %s", pk, exc)
            return Response({"connected": False, "detail": "Could not reach ClickUp. Check your API token."}, status=status.HTTP_400_BAD_REQUEST)


class _ClickUpManagerView(APIView):
    """Shared auth for the ClickUp management endpoints: team member, manager+."""

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def _team_or_error(self, request, pk):
        try:
            team = Team.objects.get(pk=pk)
        except Team.DoesNotExist:
            return None, Response(status=status.HTTP_404_NOT_FOUND)
        if not TeamMembership.objects.filter(user=request.user, team=team).exists():
            return None, Response({"detail": "Not a member."}, status=status.HTTP_403_FORBIDDEN)
        my_level, _ = _my_level(request.user, team)
        if my_level < ROLE_LEVELS["manager"]:
            return None, Response(
                {"detail": "Manager or higher required."}, status=status.HTTP_403_FORBIDDEN
            )
        return team, None


class ClickUpChannelView(_ClickUpManagerView):
    """POST /api/v1/auth/teams/<pk>/settings/clickup-channel/

    Creates the web team's ClickUp Chat channel with every member we could match
    in ClickUp, and stores its URL on the team.
    """

    def post(self, request, pk):
        team, err = self._team_or_error(request, pk)
        if err:
            return err

        token = team.clickup_api_token
        if not token:
            return Response(
                {"detail": "Connect ClickUp first — no API token configured."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        sync = sync_member_links(team)
        workspace_id = sync.get("workspace_id")
        if not workspace_id:
            return Response(
                {"detail": "Could not read your ClickUp workspace. Check the API token."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        name = (request.data.get("name") or "Stacks Monitor — Web Team").strip()
        user_ids = [m["clickup_user_id"] for m in sync["matched"] if m.get("clickup_user_id")]

        try:
            channel = ClickUpClient(token).create_chat_channel(
                workspace_id,
                name=name,
                user_ids=user_ids,
                description="Website problems reported by Stacks Monitor.",
            )
        except ClickUpError as exc:
            logger.warning("ClickUp channel creation failed for team %s: %s", pk, exc)
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        url = channel.get("url") or ""
        if url:
            team.clickup_chat_url = url
            team.save(update_fields=["clickup_chat_url"])
            AuditService.log_request(
                request, ActivityLog.Action.SETTINGS_INTEGRATION_UPDATED,
                description="Created the ClickUp web team channel",
                resource_type="team", resource_id=str(team.pk),
            )

        return Response({
            "clickup_chat_url": team.clickup_chat_url,
            "matched": sync["matched"],
            "unmatched": sync["unmatched"],
        })


class ClickUpMembersView(_ClickUpManagerView):
    """POST /api/v1/auth/teams/<pk>/settings/clickup-members/

    Re-runs email matching and applies any manual `overrides`. An override is how
    a member whose ClickUp email differs gets mapped at all.
    """

    def post(self, request, pk):
        team, err = self._team_or_error(request, pk)
        if err:
            return err

        sync = sync_member_links(team)

        overrides = request.data.get("overrides") or []
        for override in overrides:
            user_id = (override or {}).get("user_id")
            clickup_user_id = str((override or {}).get("clickup_user_id") or "").strip()
            if not (user_id and clickup_user_id):
                continue
            # Scoped to team membership — an override must not create a mapping
            # for someone outside the team.
            membership = TeamMembership.objects.filter(
                team=team, user_id=user_id
            ).select_related("user").first()
            if membership:
                # Carry the handle across too. An override that stored only the
                # id left alerts rendering "@Muhammad Furqan" — the Stacks Monitor
                # full name behind an @, which ClickUp cannot resolve.
                set_member_link(
                    team, membership.user, clickup_user_id,
                    username_for_clickup_id(team, clickup_user_id),
                )

        if overrides:
            sync = sync_member_links(team)

        return Response({"matched": sync["matched"], "unmatched": sync["unmatched"]})
