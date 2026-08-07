import csv
import io
import uuid
from urllib.parse import urlparse

from django.core.cache import cache
from rest_framework import generics, permissions, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from apps.audit.models import ActivityLog
from apps.audit.services import AuditService, site_meta
from apps.common.permissions import IsTeamMember, RolePermission
from apps.credentials.models import Credential, CredentialAccessLog, CredentialShare
from apps.credentials.permissions import can_modify_credential
from apps.credentials.serializers import (
    CredentialAccessLogSerializer,
    CredentialSerializer,
    CredentialShareSerializer,
    CredentialShareWriteSerializer,
    CredentialWriteSerializer,
    RevealedCredentialSerializer,
)
from apps.credentials.services import CredentialService


def _display_name(user) -> str:
    """A human label for a user: full name if set, else email."""
    if user is None:
        return "a user"
    full = f"{user.first_name} {user.last_name}".strip()
    return full or user.email


class CredentialSaveThrottle(UserRateThrottle):
    rate = "100/hour"
    scope = "credential_save"


class HandoffExchangeThrottle(AnonRateThrottle):
    rate = "20/minute"
    scope = "handoff_exchange"


def _get_client_ip(request) -> str | None:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


class TeamCredentialListCreateView(generics.ListCreateAPIView):
    """GET /api/v1/credentials/ — all credentials for the active team (both website and standalone)
    POST /api/v1/credentials/ — create a standalone or website-linked credential
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
        return (
            Credential.objects.visible_to(self.request.user)
            .filter(team=team)
            .select_related("website")
        )

    def create(self, request, *args, **kwargs):
        team = request.user.active_team
        if team is None:
            return Response(status=status.HTTP_403_FORBIDDEN)

        serializer = CredentialWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        website = None
        website_id = d.get("website_id")
        if website_id:
            from apps.websites.models import Website
            try:
                website = Website.objects.get(pk=website_id, team=team)
            except Website.DoesNotExist:
                return Response(
                    {"detail": "Website not found."}, status=status.HTTP_404_NOT_FOUND
                )

        credential = CredentialService.create(
            team=team,
            website=website,
            label=d["label"],
            credential_type=d["credential_type"],
            login_url=d["login_url"],
            username=d["username"],
            password=d["password"],
            notes=d["notes"],
            created_by=request.user,
        )
        AuditService.log_request(
            request, ActivityLog.Action.CREDENTIAL_CREATED,
            description=f"Created credential '{credential.label}'",
            resource_type="credential", resource_id=credential.pk,
            metadata=site_meta(credential),
        )
        return Response(
            CredentialSerializer(credential).data, status=status.HTTP_201_CREATED
        )


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
        return (
            Credential.objects.visible_to(self.request.user)
            .filter(team=team, website_id=self.kwargs["website_pk"])
            .select_related("website")
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
            team=team,
            website=website,
            label=d["label"],
            credential_type=d["credential_type"],
            login_url=d["login_url"],
            username=d["username"],
            password=d["password"],
            notes=d["notes"],
            created_by=request.user,
        )
        AuditService.log_request(
            request, ActivityLog.Action.CREDENTIAL_CREATED,
            description=f"Created credential '{credential.label}'",
            resource_type="credential", resource_id=credential.pk,
            metadata=site_meta(credential),
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
        return (
            Credential.objects.visible_to(self.request.user)
            .filter(team=team)
            .select_related("website")
        )

    def update(self, request, *args, **kwargs):
        credential = self.get_object()
        if not can_modify_credential(request.user, credential):
            return Response(status=status.HTTP_403_FORBIDDEN)
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
        changed_fields = [k for k in ("label", "credential_type", "login_url", "username", "password", "notes") if d.get(k) is not None]
        AuditService.log_request(
            request, ActivityLog.Action.CREDENTIAL_UPDATED,
            description=f"Updated credential '{updated.label}'",
            resource_type="credential", resource_id=updated.pk,
            metadata=site_meta(updated, fields_changed=changed_fields),
        )
        return Response(CredentialSerializer(updated).data)

    def perform_destroy(self, instance):
        if not can_modify_credential(self.request.user, instance):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied()
        AuditService.log_request(
            self.request, ActivityLog.Action.CREDENTIAL_DELETED,
            description=f"Deleted credential '{instance.label}'",
            resource_type="credential", resource_id=instance.pk,
            metadata=site_meta(instance),
        )
        instance.delete()


class CredentialRevealView(APIView):
    """POST /api/v1/credentials/<pk>/reveal/

    Returns decrypted credentials.  Every call is audit-logged.
    Viewer role is blocked at the service layer.
    """

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def post(self, request, pk):
        team = request.user.active_team
        try:
            credential = (
                Credential.objects.visible_to(request.user)
                .get(pk=pk, team=team)
            )
        except Credential.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        for_autofill = (
            str(request.query_params.get("for_autofill", "")).lower() in ("1", "true")
            or bool(request.data.get("for_autofill"))
        )
        revealed = CredentialService.reveal(
            credential=credential,
            requesting_user=request.user,
            ip_address=_get_client_ip(request),
            for_autofill=for_autofill,
        )
        AuditService.log_request(
            request, ActivityLog.Action.CREDENTIAL_REVEALED,
            description=f"Revealed credential '{credential.label}'",
            resource_type="credential", resource_id=credential.pk,
            metadata=site_meta(credential),
        )
        return Response(RevealedCredentialSerializer(revealed).data)


class CredentialAccessLogView(generics.ListAPIView):
    """GET /api/v1/websites/<website_pk>/credential-audit/"""

    serializer_class = CredentialAccessLogSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeamMember, RolePermission]
    required_role = "manager"

    def get_queryset(self):
        team = self.request.user.active_team
        if team is None:
            return CredentialAccessLog.objects.none()
        return CredentialAccessLog.objects.filter(
            credential__team=team,
            credential__website_id=self.kwargs["website_pk"],
        ).select_related("user")


class ExtensionCredentialLookupView(generics.ListAPIView):
    """GET /api/extension/credentials/?domain=<domain>

    With a `domain` param, returns credential metadata for the user's active
    team whose website domain or login_url matches that host. Without a domain
    (or with `?all=1`), returns every credential visible to the user — this
    backs the extension's "All items" tab so the user can open any site
    directly. Never returns plaintext — callers must use the /reveal/ endpoint.
    """

    serializer_class = CredentialSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def get_queryset(self):
        from django.db.models import Q

        team = self.request.user.active_team
        if team is None:
            return Credential.objects.none()

        visible = Credential.objects.visible_to(self.request.user).filter(team=team)

        domain = self.request.query_params.get("domain", "").strip().lower()
        if not domain:
            # No domain → full vault (newest first), for the "All items" tab.
            return visible.order_by("-updated_at")

        bare = domain.removeprefix("www.")
        # Match a website-linked credential by the website's domain (with/without
        # www), OR any credential — including standalone hosting logins — whose
        # login_url points at this host. Anchoring on "//host" keeps it from
        # matching the host inside a path.
        match = (
            Q(website__domain__iexact=domain)
            | Q(website__domain__iexact=bare)
            | Q(website__domain__iexact=f"www.{bare}")
            | Q(login_url__icontains=f"//{bare}")
            | Q(login_url__icontains=f"//www.{bare}")
        )
        return visible.filter(match).distinct()


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
    throttle_classes = [CredentialSaveThrottle]

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

        # Look up existing credential by username hash — no decryption loop
        existing = Credential.objects.filter(
            website=website,
            username_hash=Credential.hash_username(username),
        ).first()

        if existing:
            CredentialService.update(
                credential=existing,
                password=password,
                login_url=login_url or None,
                updated_by=request.user,
            )
            return Response({"action": "updated", "credential_id": str(existing.id)})

        created = CredentialService.create(
            team=team,
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
    throttle_classes = [HandoffExchangeThrottle]

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


class CredentialShareListCreateView(APIView):
    """GET/POST /api/v1/credentials/<pk>/shares/"""

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def _get_credential(self, request, pk):
        team = request.user.active_team
        if team is None:
            return None
        return (
            Credential.objects
            .visible_to(request.user)
            .filter(pk=pk, team=team)
            .first()
        )

    def get(self, request, pk):
        cred = self._get_credential(request, pk)
        if cred is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        shares = cred.shares.select_related("user", "shared_by")
        return Response(
            CredentialShareSerializer(shares, many=True).data
        )

    def post(self, request, pk):
        cred = self._get_credential(request, pk)
        if cred is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        if not can_modify_credential(request.user, cred):
            return Response(status=status.HTTP_403_FORBIDDEN)

        ser = CredentialShareWriteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        from apps.accounts.models import TeamMembership

        memberships = TeamMembership.objects.filter(
            team=cred.team, user_id__in=ser.validated_data["user_ids"]
        ).select_related("user")
        valid_user_ids = {m.user_id for m in memberships}
        invalid = set(ser.validated_data["user_ids"]) - valid_user_ids
        if invalid:
            return Response(
                {"detail": f"Users not in team: {sorted(str(u) for u in invalid)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Only developers need shares; owners/managers already have access.
        target_members = [
            m for m in memberships
            if m.role in (TeamMembership.Role.DEVELOPER, TeamMembership.Role.EDITOR, TeamMembership.Role.SEO)
        ]
        can_view = ser.validated_data["can_view_password"]
        affected_ids = []
        for m in target_members:
            CredentialShare.objects.update_or_create(
                credential=cred, user_id=m.user_id,
                defaults={"shared_by": request.user, "can_view_password": can_view},
            )
            affected_ids.append(str(m.user_id))

        if affected_ids:
            who = ", ".join(_display_name(m.user) for m in target_members)
            AuditService.log_request(
                request, ActivityLog.Action.CREDENTIAL_SHARED,
                description=f"Shared credential '{cred.label}' with {who}",
                resource_type="credential", resource_id=cred.pk,
                metadata={"shared_with_user_ids": affected_ids, "can_view_password": can_view},
            )
        created_ids = affected_ids

        shares = cred.shares.select_related("user", "shared_by")
        return Response(
            CredentialShareSerializer(shares, many=True).data,
            status=status.HTTP_201_CREATED if created_ids else status.HTTP_200_OK,
        )


class WebsiteCredentialShareView(APIView):
    """POST /api/v1/websites/<website_pk>/credentials/share/

    Share every credential of a website with the given developers at once.
    Applies the same `can_view_password` flag across all of them.
    """

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def post(self, request, website_pk):
        team = request.user.active_team
        if team is None:
            return Response(status=status.HTTP_403_FORBIDDEN)

        from apps.accounts.models import TeamMembership

        ser = CredentialShareWriteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        can_view = ser.validated_data["can_view_password"]

        memberships = TeamMembership.objects.filter(
            team=team, user_id__in=ser.validated_data["user_ids"]
        )
        valid_user_ids = {m.user_id for m in memberships}
        invalid = set(ser.validated_data["user_ids"]) - valid_user_ids
        if invalid:
            return Response(
                {"detail": f"Users not in team: {sorted(str(u) for u in invalid)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        target_user_ids = [
            m.user_id for m in memberships
            if m.role in (TeamMembership.Role.DEVELOPER, TeamMembership.Role.EDITOR, TeamMembership.Role.SEO)
        ]

        creds = Credential.objects.filter(team=team, website_id=website_pk)
        shared_cred_count = 0
        for cred in creds:
            if not can_modify_credential(request.user, cred):
                continue
            for uid in target_user_ids:
                CredentialShare.objects.update_or_create(
                    credential=cred, user_id=uid,
                    defaults={"shared_by": request.user, "can_view_password": can_view},
                )
            shared_cred_count += 1

        if shared_cred_count and target_user_ids:
            AuditService.log_request(
                request, ActivityLog.Action.CREDENTIAL_SHARED,
                description=f"Shared {shared_cred_count} site credential(s)",
                resource_type="website", resource_id=website_pk,
                metadata={
                    "shared_with_user_ids": [str(u) for u in target_user_ids],
                    "credential_count": shared_cred_count,
                    "can_view_password": can_view,
                },
            )
        return Response(
            {"shared_credentials": shared_cred_count, "developers": len(target_user_ids)},
            status=status.HTTP_200_OK,
        )


class CredentialShareDeleteView(APIView):
    """DELETE /api/v1/credentials/<pk>/shares/<user_id>/"""

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def delete(self, request, pk, user_id):
        team = request.user.active_team
        if team is None:
            return Response(status=status.HTTP_403_FORBIDDEN)
        try:
            cred = Credential.objects.get(pk=pk, team=team)
        except Credential.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        if not can_modify_credential(request.user, cred):
            return Response(status=status.HTTP_403_FORBIDDEN)
        from apps.accounts.models import User
        target = User.objects.filter(pk=user_id).first()

        deleted, _ = CredentialShare.objects.filter(
            credential=cred, user_id=user_id
        ).delete()
        if not deleted:
            return Response(status=status.HTTP_404_NOT_FOUND)

        who = _display_name(target) if target else "a user"
        AuditService.log_request(
            request, ActivityLog.Action.CREDENTIAL_UNSHARED,
            description=f"Unshared credential '{cred.label}' from {who}",
            resource_type="credential", resource_id=cred.pk,
            metadata={"unshared_user_id": str(user_id)},
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


# Map LastPass URL/grouping hints to our credential types.
_LP_TYPE_HINTS = [
    ("wp-admin", "wordpress"), ("wp-login", "wordpress"), ("siteground", "siteground"),
    ("cpanel", "cpanel"), ("cloudflare", "cloudflare"), ("godaddy", "godaddy"),
    ("namecheap", "namecheap"), ("hostinger", "hostinger"), ("shopify", "shopify"),
    ("wix.com", "wix"), ("webflow", "webflow"), ("framer", "framer"),
    ("wpengine", "wpengine"), ("wpenginepowered", "wpengine"), ("kinsta", "kinsta"),
    ("bluehost", "bluehost"),
]


def _guess_credential_type(url: str, grouping: str) -> str:
    blob = f"{url} {grouping}".lower()
    for needle, ctype in _LP_TYPE_HINTS:
        if needle in blob:
            return ctype
    return "custom"


# Column widths on Credential — a CSV row longer than these would raise a
# DataError mid-import and abandon every row after it.
_LABEL_MAX = 200
_URL_MAX = 500


def _normalize_login_url(url: str) -> str:
    """Identity form of a login URL — scheme, case and trailing slash removed.

    Only used to decide whether two rows describe the same login; the original
    URL is what gets stored.
    """
    u = (url or "").strip().lower()
    u = u.removeprefix("https://").removeprefix("http://")
    return u.rstrip("/")


def _import_identity(website_id, username_hash: str, login_url: str, label: str) -> tuple:
    """What makes an imported login unique.

    A credential is "the same login" only when it is the same account (username)
    at the same *service*. Keying on username alone collapses every hosting panel
    an agency signs into with one shared email down to a single row. The login URL
    names the service; when a row has no URL, its label is the only thing left to
    tell it apart.
    """
    url_key = _normalize_login_url(login_url)
    return (website_id, username_hash, url_key or f"label:{label.strip().lower()}")


class CredentialImportView(APIView):
    """POST /api/v1/credentials/import/ — import a LastPass CSV export.

    Expected columns (LastPass default): url, username, password, totp, extra,
    name, grouping, fav. Each row becomes an encrypted Credential. When the URL's
    host matches a team website the credential links to it; otherwise it's a
    standalone (Hosting & General) login. Re-importing the same login — same
    account at the same service — refreshes the stored password instead of
    duplicating.

    Owner/manager only: an import writes to the whole team's vault.
    """

    permission_classes = [permissions.IsAuthenticated, IsTeamMember, RolePermission]
    required_role = "manager"
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request):
        team = request.user.active_team
        if team is None:
            return Response({"detail": "No active team."}, status=status.HTTP_400_BAD_REQUEST)

        file_obj = request.FILES.get("file")
        if not file_obj:
            return Response({"detail": "No file provided."}, status=status.HTTP_400_BAD_REQUEST)
        if file_obj.size > 5 * 1024 * 1024:
            return Response({"detail": "File too large (max 5 MB)."}, status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)

        try:
            text = file_obj.read().decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(text))
        except Exception:
            return Response(
                {"detail": "Could not read the CSV. Export from LastPass as a CSV file and try again."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from apps.websites.models import Website

        # Index the team's existing vault once. Looking each row up with its own
        # query was both N queries and — because the lookup ignored the service —
        # the reason distinct logins overwrote each other.
        index: dict[tuple, Credential] = {}
        for cred in Credential.objects.filter(team=team):
            index.setdefault(
                _import_identity(cred.website_id, cred.username_hash, cred.login_url, cred.label),
                cred,
            )

        # Domains resolve to the same handful of websites over and over.
        website_cache: dict[str, object] = {}

        def _website_for(host: str):
            if host in website_cache:
                return website_cache[host]
            bare = host.removeprefix("www.")
            site = (
                Website.objects.filter(team=team, domain__iexact=host).first()
                or Website.objects.filter(team=team, domain__iexact=bare).first()
                or Website.objects.filter(team=team, domain__iexact=f"www.{bare}").first()
            )
            website_cache[host] = site
            return site

        rows = created = updated = skipped = failed = 0
        errors: list[str] = []

        for line_no, row in enumerate(reader, start=2):  # line 1 is the header
            rows += 1
            try:
                name = (row.get("name") or "").strip()
                url = (row.get("url") or "").strip()
                username = (row.get("username") or "").strip()
                password = row.get("password") or ""
                extra = (row.get("extra") or "").strip()
                totp = (row.get("totp") or "").strip()
                grouping = (row.get("grouping") or "").strip()

                # Skip secure notes / rows with no usable login.
                if not username and not password:
                    skipped += 1
                    continue

                notes = extra
                if totp:
                    notes = (notes + "\n" if notes else "") + f"TOTP secret: {totp}"

                # Link to a team website when the host matches; else standalone.
                host = ""
                try:
                    parsed = urlparse(url if "://" in url else f"https://{url}")
                    host = (parsed.hostname or "").lower()
                except ValueError:
                    host = ""
                website = _website_for(host) if host else None

                label = (name or host or "Imported login")[:_LABEL_MAX]
                cred_type = _guess_credential_type(url, grouping)

                # A URL past the column width would blow up the insert. Keep the
                # full value in the notes rather than storing a truncated link.
                stored_url = url
                if len(stored_url) > _URL_MAX:
                    notes = (notes + "\n" if notes else "") + f"Full login URL: {url}"
                    stored_url = ""

                key = _import_identity(
                    website.id if website else None,
                    Credential.hash_username(username),
                    stored_url or url,
                    label,
                )
                existing = index.get(key)

                if existing:
                    # The CSV is the source of truth on re-import: refresh the
                    # label and type too, so a repeat import repairs rows left
                    # mislabelled by an earlier one rather than freezing them.
                    CredentialService.update(
                        credential=existing,
                        label=label,
                        credential_type=cred_type,
                        password=password or None,
                        login_url=stored_url or None,
                        updated_by=request.user,
                    )
                    updated += 1
                else:
                    cred = CredentialService.create(
                        label=label, credential_type=cred_type, login_url=stored_url,
                        username=username, password=password, notes=notes,
                        created_by=request.user, team=team, website=website,
                    )
                    index[key] = cred
                    created += 1
            except Exception as exc:  # noqa: BLE001 — one bad row must not sink the import
                failed += 1
                if len(errors) < 10:
                    errors.append(f"Row {line_no}: {exc.__class__.__name__}")

        if created or updated:
            AuditService.log_request(
                request, ActivityLog.Action.CREDENTIAL_IMPORTED,
                description=f"Imported credentials from CSV — {created} created, {updated} updated",
                resource_type="credential",
                metadata={
                    "rows": rows, "created": created, "updated": updated,
                    "skipped": skipped, "failed": failed, "source": "lastpass_csv",
                },
            )

        return Response({
            "rows": rows, "created": created, "updated": updated,
            "skipped": skipped, "failed": failed, "errors": errors,
        })


class CredentialExportThrottle(UserRateThrottle):
    rate = "10/hour"
    scope = "credential_export"


class CredentialExportView(APIView):
    """GET /api/v1/credentials/export/ — download the team vault as a CSV.

    Emits the same columns the importer reads, so an export round-trips back in.
    Owner/manager only, rate limited, and audit logged twice: once as a team
    activity and once per credential in the immutable access log, because an
    export is a bulk reveal of every password in the vault.
    """

    permission_classes = [permissions.IsAuthenticated, IsTeamMember, RolePermission]
    required_role = "manager"
    throttle_classes = [CredentialExportThrottle]

    def get(self, request):
        team = request.user.active_team
        if team is None:
            return Response({"detail": "No active team."}, status=status.HTTP_400_BAD_REQUEST)

        creds = list(
            Credential.objects.visible_to(request.user)
            .filter(team=team)
            .select_related("website")
            .order_by("website__domain", "label")
        )

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["url", "username", "password", "totp", "extra", "name", "grouping", "fav"])
        for c in creds:
            try:
                username, password, notes = c.get_username(), c.get_password(), c.get_notes()
            except Exception:
                # A row encrypted under a rotated key must not abort the export.
                username = password = ""
                notes = "Could not decrypt — vault key mismatch."
            writer.writerow([
                c.login_url,
                username,
                password,
                "",
                notes,
                c.label,
                "Website Credentials" if c.website_id else "Hosting & General",
                "0",
            ])

        CredentialAccessLog.objects.bulk_create([
            CredentialAccessLog(
                credential=c,
                user=request.user,
                action=CredentialAccessLog.Action.VIEWED,
                ip_address=_get_client_ip(request),
            )
            for c in creds
        ])
        AuditService.log_request(
            request, ActivityLog.Action.CREDENTIAL_EXPORTED,
            description=f"Exported {len(creds)} credential(s) to CSV",
            resource_type="credential",
            metadata={"count": len(creds)},
        )

        from django.http import HttpResponse

        # Excel reads a BOM-less UTF-8 CSV as ANSI; the importer strips the BOM.
        response = HttpResponse(
            "﻿" + buf.getvalue(), content_type="text/csv; charset=utf-8"
        )
        response["Content-Disposition"] = 'attachment; filename="digivault-vault-export.csv"'
        return response
