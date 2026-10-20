"""Public self-signup: request an account, then confirm the email.

POST /api/v1/auth/signup/        name, email, password, workspace_name
POST /api/v1/auth/verify-email/  token -> creates the user + a free workspace

Nothing is created until the email link is clicked, so a stranger who types
someone else's address gets nothing to log in to. Both endpoints answer the
same way whether or not the email already has an account.
"""

from __future__ import annotations

import hashlib
import logging
import re
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from apps.accounts.models import PendingSignup, Team, User
from apps.accounts.services import TeamService
from apps.accounts.views import _send_account_email
from apps.audit.models import ActivityLog
from apps.audit.services import AuditService

logger = logging.getLogger(__name__)

LINK_LIFETIME = timedelta(hours=48)
RESEND_COOLDOWN = timedelta(seconds=60)

# Throwaway inboxes. Not complete, it only stops the laziest abuse.
DISPOSABLE_DOMAINS = frozenset({
    "mailinator.com", "guerrillamail.com", "guerrillamail.net", "10minutemail.com",
    "tempmail.com", "temp-mail.org", "yopmail.com", "throwawaymail.com",
    "trashmail.com", "getnada.com", "dispostable.com", "sharklasers.com",
    "maildrop.cc", "fakeinbox.com", "mintemail.com", "mohmal.com", "emailondeck.com",
})

GENERIC_REPLY = "Check your inbox. We sent a link to confirm your email and finish creating your account."


class SignupThrottle(AnonRateThrottle):
    scope = "signup"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _split_name(name: str) -> tuple[str, str]:
    parts = name.strip().split(" ", 1)
    return parts[0][:150], (parts[1] if len(parts) > 1 else "")[:150]


