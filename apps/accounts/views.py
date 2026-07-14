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
from rest_framework.views import APIView

from apps.accounts.models import PasswordResetRequest, Team, TeamInvitation, TeamMembership, User
from apps.accounts.serializers import (
    PasswordResetRequestSerializer,
    TeamInvitationSerializer,
    TeamMembershipSerializer,
    TeamSerializer,
    TeamSettingsSerializer,
    UserRegistrationSerializer,
    UserSerializer,
)
from apps.accounts.services import TeamService
from apps.audit.models import ActivityLog
from apps.audit.services import AuditService
from apps.common.permissions import IsTeamMember

logger = logging.getLogger(__name__)

ROLE_LEVELS = {"viewer": 1, "developer": 2, "custom": 2, "editor": 2, "seo": 2, "manager": 3, "owner": 4}

from apps.accounts.features import FEATURE_KEYS, default_features


def _my_level(user, team):
    try:
        m = TeamMembership.objects.get(user=user, team=team)
        return ROLE_LEVELS.get(m.role, 0), m
    except TeamMembership.DoesNotExist:
        return 0, None


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


class RegisterView(APIView):
    """POST /api/v1/auth/register/"""

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = UserRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)


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
    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def get_queryset(self):
        return Team.objects.filter(memberships__user=self.request.user)

    def update(self, request, *args, **kwargs):
        team = self.get_object()
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
            .select_related("user")
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

        # Can't change the owner role (ownership transfer not supported here)
        if target.role == "owner":
            return Response({"detail": "Cannot change the owner's role."}, status=status.HTTP_403_FORBIDDEN)

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
        target.save(update_fields=["role", "feature_access", "updated_at"])
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

        # Can't remove yourself as owner
        if target.role == "owner":
            return Response({"detail": "Cannot remove the team owner."}, status=status.HTTP_403_FORBIDDEN)

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

        # Upsert invitation (resend if already pending) — always refresh expiry
        invitation, _ = TeamInvitation.objects.update_or_create(
            team=team, email=email,
            defaults={
                "invited_by": request.user,
                "role": role,
                "accepted": False,
                "accepted_at": None,
                "expires_at": timezone.now() + timedelta(days=7),
            },
        )

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
            f"{request.user.email} has invited you to join the {team.name} team on Digivault.\n\n"
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
                subject=f"You've been invited to join {team.name} on Digivault",
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
        from django.contrib.auth import authenticate
        from rest_framework_simplejwt.tokens import RefreshToken

        inv, err = self._get_invitation(token)
        if err:
            return err

        # Resolve the user
        if request.user.is_authenticated:
            user = request.user
            if user.email.lower() != inv.email.lower():
                return Response(
                    {"detail": f"This invitation is for {inv.email}. Log in with that account."},
                    status=status.HTTP_403_FORBIDDEN,
                )
            tokens = None
        else:
            # Allow accepting with email+password in one step
            password = request.data.get("password", "")
            user = authenticate(request, username=inv.email, password=password)
            if user is None:
                return Response(
                    {"detail": "Invalid password. Check your invitation email for your temporary password."},
                    status=status.HTTP_401_UNAUTHORIZED,
                )
            refresh = RefreshToken.for_user(user)
            tokens = {"access": str(refresh.access_token), "refresh": str(refresh)}

        # Create membership
        TeamMembership.objects.get_or_create(user=user, team=inv.team, defaults={"role": inv.role})

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

        payload = {"detail": f"You have joined {inv.team.name} as {inv.role}."}
        if tokens:
            payload["tokens"] = tokens
        return Response(payload)


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

        if TeamMembership.objects.filter(team=team, user__email=email).exists():
            return Response({"detail": "A user with this email is already a team member."}, status=status.HTTP_400_BAD_REQUEST)

        existing_user = User.objects.filter(email__iexact=email).first()
        if existing_user:
            # User account exists (e.g. previously removed from team) — add the membership.
            membership = TeamMembership.objects.create(user=existing_user, team=team, role=role)
            user_updates = {}
            if not existing_user.active_team:
                user_updates["active_team"] = team
            if not existing_user.is_active:
                # Account was deactivated when removed from its last team — revive it.
                user_updates["is_active"] = True
            if user_updates:
                User.objects.filter(pk=existing_user.pk).update(**user_updates)
                existing_user.refresh_from_db()
            AuditService.log(
                actor=request.user, action=ActivityLog.Action.TEAM_MEMBER_JOINED,
                team=team,
                description=f"{existing_user.email} added to team as {role} (existing account)",
                resource_type="team_membership",
            )
            resp_data = {"detail": f"{existing_user.email} added to team as {role}.", "id": str(membership.pk)}
            if existing_user.has_usable_password():
                # Fully-active account — they log in with their current password.
                # Still email them a reset link in case they've forgotten it, but
                # never return that link in the response: exposing it to the admin
                # would be a hijack vector for a live account.
                resp_data["already_active"] = True
                first_name = existing_user.first_name or existing_user.email.split("@")[0]
                reset_url = _issue_set_password_link(existing_user, request.user)
                email_body = (
                    f"Hi {first_name},\n\n"
                    f"You've been added to {team.name} on Digivault as {role} by {request.user.email}.\n\n"
                    f"Log in with your existing password at: {settings.FRONTEND_URL}/login\n\n"
                    f"Forgot your password? Use this link to set a new one "
                    f"(valid for 7 days):\n{reset_url}\n"
                )
                resp_data["email_sent"] = _send_account_email(
                    f"You've been added to {team.name} on Digivault", email_body, existing_user.email,
                )
            else:
                # Account exists but was never fully onboarded (no usable password,
                # e.g. invited earlier while SMTP was down). Re-issue a fresh
                # set-password link and email it so they can finally log in.
                first_name = existing_user.first_name or existing_user.email.split("@")[0]
                set_password_url = _issue_set_password_link(existing_user, request.user)
                email_body = (
                    f"Hi {first_name},\n\n"
                    f"You've been added to {team.name} on Digivault as {role} by {request.user.email}.\n\n"
                    f"Email: {existing_user.email}\n\n"
                    f"Set your password (link valid for 7 days):\n{set_password_url}\n\n"
                    f"After setting your password you'll be guided through two-factor "
                    f"authentication setup.\n"
                )
                resp_data["email_sent"] = _send_account_email(
                    "Your Digivault account has been created", email_body, existing_user.email,
                )
                resp_data["set_password_url"] = set_password_url
            return Response(resp_data, status=status.HTTP_201_CREATED)

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
                f"An account has been created for you on Digivault by {request.user.email}.\n\n"
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
                f"An account has been created for you on Digivault by {request.user.email}.\n\n"
                f"Email: {email}\n"
                f"Team: {team.name} ({role})\n\n"
                f"Set your password (link valid for 7 days):\n{set_password_url}\n\n"
                f"After setting your password you'll be guided through two-factor "
                f"authentication setup.\n"
            )

        membership = TeamMembership.objects.create(user=user, team=team, role=role)
        if not user.active_team:
            User.objects.filter(pk=user.pk).update(active_team=team)

        email_sent = _send_account_email(
            "Your Digivault account has been created", email_body, email,
        )

        resp_data = TeamMembershipSerializer(membership).data
        resp_data["email_sent"] = email_sent
        # For the no-password path the member cannot log in until they set a
        # password. Return the set-password link to the admin so onboarding never
        # depends on email delivery (e.g. if SMTP is unconfigured/down).
        if set_password_url:
            resp_data["set_password_url"] = set_password_url

        return Response(resp_data, status=status.HTTP_201_CREATED)


