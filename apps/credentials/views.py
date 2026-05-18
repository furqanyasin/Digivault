import uuid

from django.core.cache import cache
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from apps.common.permissions import IsTeamMember, RolePermission
from apps.credentials.models import Credential, CredentialAccessLog
from apps.credentials.serializers import (
    CredentialAccessLogSerializer,
    CredentialSerializer,
    CredentialWriteSerializer,
    RevealedCredentialSerializer,
)
from apps.credentials.services import CredentialService


def _get_client_ip(request) -> str | None:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


class CredentialListCreateView(generics.ListCreateAPIView):
    """GET /api/v1/websites/<website_pk>/credentials/
    POST /api/v1/websites/<website_pk>/credentials/
    """

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def get_serializer_class(self):
        if self.request.method == "POST":
            return CredentialWriteSerializer
        return CredentialSerializer

    def get_queryset(self):
        team = self.request.user.active_team
        if team is None:
            return Credential.objects.none()
        return Credential.objects.filter(
            website__team=team,
            website_id=self.kwargs["website_pk"],
        )

    def create(self, request, *args, **kwargs):
        team = request.user.active_team
        from apps.websites.models import Website

        try:
            website = Website.objects.get(pk=kwargs["website_pk"], team=team)
        except Website.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        serializer = CredentialWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        credential = CredentialService.create(
            website=website,
            label=d["label"],
            credential_type=d["credential_type"],
            login_url=d["login_url"],
            username=d["username"],
            password=d["password"],
            notes=d["notes"],
            created_by=request.user,
        )
        return Response(
            CredentialSerializer(credential).data, status=status.HTTP_201_CREATED
        )


class CredentialDetailView(generics.RetrieveUpdateDestroyAPIView):
    """GET/PATCH/DELETE /api/v1/credentials/<pk>/"""

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def get_serializer_class(self):
        if self.request.method in ("PATCH", "PUT"):
            return CredentialWriteSerializer
        return CredentialSerializer

    def get_queryset(self):
        team = self.request.user.active_team
        if team is None:
            return Credential.objects.none()
        return Credential.objects.filter(website__team=team)

    def update(self, request, *args, **kwargs):
        credential = self.get_object()
        serializer = CredentialWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data
        updated = CredentialService.update(
            credential=credential,
            label=d.get("label"),
            credential_type=d.get("credential_type"),
            login_url=d.get("login_url"),
            username=d.get("username"),
            password=d.get("password"),
            notes=d.get("notes"),
            updated_by=request.user,
        )
        return Response(CredentialSerializer(updated).data)


class CredentialRevealView(APIView):
    """POST /api/v1/credentials/<pk>/reveal/

    Returns decrypted credentials.  Every call is audit-logged.
    Viewer role is blocked at the service layer.
    """

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def post(self, request, pk):
        team = request.user.active_team
        try:
            credential = Credential.objects.get(pk=pk, website__team=team)
        except Credential.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        revealed = CredentialService.reveal(
            credential=credential,
            requesting_user=request.user,
            ip_address=_get_client_ip(request),
        )
        return Response(RevealedCredentialSerializer(revealed).data)


class CredentialAccessLogView(generics.ListAPIView):
    """GET /api/v1/websites/<website_pk>/credential-audit/"""

    serializer_class = CredentialAccessLogSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeamMember]
    required_role = "manager"

    def get_queryset(self):
        team = self.request.user.active_team
        if team is None:
            return CredentialAccessLog.objects.none()
        return CredentialAccessLog.objects.filter(
            credential__website__team=team,
            credential__website_id=self.kwargs["website_pk"],
        ).select_related("user")


class ExtensionCredentialLookupView(generics.ListAPIView):
    """GET /api/extension/credentials/?domain=<domain>

    Returns credential metadata for all credentials belonging to websites
    in the user's active team whose domain matches the query param.
    Never returns plaintext — callers must use the /reveal/ endpoint.
    """

    serializer_class = CredentialSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def list(self, request, *args, **kwargs):
        domain = request.query_params.get("domain", "").strip()
        if not domain:
            return Response(
                {"error": "domain parameter is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        team = self.request.user.active_team
        if team is None:
            return Credential.objects.none()
        domain = self.request.query_params.get("domain", "").strip().lower()
        return Credential.objects.filter(
            website__team=team,
            website__domain__iexact=domain,
        )


class ExtensionCredentialSaveView(APIView):
    """POST /api/extension/credentials/save/

    Captures a credential from the extension's save prompt and stores it
    encrypted under the matching website.  If a credential with the same
    username already exists for that website it is updated (password refreshed);
    otherwise a new one is created.

    Body: { domain, username, password, login_url? }
    Returns: { action: "created"|"updated", credential_id }
    """

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def post(self, request):
        domain = (request.data.get("domain") or "").strip().lower()
        username = (request.data.get("username") or "").strip()
        password = request.data.get("password") or ""
        login_url = (request.data.get("login_url") or "").strip()

        if not domain or not username or not password:
            return Response(
                {"error": "domain, username and password are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        team = request.user.active_team
        if not team:
            return Response({"error": "no_active_team"}, status=status.HTTP_400_BAD_REQUEST)

        from apps.websites.models import Website

        # Match domain exactly or with/without www
        bare = domain.removeprefix("www.")
        website = (
            Website.objects.filter(team=team, domain__iexact=domain).first()
            or Website.objects.filter(team=team, domain__iexact=bare).first()
            or Website.objects.filter(team=team, domain__iexact=f"www.{bare}").first()
        )
        if not website:
            return Response(
                {
                    "error": "website_not_found",
                    "detail": f"No website for '{domain}' found in your team. Add it first.",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        # Check for an existing credential with the same username (decrypt each)
        existing = None
        for cred in Credential.objects.filter(website=website):
            if cred.get_username() == username:
                existing = cred
                break

        if existing:
            CredentialService.update(
                credential=existing,
                password=password,
                login_url=login_url or None,
                updated_by=request.user,
            )
            return Response({"action": "updated", "credential_id": str(existing.id)})

        created = CredentialService.create(
            website=website,
            label=f"{domain} login",
            credential_type=Credential.CredentialType.CUSTOM,
            login_url=login_url,
            username=username,
            password=password,
            notes="",
            created_by=request.user,
        )
        return Response(
            {"action": "created", "credential_id": str(created.id)},
            status=status.HTTP_201_CREATED,
        )


class WebHandoffView(APIView):
    """POST /api/extension/web-handoff/

    Issues a short-lived one-time code (60 s, stored in Redis) that the
    Next.js /auth/extension page can exchange for HttpOnly session cookies.
    Requires a valid extension JWT — the code is bound to the authenticated user.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        refresh = RefreshToken.for_user(request.user)
        code = uuid.uuid4().hex
        cache.set(
            f"ext_handoff:{code}",
            {"access": str(refresh.access_token), "refresh": str(refresh)},
            timeout=60,
        )
        return Response({"code": code})


class WebHandoffExchangeView(APIView):
    """GET /api/extension/exchange/?code=<code>

    One-time exchange: returns the access + refresh tokens stored under the
    given code and immediately deletes the cache key (replay not possible).
    No authentication required — the code itself is the credential.
    """

    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def get(self, request):
        code = request.query_params.get("code", "").strip()
        if not code:
            return Response(
                {"detail": "code parameter is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        key = f"ext_handoff:{code}"
        tokens = cache.get(key)
        if tokens is None:
            return Response(
                {"detail": "Invalid or expired code"},
                status=status.HTTP_404_NOT_FOUND,
            )
        cache.delete(key)
        return Response(tokens)
