"""2FA / TOTP views using pyotp + Redis pre-auth session."""

import base64
import hashlib
import io
import logging
import secrets

import pyotp
import qrcode
from django.conf import settings
from django.core.cache import cache
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.tokens import RefreshToken

from apps.audit.models import ActivityLog
from apps.audit.services import AuditService
from apps.credentials.encryption import decrypt, encrypt


class PreAuthSessionAuthentication:
    """DRF authentication backend that accepts a pre-auth session key.

    Used only for the 2FA setup / confirm endpoints — allows a user who has
    passed email+password but not yet completed 2FA setup to request their
    QR code without a full JWT token.
    """

    def authenticate(self, request):
        key = request.META.get("HTTP_X_PRE_AUTH_KEY", "").strip()
        if not key:
            return None
        from apps.accounts.models import User
        user_id = cache.get(f"preauth:{key}")
        if not user_id:
            return None
        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None
        return (user, None)

    def authenticate_header(self, request):
        return "PreAuthKey"

logger = logging.getLogger(__name__)

_SESSION_TTL = 300        # 5 minutes
_DEVICE_TRUST_TTL = 36000  # 10 hours


class TotpSetupThrottle(UserRateThrottle):
    rate = "10/hour"
    scope = "totp_setup"


class TotpVerifyThrottle(AnonRateThrottle):
    rate = "10/minute"
    scope = "totp_verify"


def _issue_tokens(user) -> dict:
    refresh = RefreshToken.for_user(user)
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


def _get_totp_secret(user) -> str:
    """Decrypt and return the user's TOTP secret (raw base32 string)."""
    raw = bytes(user.totp_secret)
    return decrypt(raw)


def _set_totp_secret(user, secret: str) -> None:
    """Encrypt and save a TOTP secret to the user model."""
    user.totp_secret = encrypt(secret)
    user.save(update_fields=["totp_secret"])