class PasswordResetRequestView(APIView):
    """POST /api/v1/auth/password-reset/ — user submits email to request a reset (public).
    GET  /api/v1/auth/password-reset/ — manager lists pending requests for their team's users.
    """

    def get_permissions(self):
        if self.request.method == "GET":
            return [permissions.IsAuthenticated()]
        return [permissions.AllowAny()]

    def post(self, request):
        email = (request.data.get("email") or "").strip().lower()
        if not email:
            return Response({"detail": "Email is required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            # Don't leak whether the email exists
            return Response({"detail": "If that email is registered, a reset request has been submitted for admin approval."})

        # Prevent duplicate pending requests
        existing = PasswordResetRequest.objects.filter(user=user, status=PasswordResetRequest.Status.PENDING).first()
        if existing:
            return Response({"detail": "A reset request is already pending admin approval."})

        PasswordResetRequest.objects.create(user=user)
        return Response({"detail": "Your reset request has been submitted. An admin will review it shortly."})

    def get(self, request):
        # Return pending requests for users in any team managed by the requester
        managed_teams = TeamMembership.objects.filter(
            user=request.user, role__in=["manager", "owner"]
        ).values_list("team_id", flat=True)
        team_user_ids = TeamMembership.objects.filter(team_id__in=managed_teams).values_list("user_id", flat=True)
        requests_qs = PasswordResetRequest.objects.filter(
            user_id__in=team_user_ids,
            status=PasswordResetRequest.Status.PENDING,
        ).select_related("user")
        return Response(PasswordResetRequestSerializer(requests_qs, many=True).data)


class PasswordResetApproveView(APIView):
    """POST /api/v1/auth/password-reset/<pk>/approve/ — manager approves and sends reset email."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        try:
            reset_req = PasswordResetRequest.objects.select_related("user").get(pk=pk, status=PasswordResetRequest.Status.PENDING)
        except PasswordResetRequest.DoesNotExist:
            return Response({"detail": "Request not found or already processed."}, status=status.HTTP_404_NOT_FOUND)

        # Must be a manager/owner of a team that this user belongs to
        shared_teams = TeamMembership.objects.filter(
            team__memberships__user=reset_req.user,
            user=request.user,
            role__in=["manager", "owner"],
        ).exists()
        if not shared_teams:
            return Response({"detail": "Not authorised to approve this request."}, status=status.HTTP_403_FORBIDDEN)

        token = secrets.token_urlsafe(48)
        PasswordResetRequest.objects.filter(pk=pk).update(
            status=PasswordResetRequest.Status.APPROVED,
            reset_token=token,
            approved_by=request.user,
            approved_at=timezone.now(),
            expires_at=timezone.now() + timedelta(hours=24),
        )

        reset_url = f"{settings.FRONTEND_URL}/reset-password?token={token}"
        try:
            send_mail(
                subject="Reset your Digivault password",
                message=(
                    f"Hi,\n\n"
                    f"Your password reset request has been approved.\n\n"
                    f"Click the link below to set a new password (expires in 24 hours):\n"
                    f"{reset_url}\n\n"
                    f"If you didn't request this, please contact your team admin.\n"
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[reset_req.user.email],
                fail_silently=False,
            )
        except Exception as exc:
            logger.error("Failed to send password reset email to %s: %s", reset_req.user.email, exc)
            return Response({"detail": "Approved but failed to send email. Check server logs."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({"detail": "Request approved and reset email sent.", "reset_url": reset_url})


class PasswordResetRejectView(APIView):
    """POST /api/v1/auth/password-reset/<pk>/reject/ — manager rejects a reset request."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        try:
            reset_req = PasswordResetRequest.objects.select_related("user").get(pk=pk, status=PasswordResetRequest.Status.PENDING)
        except PasswordResetRequest.DoesNotExist:
            return Response({"detail": "Request not found or already processed."}, status=status.HTTP_404_NOT_FOUND)

        shared_teams = TeamMembership.objects.filter(
            team__memberships__user=reset_req.user,
            user=request.user,
            role__in=["manager", "owner"],
        ).exists()
        if not shared_teams:
            return Response({"detail": "Not authorised to reject this request."}, status=status.HTTP_403_FORBIDDEN)

        PasswordResetRequest.objects.filter(pk=pk).update(
            status=PasswordResetRequest.Status.REJECTED,
            approved_by=request.user,
            approved_at=timezone.now(),
        )
        return Response({"detail": "Request rejected."})


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

        token = request.data.get("clickup_api_token", "").strip()
        team.clickup_api_token = token
        team.save(update_fields=["_clickup_api_token"])
        AuditService.log_request(
            request, ActivityLog.Action.SETTINGS_INTEGRATION_UPDATED,
            description="Updated ClickUp integration token",
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
            import requests as http_requests
            resp = http_requests.get(
                "https://api.clickup.com/api/v2/user",
                headers={"Authorization": token},
                timeout=10,
            )
            if resp.status_code == 200:
                user_data = resp.json().get("user", {})
                return Response({
                    "connected": True,
                    "clickup_user": user_data.get("username") or user_data.get("email", ""),
                })
            return Response({"connected": False, "detail": f"ClickUp returned {resp.status_code}."}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            logger.warning("ClickUp connectivity check failed for team %s: %s", pk, exc)
            return Response({"connected": False, "detail": "Could not reach ClickUp. Check your API token."}, status=status.HTTP_400_BAD_REQUEST)