class SignupView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = [SignupThrottle]

    def post(self, request):
        data = request.data
        # Honeypot: a field people never see. Bots fill every input.
        if (data.get("company_website") or "").strip():
            return Response({"detail": GENERIC_REPLY})

        name = (data.get("name") or "").strip()
        email = (data.get("email") or "").strip().lower()
        password = data.get("password") or ""
        workspace = (data.get("workspace_name") or "").strip()[:100]

        if not name:
            return Response({"detail": "Please enter your name."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            validate_email(email)
        except DjangoValidationError:
            return Response({"detail": "Please enter a valid email address."}, status=status.HTTP_400_BAD_REQUEST)
        if email.rsplit("@", 1)[-1] in DISPOSABLE_DOMAINS:
            return Response(
                {"detail": "Please use your work or personal email, not a temporary inbox."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        first_name, last_name = _split_name(name)
        try:
            validate_password(password, user=User(email=email, first_name=first_name, last_name=last_name))
        except DjangoValidationError as exc:
            return Response({"detail": " ".join(exc.messages)}, status=status.HTTP_400_BAD_REQUEST)

        now = timezone.now()
        if PendingSignup.objects.filter(email=email, created_at__gte=now - RESEND_COOLDOWN).exists():
            return Response({"detail": GENERIC_REPLY})

        existing = User.objects.filter(email__iexact=email).first()
        if existing is not None and _in_use(existing):
            # A real, used account. Tell its owner instead of the caller, and
            # never let a signup set the password of an account in use.
            _send_account_email(
                "You already have a Stacks Monitor account",
                (
                    f"Hi,\n\nSomeone tried to create a Stacks Monitor account with {email}, "
                    "but this email already has one.\n\n"
                    f"Log in: {settings.FRONTEND_URL}/login\n"
                    f"Forgot your password? {settings.FRONTEND_URL}/forgot-password\n\n"
                    "If this wasn't you, you can ignore this email.\n"
                ),
                email,
            )
            return Response({"detail": GENERIC_REPLY})

        token = secrets.token_urlsafe(32)
        PendingSignup.objects.create(
            email=email,
            first_name=first_name,
            last_name=last_name,
            workspace_name=workspace,
            password_hash=make_password(password),
            token_hash=_hash(token),
            expires_at=now + LINK_LIFETIME,
        )
        verify_url = f"{settings.FRONTEND_URL}/verify-email?token={token}"
        sent = _send_account_email(
            "Confirm your email for Stacks Monitor",
            (
                f"Hi {first_name},\n\n"
                "Thanks for signing up for Stacks Monitor.\n\n"
                f"Confirm your email to finish creating your account (link valid for 48 hours):\n{verify_url}\n\n"
                "If you didn't sign up, ignore this email and no account will be created.\n"
            ),
            email,
        )
        if not sent:
            logger.error("Signup verification email to %s was not sent", email)
        if settings.DEBUG:
            logger.info("Signup verification link for %s: %s", email, verify_url)
        return Response({"detail": GENERIC_REPLY})


def _in_use(user) -> bool:
    """An account someone already holds a password for.

    The other kind is one an owner created for this email that was never set
    up (no password yet, or still on the owner's temporary one). Proving the
    email by clicking the link is enough to claim that kind.
    """
    return user.has_usable_password() and not user.must_change_password


def _default_workspace_name(first_name: str, email: str) -> str:
    base = first_name or re.sub(r"[^A-Za-z0-9]+", " ", email.split("@")[0]).strip() or "My"
    return f"{base}'s workspace"[:100]


class VerifyEmailView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = [SignupThrottle]

    def post(self, request):
        from apps.accounts.totp_views import _issue_tokens, _two_factor_required

        token = (request.data.get("token") or "").strip()
        if not token:
            return Response({"detail": "The link is missing its token."}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            pending = (
                PendingSignup.objects.select_for_update()
                .filter(token_hash=_hash(token), used_at__isnull=True)
                .first()
            )
            if pending is None:
                return Response(
                    {"detail": "This link was already used or is not valid. Try logging in, or sign up again."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if pending.expires_at < timezone.now():
                return Response(
                    {"detail": "This link has expired. Please sign up again."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            user = User.objects.select_for_update().filter(email__iexact=pending.email).first()
            if user is not None and _in_use(user):
                # Someone else signed in to this address since the link was
                # sent. Refuse rather than overwrite a password in use.
                pending.used_at = timezone.now()
                pending.save(update_fields=["used_at"])
                return Response(
                    {"detail": "This email already has an account. Log in, or reset your password."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            created = user is None
            if created:
                user = User.objects.create_user(
                    email=pending.email, password=None,
                    first_name=pending.first_name, last_name=pending.last_name,
                )
            elif not user.first_name:
                user.first_name, user.last_name = pending.first_name, pending.last_name
            # The hash was made from the password typed at signup.
            user.password = pending.password_hash
            user.is_active = True
            user.must_change_password = False
            # The email is proven now, so a listed platform owner gets their
            # rights straight away instead of at the next api restart.
            owners = {e.strip().lower() for e in getattr(settings, "PLATFORM_OWNER_EMAILS", [])}
            if user.email.lower() in owners:
                user.is_superuser = user.is_staff = True
            user.save()

            team = Team.objects.filter(owner=user).order_by("created_at").first()
            if team is None:
                # TeamService.create also makes it the active team.
                team = TeamService.create(
                    name=pending.workspace_name or _default_workspace_name(pending.first_name, pending.email),
                    owner=user, plan=Team.Plan.FREE, require_2fa=False,
                )
            else:
                # They signed up to use their own workspace, so open it first
                # even if they were also added to someone else's team.
                User.objects.filter(pk=user.pk).update(active_team=team)
                user.active_team = team

            now = timezone.now()
            PendingSignup.objects.filter(email__iexact=pending.email, used_at__isnull=True).update(used_at=now)

        AuditService.log(
            actor=user, action=ActivityLog.Action.AUTH_SIGNUP, team=team,
            description=f"{user.email} signed up and created '{team.name}'",
            resource_type="team", resource_id=team.pk,
        )

        if _two_factor_required(user):
            return Response({"detail": "Email confirmed. Log in to continue.", "login_required": True})
        return Response({"detail": "Email confirmed.", **_issue_tokens(user)})


class TwoFactorReminderDismissView(APIView):
    """POST /api/v1/auth/me/2fa-reminder/dismiss/ — hide the banner for 24 hours."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        User.objects.filter(pk=request.user.pk).update(twofa_reminder_dismissed_at=timezone.now())
        return Response({"detail": "We'll remind you tomorrow."})