def _hash_backup_code(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def _generate_backup_codes() -> tuple[list[str], list[str]]:
    """Return (plaintext_codes, hashed_codes) — store hashes, show plaintext once."""
    codes = [secrets.token_hex(4).upper() for _ in range(8)]
    hashed = [_hash_backup_code(c) for c in codes]
    return codes, hashed


class TotpSetupView(APIView):
    """GET /api/v1/auth/2fa/setup/ — generate a fresh TOTP secret and QR code.

    Accepts either a Bearer JWT (for already-authenticated users) or the
    X-Pre-Auth-Key header (for users mid-login who haven't set up 2FA yet).
    Does NOT enable 2FA yet; the user must confirm with a valid code first.
    """

    authentication_classes = [PreAuthSessionAuthentication, JWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [TotpSetupThrottle]

    def get(self, request):
        secret = pyotp.random_base32()
        totp = pyotp.TOTP(secret)
        name = request.user.email
        issuer = "Digivault"
        otp_url = totp.provisioning_uri(name=name, issuer_name=issuer)

        # Generate QR image as base64 PNG
        img = qrcode.make(otp_url)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        qr_b64 = base64.b64encode(buf.getvalue()).decode()

        # Cache the pending secret under the user's ID (not saved to DB yet)
        cache.set(f"totp_pending:{request.user.pk}", secret, timeout=600)

        AuditService.log_request(
            request, ActivityLog.Action.AUTH_2FA_SETUP_STARTED,
            description="Started 2FA setup",
        )

        return Response({
            "secret": secret,
            "otp_url": otp_url,
            "qr_code": f"data:image/png;base64,{qr_b64}",
        })


class TotpConfirmView(APIView):
    """POST /api/v1/auth/2fa/confirm/ — confirm TOTP code, enable 2FA, return backup codes."""

    authentication_classes = [PreAuthSessionAuthentication, JWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [TotpSetupThrottle]

    def post(self, request):
        code = (request.data.get("code") or "").strip()
        if not code:
            return Response({"detail": "code is required."}, status=status.HTTP_400_BAD_REQUEST)

        secret = cache.get(f"totp_pending:{request.user.pk}")
        if not secret:
            return Response(
                {"detail": "No pending 2FA setup. Call GET /api/v1/auth/2fa/setup/ first."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        totp = pyotp.TOTP(secret)
        if not totp.verify(code, valid_window=1):
            return Response({"detail": "Invalid code. Check your authenticator app."}, status=status.HTTP_400_BAD_REQUEST)

        plaintext_codes, hashed_codes = _generate_backup_codes()
        user = request.user
        _set_totp_secret(user, secret)
        user.totp_enabled = True
        user.totp_backup_codes = hashed_codes
        user.save(update_fields=["totp_enabled", "totp_backup_codes"])

        cache.delete(f"totp_pending:{user.pk}")

        AuditService.log_request(
            request, ActivityLog.Action.AUTH_2FA_ENABLED,
            description="2FA enabled via Google Authenticator",
        )

        response_data: dict = {
            "detail": "2FA enabled.",
            "backup_codes": plaintext_codes,
        }

        # If the user authenticated via pre-auth session key (mid-login setup flow),
        # issue JWT tokens so they land on the dashboard without a second login step.
        if isinstance(request.successful_authenticator, PreAuthSessionAuthentication):
            pre_auth_key = request.META.get("HTTP_X_PRE_AUTH_KEY", "")
            cache.delete(f"preauth:{pre_auth_key}")
            device_token = secrets.token_hex(32)
            cache.set(f"device_trust:{device_token}", str(user.pk), timeout=_DEVICE_TRUST_TTL)
            response_data.update(_issue_tokens(user))
            response_data["device_trust_token"] = device_token
            AuditService.log(
                actor=user, action=ActivityLog.Action.AUTH_LOGIN,
                team=user.active_team,
                description="Logged in after completing 2FA setup",
                ip_address=_get_ip(request),
            )

        return Response(response_data, status=status.HTTP_200_OK)


class TotpDisableView(APIView):
    """POST /api/v1/auth/2fa/disable/ — disable 2FA (manager can disable for other users)."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        from apps.accounts.models import User
        target_id = request.data.get("user_id")

        if target_id and str(target_id) != str(request.user.pk):
            # Only managers/owners can disable for others
            from apps.accounts.models import TeamMembership
            team = request.user.active_team
            if not team:
                return Response({"detail": "No active team."}, status=status.HTTP_403_FORBIDDEN)
            try:
                me = TeamMembership.objects.get(user=request.user, team=team)
            except TeamMembership.DoesNotExist:
                return Response({"detail": "Not authorised."}, status=status.HTTP_403_FORBIDDEN)
            if me.role not in ("manager", "owner"):
                return Response({"detail": "Manager or owner required."}, status=status.HTTP_403_FORBIDDEN)
            try:
                target = User.objects.get(pk=target_id)
            except User.DoesNotExist:
                return Response(status=status.HTTP_404_NOT_FOUND)
        else:
            target = request.user

        if not target.totp_enabled:
            return Response({"detail": "2FA is not enabled for this user."})

        target.totp_enabled = False
        target.totp_secret = b""
        target.totp_backup_codes = []
        target.save(update_fields=["totp_enabled", "totp_secret", "totp_backup_codes"])

        AuditService.log_request(
            request, ActivityLog.Action.AUTH_2FA_DISABLED,
            description=f"2FA disabled for {target.email}",
        )

        return Response({"detail": "2FA disabled."})


class TotpRegenerateBackupView(APIView):
    """POST /api/v1/auth/2fa/regenerate-backup/ — replace backup codes."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        user = request.user
        if not user.totp_enabled:
            return Response({"detail": "2FA is not enabled."}, status=status.HTTP_400_BAD_REQUEST)

        plaintext_codes, hashed_codes = _generate_backup_codes()
        user.totp_backup_codes = hashed_codes
        user.save(update_fields=["totp_backup_codes"])

        AuditService.log_request(
            request, ActivityLog.Action.AUTH_BACKUP_CODES_REGEN,
            description="Backup codes regenerated",
        )

        return Response({"backup_codes": plaintext_codes})


class TotpStatusView(APIView):
    """GET /api/v1/auth/2fa/status/ — return current 2FA status."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response({
            "totp_enabled": request.user.totp_enabled,
            "backup_codes_count": len(request.user.totp_backup_codes),
        })


class LoginView(APIView):
    """POST /api/v1/auth/login/ — email + password login with 2FA support.

    Response variants:
    - 2FA enrolled: { requires_2fa: true, session_key }
    - 2FA not set up (mandatory): { requires_setup: true, session_key }
    - No 2FA (legacy/bypass): { access, refresh }  [only if totp_enabled=False AND bypass allowed]
    """

    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request):
        from django.contrib.auth import authenticate

        email = (request.data.get("email") or "").strip().lower()
        password = request.data.get("password") or ""

        if not email or not password:
            return Response(
                {"detail": "Email and password are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = authenticate(request, username=email, password=password)
        if user is None:
            AuditService.log(
                actor=None,
                action=ActivityLog.Action.AUTH_LOGIN_FAILED,
                team=None,
                description=f"Failed login attempt for {email}",
                ip_address=_get_ip(request),
            )
            return Response(
                {"detail": "Invalid credentials."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # Store a short-lived pre-auth session key
        session_key = secrets.token_hex(32)
        cache.set(f"preauth:{session_key}", str(user.pk), timeout=_SESSION_TTL)

        if user.totp_enabled:
            # Check for a trusted device cookie (set after prior successful 2FA)
            device_token = request.META.get("HTTP_X_2FA_DEVICE_TOKEN", "").strip()
            if device_token:
                trusted_user_id = cache.get(f"device_trust:{device_token}")
                if trusted_user_id and str(trusted_user_id) == str(user.pk):
                    # Device trusted — skip 2FA prompt, issue tokens + roll device token
                    cache.delete(f"preauth:{session_key}")
                    cache.delete(f"device_trust:{device_token}")
                    new_device_token = secrets.token_hex(32)
                    cache.set(f"device_trust:{new_device_token}", str(user.pk), timeout=_DEVICE_TRUST_TTL)
                    AuditService.log(
                        actor=user, action=ActivityLog.Action.AUTH_LOGIN,
                        team=user.active_team,
                        description="Logged in (trusted device — 2FA skipped)",
                        ip_address=_get_ip(request),
                    )
                    return Response({**_issue_tokens(user), "device_trust_token": new_device_token})

            return Response({"requires_2fa": True, "session_key": session_key})

        # 2FA mandatory — not yet set up
        return Response({"requires_setup": True, "session_key": session_key})


class TotpVerifyView(APIView):
    """POST /api/v1/auth/2fa/verify/ — exchange pre-auth session_key + TOTP code for JWT pair."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = [TotpVerifyThrottle]

    def post(self, request):
        from apps.accounts.models import User

        session_key = (request.data.get("session_key") or "").strip()
        code = (request.data.get("code") or "").strip()

        if not session_key or not code:
            return Response(
                {"detail": "session_key and code are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user_id = cache.get(f"preauth:{session_key}")
        if not user_id:
            return Response(
                {"detail": "Session expired or invalid. Please log in again."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return Response(status=status.HTTP_401_UNAUTHORIZED)

        def _issue_with_device_trust(log_description: str) -> Response:
            device_token = secrets.token_hex(32)
            cache.set(f"device_trust:{device_token}", str(user.pk), timeout=_DEVICE_TRUST_TTL)
            AuditService.log(
                actor=user, action=ActivityLog.Action.AUTH_LOGIN,
                team=user.active_team,
                description=log_description,
                ip_address=_get_ip(request),
            )
            return Response({**_issue_tokens(user), "device_trust_token": device_token})

        # Try backup code first
        code_hash = _hash_backup_code(code.upper())
        if code_hash in user.totp_backup_codes:
            user.totp_backup_codes = [h for h in user.totp_backup_codes if h != code_hash]
            user.save(update_fields=["totp_backup_codes"])
            cache.delete(f"preauth:{session_key}")
            return _issue_with_device_trust("Logged in with backup code")

        # Verify TOTP
        if not user.totp_secret:
            return Response({"detail": "2FA not configured."}, status=status.HTTP_400_BAD_REQUEST)

        secret = _get_totp_secret(user)
        totp = pyotp.TOTP(secret)
        if not totp.verify(code, valid_window=1):
            return Response({"detail": "Invalid code."}, status=status.HTTP_401_UNAUTHORIZED)

        cache.delete(f"preauth:{session_key}")
        return _issue_with_device_trust("Logged in with 2FA")


def _get_ip(request) -> str | None:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")
