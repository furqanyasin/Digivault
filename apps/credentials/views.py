import csv
import io
import uuid
from urllib.parse import urlparse

from django.core.cache import cache
from django.utils import timezone
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q
from django.db.utils import IntegrityError
from rest_framework import generics, permissions, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from apps.audit.models import ActivityLog
from apps.audit.services import AuditService, site_meta
from apps.common.client_ip import client_ip
from apps.common.permissions import IsTeamMember, RolePermission
from apps.clients.models import Client
from apps.credentials import access
from apps.credentials.models import (
    Credential,
    CredentialAccessLog,
    CredentialAccessRequest,
    CredentialPasswordHistory,
    CredentialShare,
    FolderShare,
    SubTeamCredentialGrant,
    VaultFolder,
    normalize_totp_secret,
)
from apps.credentials.permissions import can_modify_credential
from apps.credentials.serializers import (
    AccessDecisionSerializer,
    AccessRequestSerializer,
    AccessRequestWriteSerializer,
    CredentialAccessLogSerializer,
    CredentialActivitySerializer,
    PasswordHistorySerializer,
    CredentialSerializer,
    CredentialShareSerializer,
    CredentialShareWriteSerializer,
    CredentialWriteSerializer,
    RequestableCredentialSerializer,
    RevealedCredentialSerializer,
    SubTeamCredentialGrantSerializer,
    FolderShareWriteSerializer,
    SubTeamCredentialGrantWriteSerializer,
    VaultFolderSerializer,
)
from apps.credentials.services import SHAREABLE_ROLES, CredentialService
from apps.scripts.ingest_origin import site_host


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


def _team_website_ids_for_host(team, host: str) -> list:
    """The team's websites that are the site at `host`.

    Compared through `site_host`, not `domain__iexact`: users save a domain as
    `example.com`, `https://example.com` or `https://www.example.com/`, and an
    exact match against the browser's hostname silently missed the last two —
    the extension then found no logins and refused to save new ones there.
    """
    from apps.websites.models import Website

    bare = site_host(host)
    if not bare:
        return []
    return [
        pk
        for pk, domain in Website.objects.filter(team=team).values_list("pk", "domain")
        if site_host(domain) == bare
    ]


_CLIENT_NOT_FOUND = object()


def _resolve_client(team, validated: dict):
    """The Client named by `client_id`, None for an explicit null, UNSET when
    the key is absent, or `_CLIENT_NOT_FOUND` for an id outside this team
    (answered like a missing one, so another team's ids are not confirmed)."""
    if "client_id" not in validated:
        return CredentialService.UNSET
    client_id = validated["client_id"]
    if client_id is None:
        return None
    from apps.clients.models import Client

    return Client.objects.filter(pk=client_id, team=team).first() or _CLIENT_NOT_FOUND


_FOLDER_NOT_FOUND = object()


def _resolve_folder(team, validated: dict):
    """The VaultFolder named by `folder_id`, None for an explicit null, UNSET
    when absent, or `_FOLDER_NOT_FOUND` for an id outside this team."""
    if "folder_id" not in validated:
        return CredentialService.UNSET
    folder_id = validated["folder_id"]
    if folder_id is None:
        return None
    return VaultFolder.objects.filter(pk=folder_id, team=team).first() or _FOLDER_NOT_FOUND


def _get_client_ip(request) -> str | None:
    # Resolved once, by uvicorn — see apps/common/client_ip.py for why this
    # no longer reads X-Forwarded-For itself.
    return client_ip(request)


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
            .select_related("website", "client", "folder")
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

        client = _resolve_client(team, d)
        if client is _CLIENT_NOT_FOUND:
            return Response(
                {"detail": "Client not found on this team."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        folder = _resolve_folder(team, d)
        if folder is _FOLDER_NOT_FOUND:
            return Response(
                {"detail": "Folder not found on this team."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        credential = CredentialService.create(
            team=team,
            website=website,
            folder=None if folder is CredentialService.UNSET else folder,
            client=None if client is CredentialService.UNSET else client,
            department=d.get("department"),
            totp_secret=d.get("totp", ""),
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
            .select_related("website", "client", "folder")
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

        client = _resolve_client(team, d)
        if client is _CLIENT_NOT_FOUND:
            return Response(
                {"detail": "Client not found on this team."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        folder = _resolve_folder(team, d)
        if folder is _FOLDER_NOT_FOUND:
            return Response(
                {"detail": "Folder not found on this team."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        credential = CredentialService.create(
            team=team,
            website=website,
            folder=None if folder is CredentialService.UNSET else folder,
            client=None if client is CredentialService.UNSET else client,
            department=d.get("department"),
            totp_secret=d.get("totp", ""),
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
            .select_related("website", "client", "folder")
        )

    def update(self, request, *args, **kwargs):
        credential = self.get_object()
        if not can_modify_credential(request.user, credential):
            return Response(status=status.HTTP_403_FORBIDDEN)
        serializer = CredentialWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        # Which website a credential belongs to is what puts it in the vault's
        # "Website Credentials" section rather than "Hosting & General", so
        # re-filing one means changing this. `CredentialWriteSerializer` has
        # always accepted `website_id` and this view has always thrown it away:
        # the request validated, answered 200, and nothing moved.
        #
        # `partial=True` means an absent key never reaches validated_data, so
        # the key's presence is the difference between "leave the link alone"
        # and an explicit null meaning "unlink it, send it back to Hosting".
        website = CredentialService.UNSET
        if "website_id" in d:
            website_id = d["website_id"]
            if website_id is None:
                website = None
            else:
                from apps.websites.models import Website

                website = Website.objects.filter(
                    pk=website_id, team=credential.team
                ).first()
                if website is None:
                    # Not found and not-your-team are answered identically —
                    # telling the caller which would confirm the existence of
                    # another team's website id.
                    return Response(
                        {"detail": "Website not found on this team."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

        client = _resolve_client(credential.team, d)
        if client is _CLIENT_NOT_FOUND:
            return Response(
                {"detail": "Client not found on this team."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        folder = _resolve_folder(credential.team, d)
        if folder is _FOLDER_NOT_FOUND:
            return Response(
                {"detail": "Folder not found on this team."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        updated = CredentialService.update(
            credential=credential,
            folder=folder,
            label=d.get("label"),
            credential_type=d.get("credential_type"),
            login_url=d.get("login_url"),
            username=d.get("username"),
            password=d.get("password"),
            notes=d.get("notes"),
            updated_by=request.user,
            website=website,
            client=client,
            department=d.get("department"),
            totp_secret=d.get("totp"),
        )
        changed_fields = [k for k in ("label", "credential_type", "login_url", "username", "password", "notes", "department", "totp") if d.get(k) is not None]
        if website is not CredentialService.UNSET:
            changed_fields.append("website")
        if client is not CredentialService.UNSET:
            changed_fields.append("client")
        if folder is not CredentialService.UNSET:
            changed_fields.append("folder")
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

    The dashboard reveal. Always honours `can_view_password`, so a caller whose
    only access is a no-reveal share or grant gets `password_hidden` and an
    empty string. `for_autofill` is deliberately NOT read from the request: it
    used to be, which let anyone append `?for_autofill=1` and read a password
    they were not meant to see. Autofill lives on
    ExtensionCredentialRevealView instead. Every call is audit-logged.
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

        revealed = CredentialService.reveal(
            credential=credential,
            requesting_user=request.user,
            ip_address=_get_client_ip(request),
        )
        AuditService.log_request(
            request, ActivityLog.Action.CREDENTIAL_REVEALED,
            description=f"Revealed credential '{credential.label}'",
            resource_type="credential", resource_id=credential.pk,
            metadata=site_meta(credential),
        )
        return Response(RevealedCredentialSerializer(revealed).data)


class CredentialTotpView(APIView):
    """POST /api/v1/credentials/<pk>/totp/ — the current authenticator code.

    Returns `{code, period, expires_in}`; the secret never leaves the server.
    POST rather than GET because every read is an audited access, like reveal.
    """

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def post(self, request, pk):
        try:
            credential = Credential.objects.visible_to(request.user).get(
                pk=pk, team=request.user.active_team
            )
        except Credential.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        try:
            data = CredentialService.totp_code(
                credential, request.user, ip_address=_get_client_ip(request)
            )
        except ValueError:
            return Response(
                {"detail": "This credential has no authenticator code."},
                status=status.HTTP_404_NOT_FOUND,
            )
        AuditService.log_request(
            request, ActivityLog.Action.CREDENTIAL_TOTP_READ,
            description=f"Read the authenticator code for '{credential.label}'",
            resource_type="credential", resource_id=credential.pk,
            metadata=site_meta(credential),
        )
        return Response(data)


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
        team = self.request.user.active_team
        if team is None:
            return Credential.objects.none()

        visible = Credential.objects.visible_to(self.request.user).filter(team=team)

        domain = self.request.query_params.get("domain", "").strip().lower()
        if not domain:
            # No domain → full vault (newest first), for the "All items" tab.
            return visible.order_by("-updated_at")

        bare = site_host(domain)
        # Match a website-linked credential by its website, OR any credential —
        # including standalone hosting logins — whose login_url is this host.
        #
        # The login_url test is a host comparison, not a substring one. Anchored
        # on "//host" alone, `acme.co` matched a stored `https://acme.com/...` —
        # and the extension fills whatever this returns, so a lookalike domain
        # was offered the real site's password. `icontains` only narrows the
        # rows that get parsed.
        candidates = visible.filter(
            Q(login_url__icontains=f"//{bare}") | Q(login_url__icontains=f"//www.{bare}")
        ).values_list("pk", "login_url")
        by_login_url = [pk for pk, url in candidates if site_host(url) == bare]
        by_website = Q(website_id__in=_team_website_ids_for_host(team, bare))
        return (
            visible.filter(by_website | Q(pk__in=by_login_url))
            .exclude(credential_type__in=Credential.NON_LOGIN_TYPES)
            .distinct()
        )


def is_group_admin(user, team) -> bool:
    """Whether `user` may read and change credential group access in `team`.

    The owner role, which a team can now hand to more than one person — see
    `apps.accounts.views._require_group_admin` for why the cover for an absent
    owner is a second owner rather than every manager. Expressed once so the
    copies of this role check that used to be scattered through this module
    cannot drift apart.
    """
    from apps.accounts.models import TeamMembership

    if team is None:
        return False
    return TeamMembership.objects.filter(
        user=user, team=team, role=TeamMembership.Role.OWNER
    ).exists()


def _group_admin_or_error(request, sub_team_pk):
    """Resolve a SubTeam the caller may administer.

    Returns `(group, None)` or `(None, Response)`. A group in another team is a
    404 rather than a 403: the caller has no business knowing it exists.

    Reading is gated the same as writing, because the grant list *is* the
    access-control policy.
    """
    from apps.accounts.models import SubTeam

    team = request.user.active_team
    if team is None:
        return None, Response(status=status.HTTP_404_NOT_FOUND)
    try:
        group = SubTeam.objects.filter(pk=sub_team_pk, team=team).first()
    except (DjangoValidationError, ValueError, TypeError):
        group = None
    if group is None:
        return None, Response(status=status.HTTP_404_NOT_FOUND)
    if not is_group_admin(request.user, team):
        return None, Response(
            {"detail": "Team owner required."}, status=status.HTTP_403_FORBIDDEN
        )
    return group, None


#: Alias kept so nothing importing either name breaks — the gate is the owner
#: role, which is now a set of people rather than one.
_owner_group_or_error = _group_admin_or_error


class SubTeamGrantListCreateView(APIView):
    """GET/POST /api/v1/sub-teams/<sub_team_pk>/credential-grants/ — owner only."""

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def get(self, request, sub_team_pk):
        group, err = _owner_group_or_error(request, sub_team_pk)
        if err:
            return err
        grants = group.credential_grants.select_related(
            "credential", "granted_by", "sub_team"
        )
        return Response(SubTeamCredentialGrantSerializer(grants, many=True).data)

    def post(self, request, sub_team_pk):
        group, err = _owner_group_or_error(request, sub_team_pk)
        if err:
            return err

        ser = SubTeamCredentialGrantWriteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        credential = None
        if data["scope"] == SubTeamCredentialGrant.Scope.CREDENTIAL:
            # Scoped to the group's own team, so a foreign credential is a 400
            # rather than a silent cross-tenant grant.
            credential = Credential.objects.filter(
                pk=data["credential"], team=group.team
            ).first()
            if credential is None:
                return Response(
                    {"detail": "That credential belongs to a different team."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        folder = None
        if data["scope"] == SubTeamCredentialGrant.Scope.FOLDER:
            folder = VaultFolder.objects.filter(pk=data["folder"], team=group.team).first()
            if folder is None:
                return Response(
                    {"detail": "That folder belongs to a different team."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        grant = SubTeamCredentialGrant(
            sub_team=group,
            scope=data["scope"],
            credential_type=data.get("credential_type") or "",
            credential=credential,
            folder=folder,
            can_view_password=data.get("can_view_password", False),
            granted_by=request.user,
        )
        try:
            grant.full_clean(exclude=["granted_by"])
            grant.save()
        except DjangoValidationError as exc:
            return Response(
                {"detail": "; ".join(exc.messages)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except IntegrityError:
            return Response(
                {"detail": "That group already has this grant."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        AuditService.log_request(
            request, ActivityLog.Action.CREDENTIAL_GROUP_GRANTED,
            description=(
                f"Granted group '{group.name}' access to "
                + (
                    f"folder '{grant.folder.name}'" if grant.folder_id
                    else grant.credential.label if grant.credential_id
                    else grant.get_scope_display().lower()
                )
            ),
            resource_type="sub_team_credential_grant", resource_id=grant.pk,
            metadata={
                "sub_team_id": str(group.pk),
                "scope": grant.scope,
                "credential_type": grant.credential_type,
                "credential_id": (
                    str(grant.credential_id) if grant.credential_id else None
                ),
                "can_view_password": grant.can_view_password,
            },
        )
        return Response(
            SubTeamCredentialGrantSerializer(grant).data,
            status=status.HTTP_201_CREATED,
        )


class SubTeamGrantDeleteView(APIView):
    """DELETE /api/v1/sub-teams/<sub_team_pk>/credential-grants/<pk>/ — owner only."""

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def delete(self, request, sub_team_pk, pk):
        group, err = _owner_group_or_error(request, sub_team_pk)
        if err:
            return err
        grant = group.credential_grants.filter(pk=pk).first()
        if grant is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        label = (
            grant.credential.label
            if grant.credential_id
            else grant.get_scope_display().lower()
        )
        grant.delete()
        AuditService.log_request(
            request, ActivityLog.Action.CREDENTIAL_GROUP_REVOKED,
            description=f"Revoked group '{group.name}' access to {label}",
            resource_type="sub_team_credential_grant", resource_id=pk,
            metadata={"sub_team_id": str(group.pk)},
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class CredentialGroupGrantListView(APIView):
    """GET /api/v1/credentials/<pk>/group-grants/ — owner only.

    The grants that reach one specific credential, so the share dialog can show
    group access next to user access. Read-only: grants are created through the
    sub-team collection. The shares endpoint keeps its bare-array response
    shape, because the deployed frontend depends on it.
    """

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def get(self, request, pk):
        team = request.user.active_team
        if team is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        if not is_group_admin(request.user, team):
            return Response(
                {"detail": "Team owner required."}, status=status.HTTP_403_FORBIDDEN
            )
        credential = Credential.objects.filter(pk=pk, team=team).first()
        if credential is None:
            return Response(status=status.HTTP_404_NOT_FOUND)

        grants = (
            SubTeamCredentialGrant.objects.filter(sub_team__team=team)
            .filter(
                Q(scope=SubTeamCredentialGrant.Scope.ALL)
                | Q(
                    scope=SubTeamCredentialGrant.Scope.CREDENTIAL_TYPE,
                    credential_type=credential.credential_type,
                )
                | Q(
                    scope=SubTeamCredentialGrant.Scope.CREDENTIAL,
                    credential=credential,
                )
            )
            .select_related("sub_team", "credential", "granted_by")
        )
        return Response(SubTeamCredentialGrantSerializer(grants, many=True).data)


class ExtensionCredentialRevealView(APIView):
    """POST /api/extension/credentials/<pk>/reveal/

    The autofill path. Returns plaintext even when the caller's only access is
    a no-reveal share or grant, because the extension has to put the password
    into the login form.

    This is not a security boundary and must not be described as one: the
    extension carries the same JWT as the dashboard, so a determined user can
    call this route themselves. What it buys is that the password is never
    rendered in the dashboard, there is no one-parameter toggle on the
    dashboard endpoint, and every autofill pull is logged as AUTOFILL against a
    named user. Control by accountability.
    """

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def post(self, request, pk):
        team = request.user.active_team
        try:
            credential = (
                Credential.objects.visible_to(request.user).get(pk=pk, team=team)
            )
        except Credential.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        revealed = CredentialService.reveal(
            credential=credential,
            requesting_user=request.user,
            ip_address=_get_client_ip(request),
            for_autofill=True,
        )
        AuditService.log_request(
            request, ActivityLog.Action.CREDENTIAL_REVEALED,
            description=f"Autofilled credential '{credential.label}'",
            resource_type="credential", resource_id=credential.pk,
            metadata={**site_meta(credential), "autofill": True},
        )
        return Response(RevealedCredentialSerializer(revealed).data)


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

        website_ids = _team_website_ids_for_host(team, domain)
        website = Website.objects.filter(pk__in=website_ids).order_by("created_at").first()

        # Look up existing credential by username hash — no decryption loop.
        # Updating one is an edit, so it answers to the same rule as the
        # dashboard (`can_modify_credential`). This used to overwrite whatever
        # matched, so a viewer could replace a password they could not even see.
        #
        # Any site, not just a client's: Semrush, Ahrefs, Canva and registrar
        # logins have no Website row, and are matched among standalone
        # credentials by their login host (see `_saved_login`).
        existing = _saved_login(team, domain, username)

        if existing:
            if not can_modify_credential(request.user, existing):
                return Response(
                    {
                        "error": "not_allowed",
                        "detail": "This login is already in Stacks Monitor and only its "
                        "creator or a manager can change it.",
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )
            CredentialService.update(
                credential=existing,
                password=password,
                login_url=login_url or None,
                updated_by=request.user,
            )
            AuditService.log_request(
                request, ActivityLog.Action.CREDENTIAL_UPDATED,
                description=f"Updated credential '{existing.label}' from the extension",
                resource_type="credential", resource_id=existing.pk,
                metadata={**site_meta(existing), "source": "extension"},
            )
            return Response({"action": "updated", "credential_id": str(existing.id)})

        created = CredentialService.create(
            team=team,
            website=website,
            label=f"{domain.removeprefix('www.')} login",
            credential_type=Credential.CredentialType.CUSTOM,
            login_url=login_url,
            username=username,
            password=password,
            notes="",
            created_by=request.user,
        )
        AuditService.log_request(
            request, ActivityLog.Action.CREDENTIAL_CREATED,
            description=f"Created credential '{created.label}' from the extension",
            resource_type="credential", resource_id=created.pk,
            metadata={**site_meta(created), "source": "extension"},
        )
        return Response(
            {"action": "created", "credential_id": str(created.id)},
            status=status.HTTP_201_CREATED,
        )


class ExtensionCredentialCheckView(APIView):
    """POST /api/extension/credentials/check/ {domain, username, password}

    Whether the save prompt is worth showing: "new" (not in the vault),
    "changed" (saved with a different password — offer an update), "same"
    (already saved as typed — stay quiet), or "readonly" (saved, but the
    caller cannot change it — nothing to offer). The prompt used to appear on
    every sign-in to a site whose login was already in the vault.

    Compared on the server, so the extension never has to reveal a stored
    password to find out, and nothing here writes an access-log row.
    """

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]
    throttle_classes = [CredentialSaveThrottle]

    def post(self, request):
        domain = (request.data.get("domain") or "").strip().lower()
        username = (request.data.get("username") or "").strip()
        password = request.data.get("password") or ""
        team = request.user.active_team
        if not domain or not username or not password or team is None:
            return Response({"status": "new"})
        existing = _saved_login(team, domain, username)
        if existing is None:
            return Response({"status": "new"})
        if not can_modify_credential(request.user, existing):
            return Response({"status": "readonly"})
        try:
            same = existing.get_password() == password
        except Exception:  # noqa: BLE001 — undecryptable: treat as changed
            same = False
        return Response({"status": "same" if same else "changed", "credential_id": str(existing.pk)})


def _saved_login(team, domain: str, username: str):
    """The credential the save prompt for (`domain`, `username`) refers to."""
    from apps.websites.models import Website

    website_ids = _team_website_ids_for_host(team, domain)
    website = Website.objects.filter(pk__in=website_ids).order_by("created_at").first()
    same_user = Credential.objects.filter(
        team=team, username_hash=Credential.hash_username(username)
    )
    if website:
        return same_user.filter(website=website).first()
    bare = site_host(domain)
    return next(
        (
            c for c in same_user.filter(website=None).exclude(login_url="")
            if site_host(c.login_url) == bare
        ),
        None,
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
        # `delete` reports whether it removed the key, which makes it the
        # one-time claim: of two requests racing on one code, only the one
        # whose delete succeeds gets the tokens.
        if tokens is None or not cache.delete(key):
            return Response(
                {"detail": "Invalid or expired code"},
                status=status.HTTP_404_NOT_FOUND,
            )
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
        shares = CredentialShare.objects.active().filter(credential=cred).select_related(
            "user", "shared_by"
        )
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

        # Only member-level roles need shares; owners/managers already have
        # access. See SHAREABLE_ROLES.
        target_members = [m for m in memberships if m.role in SHAREABLE_ROLES]
        can_view = ser.validated_data["can_view_password"]
        # Sharing sets the expiry outright — a permanent share given to someone
        # holding a temporary one from an access request must not keep its end
        # date, which update_or_create would otherwise leave in place.
        hours = ser.validated_data.get("expires_in_hours")
        expires_at = timezone.now() + timezone.timedelta(hours=hours) if hours else None
        affected_ids = []
        for m in target_members:
            CredentialShare.objects.update_or_create(
                credential=cred, user_id=m.user_id,
                defaults={
                    "shared_by": request.user, "can_view_password": can_view,
                    "expires_at": expires_at,
                },
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

        shares = CredentialShare.objects.active().filter(credential=cred).select_related(
            "user", "shared_by"
        )
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
            m.user_id for m in memberships if m.role in SHAREABLE_ROLES
        ]

        creds = Credential.objects.filter(team=team, website_id=website_pk)
        shared_cred_count = 0
        for cred in creds:
            if not can_modify_credential(request.user, cred):
                continue
            for uid in target_user_ids:
                CredentialShare.objects.update_or_create(
                    credential=cred, user_id=uid,
                    defaults={
                        "shared_by": request.user, "can_view_password": can_view,
                        "expires_at": None,
                    },
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


# The vault CSV — one header shared by the sample template, the export and the
# native import path. It is every writable field on a Credential (the
# `CredentialWriteSerializer` set) plus `teams`, so an export round-trips back in
# without the importer having to re-guess anything.
#
# LastPass's own columns (url/username/password/totp/extra/name/grouping/fav)
# remain readable, resolved per column below rather than by a mode switch, so an
# untouched LastPass export still imports.
_VAULT_CSV_HEADER = [
    "name", "credential_type", "website", "url", "username", "password",
    "notes", "teams", "department", "totp", "folder",
]

#: LastPass `grouping` values that are not real folders.
_NOT_FOLDERS = {"(none)", "website credentials", "hosting & general", "hosting and general"}

# Groups within one cell. Comma is the CSV delimiter and cannot be used.
_TEAM_SEPARATOR = ";"
# Suffix on a group name meaning the group may reveal the password. Absent
# means it may not — matching SubTeamCredentialGrant.can_view_password's
# deliberate default of False.
_TEAM_VIEW_SUFFIX = "view"


def _format_team_grant(name: str, can_view_password: bool) -> str:
    return f"{name}:{_TEAM_VIEW_SUFFIX}" if can_view_password else name


def _parse_teams_cell(raw: str) -> list[tuple[str, bool]]:
    """`"Web Team:view; SEO Team"` → `[("Web Team", True), ("SEO Team", False)]`.

    Split from the right so a group whose own name contains a colon survives;
    only a trailing `:view` is read as the flag.
    """
    out: list[tuple[str, bool]] = []
    for chunk in (raw or "").split(_TEAM_SEPARATOR):
        entry = chunk.strip()
        if not entry:
            continue
        name, sep, suffix = entry.rpartition(":")
        if sep and suffix.strip().lower() == _TEAM_VIEW_SUFFIX:
            out.append((name.strip(), True))
        else:
            out.append((entry, False))
    return out


# Credential types by both stored value and human label, so a spreadsheet edited
# in Excel — where the label is what a person sees in the app — still imports.
_CREDENTIAL_TYPES_BY_VALUE = {v.lower(): v for v in Credential.CredentialType.values}
_CREDENTIAL_TYPES_BY_LABEL = {
    str(label).lower(): value for value, label in Credential.CredentialType.choices
}


def _resolve_credential_type(raw: str, url: str, grouping: str) -> str:
    """The declared type when it is one we know, else the URL guesser.

    A typo in a hand-edited sheet must not lose the row — the guesser is what
    every LastPass import has always relied on, so falling back to it costs the
    row nothing it would otherwise have had.
    """
    key = (raw or "").strip().lower()
    if key in _CREDENTIAL_TYPES_BY_VALUE:
        return _CREDENTIAL_TYPES_BY_VALUE[key]
    if key in _CREDENTIAL_TYPES_BY_LABEL:
        return _CREDENTIAL_TYPES_BY_LABEL[key]
    return _guess_credential_type(url, grouping)


def _website_lookup_key(value: str) -> str:
    """A `website` cell reduced to a bare host — `https://www.acme.io/` → `acme.io`."""
    host = (value or "").strip().lower()
    host = host.removeprefix("https://").removeprefix("http://")
    host = host.split("/", 1)[0].split("?", 1)[0]
    return host.removeprefix("www.")


def _is_team_owner(user, team) -> bool:
    """Alias, so the CSV paths below read the same rule as every other caller
    rather than keeping their own copy of it."""
    return is_group_admin(user, team)


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


def _url_host(url_key: str) -> str:
    """Host (with port) of a normalized login URL — `acme.io:2083/x` → `acme.io:2083`."""
    return url_key.split("/", 1)[0].split("?", 1)[0]


def _match_keys(
    website_id, username_hash: str, login_url: str, label: str, credential_type: str
) -> list[tuple]:
    """Identity keys for an imported login, most specific first.

    A credential is "the same login" only when it is the same account (username)
    at the same *service*. Keying on username alone collapses every hosting panel
    an agency signs into with one shared email down to a single row, so every key
    below carries the service as well:

    1. ``url``   — the same account at the exact same login URL.
    2. ``host``  — the same account and the same type on one linked website's
                   host. Catches ``/wp-admin`` against ``/wp-login.php``. Limited
                   to rows that resolved to a website, so the agency-wide panel
                   logins (which are standalone) can never collapse together.
    3. ``label`` — the same account under the same name. Catches a login whose
                   URL changed, and is the only key a row without a URL has.

    A stored credential registers all of its keys; an incoming row matches on the
    first one that hits.
    """
    url_key = _normalize_login_url(login_url)
    host = _url_host(url_key)
    keys: list[tuple] = []
    if url_key:
        keys.append(("url", website_id, username_hash, url_key))
    if host and website_id is not None:
        keys.append(("host", website_id, username_hash, host, credential_type))
    keys.append(("label", website_id, username_hash, label.strip().lower()))
    return keys


def _mask_username(username: str) -> str:
    """Enough of a username to recognise a row by, without echoing it in full."""
    if not username:
        return ""
    local, sep, domain = username.partition("@")
    return f"{local[:2]}{'*' * max(len(local) - 2, 1)}{sep}{domain}"


# preview writes nothing and reports what a commit would do; the other three are
# the answers to "this login already exists" — refresh it, leave it alone, or
# keep both copies.
_IMPORT_MODES = ("preview", "update", "skip", "duplicate")


class CredentialImportView(APIView):
    """POST /api/v1/credentials/import/ — import a vault CSV.

    Reads the native header (`_VAULT_CSV_HEADER`: name, credential_type,
    website, url, username, password, notes, teams, department, totp), which is
    what the export and the sample template emit, so an export round-trips back
    in unchanged. `totp` is LastPass's column name too, so its authenticator
    secrets now arrive as real secrets rather than as a line in the notes.

    LastPass's own columns (url, username, password, totp, extra, name,
    grouping, fav) are still read, resolved per column rather than by a mode
    switch: `notes` falls back to `extra`, `credential_type` to the URL guesser,
    and `website` to the login URL's host. An untouched LastPass export imports
    exactly as it always did.

    Each row becomes an encrypted Credential. The `teams` column grants named
    groups access to the row and is owner-only — a manager's values are counted
    into `grants_ignored` rather than dropped in silence. It never revokes:
    an empty cell leaves existing grants alone.

    Rows that match a login already in the vault are handled by ``mode``:

    - ``preview`` — write nothing, return the matches so the UI can ask.
    - ``update``  — refresh the existing entry (the default, and what a repeat
                    import of the same export should do).
    - ``skip``    — import only the rows that are genuinely new.
    - ``duplicate`` — store the row as a second entry anyway.

    ``preview`` runs the identical matching pass as the commit that follows it,
    so the counts it reports are the counts the user gets. The file is uploaded
    again for the commit rather than parked server-side — a CSV of plaintext
    passwords should not sit in a cache between two requests.

    Owner/manager only: an import writes to the whole team's vault.
    """

    permission_classes = [permissions.IsAuthenticated, IsTeamMember, RolePermission]
    required_role = "manager"
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request):
        team = request.user.active_team
        if team is None:
            return Response({"detail": "No active team."}, status=status.HTTP_400_BAD_REQUEST)

        mode = str(request.data.get("mode") or "update").strip().lower()
        if mode not in _IMPORT_MODES:
            return Response(
                {"detail": f"Unknown import mode '{mode}'."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        preview = mode == "preview"

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
            for key in _match_keys(
                cred.website_id, cred.username_hash, cred.login_url,
                cred.label, cred.credential_type,
            ):
                index.setdefault(key, cred)

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

        folders_by_name = {
            fo.name.lower(): fo for fo in VaultFolder.objects.filter(team=team)
        }

        def _import_folder(raw: str):
            """The folder named in a row, created on first sight. Not in a
            preview, which writes nothing. The vault's own section names (an
            old export put them in `grouping`) are not folders."""
            name = (raw or "").strip().replace("\\", " / ")[:80]
            if not name or name.lower() in _NOT_FOLDERS:
                return None
            folder = folders_by_name.get(name.lower())
            if folder is None and not preview:
                folder = VaultFolder.objects.create(team=team, name=name, created_by=request.user)
                folders_by_name[name.lower()] = folder
            return folder

        # Writing grants is owner-only for the same reason reading them is. A
        # manager's `teams` values are counted and reported rather than dropped
        # in silence.
        is_owner = _is_team_owner(request.user, team)
        groups_by_name: dict[str, object] = {}
        if is_owner:
            from apps.accounts.models import SubTeam

            groups_by_name = {
                g.name.strip().lower(): g for g in SubTeam.objects.filter(team=team)
            }

        def _apply_team_grants(credential, cell: str, line_no: int):
            """Grant each named group access to `credential`.

            Additive only: an omitted or empty cell leaves existing grants
            alone, because revoking is a deliberate act in the share dialog and
            must not be something a spreadsheet does by saying nothing.

            Returns `(created, ignored, messages)`.
            """
            entries = _parse_teams_cell(cell)
            if not entries:
                return 0, 0, []
            if not is_owner:
                return 0, len(entries), []

            made = 0
            messages: list[str] = []
            for group_name, can_view in entries:
                group = groups_by_name.get(group_name.strip().lower())
                if group is None:
                    messages.append(f"Row {line_no}: unknown group '{group_name}'.")
                    continue
                _, was_created = SubTeamCredentialGrant.objects.get_or_create(
                    sub_team=group,
                    scope=SubTeamCredentialGrant.Scope.CREDENTIAL,
                    credential=credential,
                    defaults={
                        "can_view_password": can_view,
                        "granted_by": request.user,
                    },
                )
                if was_created:
                    made += 1
            return made, 0, messages

        rows = created = updated = skipped = failed = 0
        duplicates = repeats_in_file = skipped_duplicates = 0
        grants_created = grants_ignored = 0
        errors: list[str] = []
        # What a preview reports back. Capped so a 5 MB re-import of an entire
        # vault can't answer with a response the dialog has to render in full.
        conflicts: list[dict] = []
        _CONFLICT_SAMPLE = 200
        # Rows this preview has already counted as new — a second copy inside the
        # same file is a repeat of *that*, not of anything in the vault.
        pending: dict[tuple, int] = {}

        for line_no, row in enumerate(reader, start=2):  # line 1 is the header
            rows += 1
            try:
                name = (row.get("name") or "").strip()
                url = (row.get("url") or "").strip()
                username = (row.get("username") or "").strip()
                password = row.get("password") or ""
                totp = (row.get("totp") or "").strip()
                grouping = (row.get("grouping") or "").strip()
                # Native column first, LastPass's `extra` as the fallback.
                notes = (row.get("notes") or row.get("extra") or "").strip()
                teams_cell = (row.get("teams") or row.get("groups") or "").strip()

                # Skip secure notes / rows with no usable login.
                if not username and not password:
                    skipped += 1
                    continue

                # A valid secret becomes the credential's authenticator; one we
                # cannot read (a Steam or HOTP export) is kept in the notes
                # rather than dropped, so nothing in the file is lost.
                totp_secret = ""
                if totp:
                    try:
                        totp_secret = normalize_totp_secret(totp)
                    except ValueError:
                        notes = (notes + "\n" if notes else "") + f"TOTP secret: {totp}"
                department = (row.get("department") or "").strip().lower()
                if department and department not in Client.DEPARTMENTS:
                    department = ""
                # The native `folder` column, else LastPass's `grouping` —
                # its folder path ("SEO\\Tools"), kept whole as one name.
                folder = _import_folder(row.get("folder") or grouping)

                # Link to a team website when the host matches; else standalone.
                host = ""
                try:
                    parsed = urlparse(url if "://" in url else f"https://{url}")
                    host = (parsed.hostname or "").lower()
                except ValueError:
                    host = ""
                # The explicit column wins: a hosting panel login for acme.io
                # lives on my.siteground.com, and host matching can never
                # recover that link. Fall back to the host when it is absent or
                # names no site we know.
                declared_site = _website_lookup_key(row.get("website") or "")
                website = _website_for(declared_site) if declared_site else None
                if website is None and host:
                    website = _website_for(host)

                label = (name or host or "Imported login")[:_LABEL_MAX]
                cred_type = _resolve_credential_type(
                    row.get("credential_type") or "", url, grouping
                )

                # A URL past the column width would blow up the insert. Keep the
                # full value in the notes rather than storing a truncated link.
                stored_url = url
                if len(stored_url) > _URL_MAX:
                    notes = (notes + "\n" if notes else "") + f"Full login URL: {url}"
                    stored_url = ""

                keys = _match_keys(
                    website.id if website else None,
                    Credential.hash_username(username),
                    stored_url,
                    label,
                    cred_type,
                )
                existing = next((index[k] for k in keys if k in index), None)

                if existing is not None:
                    duplicates += 1
                    if preview:
                        if len(conflicts) < _CONFLICT_SAMPLE:
                            conflicts.append({
                                "row": line_no,
                                "label": label,
                                "username": _mask_username(username),
                                "credential_type": cred_type,
                                "login_url": stored_url,
                                "website_name": (
                                    (website.name or website.domain) if website else None
                                ),
                                "existing_id": str(existing.id),
                                "existing_label": existing.label,
                                "existing_updated_at": existing.updated_at.isoformat(),
                            })
                        continue
                    if mode == "skip":
                        skipped_duplicates += 1
                        continue
                    if mode == "update":
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
                            department=department or None,
                            totp_secret=totp_secret or None,
                            notify_users=False,
                            **({"folder": folder} if folder else {}),
                        )
                        made, ignored, notes_out = _apply_team_grants(
                            existing, teams_cell, line_no
                        )
                        grants_created += made
                        grants_ignored += ignored
                        for msg in notes_out:
                            if len(errors) < 10:
                                errors.append(msg)
                        updated += 1
                        continue
                    # mode == "duplicate": store the row as its own entry anyway.

                elif preview and any(k in pending for k in keys):
                    repeats_in_file += 1
                    continue

                if preview:
                    created += 1
                    for k in keys:
                        pending.setdefault(k, line_no)
                    continue

                cred = CredentialService.create(
                    label=label, credential_type=cred_type, login_url=stored_url,
                    username=username, password=password, notes=notes,
                    created_by=request.user, team=team, website=website,
                    department=department or None, totp_secret=totp_secret,
                    folder=folder,
                )
                for k in keys:
                    index.setdefault(k, cred)
                made, ignored, notes_out = _apply_team_grants(cred, teams_cell, line_no)
                grants_created += made
                grants_ignored += ignored
                for msg in notes_out:
                    if len(errors) < 10:
                        errors.append(msg)
                created += 1
            except Exception as exc:  # noqa: BLE001 — one bad row must not sink the import
                failed += 1
                if len(errors) < 10:
                    errors.append(f"Row {line_no}: {exc.__class__.__name__}")

        if not preview and (created or updated):
            AuditService.log_request(
                request, ActivityLog.Action.CREDENTIAL_IMPORTED,
                description=f"Imported credentials from CSV — {created} created, {updated} updated",
                resource_type="credential",
                metadata={
                    "rows": rows, "created": created, "updated": updated,
                    "skipped": skipped + skipped_duplicates, "failed": failed,
                    "mode": mode, "source": "lastpass_csv",
                },
            )

        return Response({
            "mode": mode,
            "rows": rows,
            "created": created,
            "updated": updated,
            "skipped": skipped + skipped_duplicates,
            "failed": failed,
            "errors": errors,
            # Preview-only: `created` above is the count of genuinely new rows.
            "duplicates": duplicates,
            "repeats_in_file": repeats_in_file,
            "conflicts": conflicts,
            # Group access from the `teams` column. `grants_ignored` is non-zero
            # only for a manager, for whom writing grants is out of bounds.
            "grants_created": grants_created,
            "grants_ignored": grants_ignored,
        })


class CredentialExportThrottle(UserRateThrottle):
    rate = "10/hour"
    scope = "credential_export"


class CredentialExportView(APIView):
    """GET /api/v1/credentials/export/ — download the team vault as a CSV.

    Emits every writable credential field (`_VAULT_CSV_HEADER`), so an export
    round-trips back in without the importer re-guessing the type or the website
    link. Owner/manager only, rate limited, and audit logged twice: once as a
    team activity and once per credential in the immutable access log, because
    an export is a bulk reveal of every password in the vault.

    The `teams` column is populated only for a team owner. Only single-credential
    grants appear in it: a blanket or type-scoped grant is team-wide policy, and
    writing it into every row would re-import as one per-credential grant per
    row, freezing a live policy into a snapshot of itself.
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
            .select_related("website", "client", "folder")
            .order_by("website__domain", "label")
        )

        # The grant list *is* the access-control policy, and reading it is
        # owner-only everywhere else (see `_group_admin_or_error`). Export is
        # manager-gated, so a manager gets the column present but empty rather
        # than the policy handed to them in a spreadsheet.
        grants_by_credential: dict[object, list[str]] = {}
        if _is_team_owner(request.user, team):
            for grant in (
                SubTeamCredentialGrant.objects.filter(
                    sub_team__team=team,
                    scope=SubTeamCredentialGrant.Scope.CREDENTIAL,
                )
                .select_related("sub_team")
            ):
                grants_by_credential.setdefault(grant.credential_id, []).append(
                    _format_team_grant(grant.sub_team.name, grant.can_view_password)
                )

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(_VAULT_CSV_HEADER)
        for c in creds:
            try:
                username, password, notes = c.get_username(), c.get_password(), c.get_notes()
                totp = c.get_totp_secret()
            except Exception:
                # A row encrypted under a rotated key must not abort the export.
                username = password = totp = ""
                notes = "Could not decrypt — vault key mismatch."
            writer.writerow([
                c.label,
                c.credential_type,
                c.website.domain if c.website_id else "",
                c.login_url,
                username,
                password,
                notes,
                _TEAM_SEPARATOR.join(sorted(grants_by_credential.get(c.id, []))),
                c.department,
                totp,
                c.folder.name if c.folder_id else "",
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
        response["Content-Disposition"] = 'attachment; filename="stacksmonitor-vault-export.csv"'
        return response


# ── Access requests ──────────────────────────────────────────────────────────


class RequestableCredentialListView(generics.ListAPIView):
    """GET /api/v1/credentials/requestable/?q= — team credentials you cannot see.

    Metadata only, for the "Request access" picker.
    """

    serializer_class = RequestableCredentialSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def get_queryset(self):
        team = self.request.user.active_team
        if team is None:
            return Credential.objects.none()
        qs = access.requestable_for(self.request.user, team)
        q = (self.request.query_params.get("q") or "").strip()
        if q:
            qs = qs.filter(
                Q(label__icontains=q)
                | Q(website__name__icontains=q)
                | Q(website__domain__icontains=q)
                | Q(client__name__icontains=q)
            )
        return qs.order_by("label")


class CredentialAccessRequestCreateView(APIView):
    """POST /api/v1/credentials/<pk>/access-requests/ {reason, hours}"""

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def post(self, request, pk):
        credential = Credential.objects.filter(pk=pk, team=request.user.active_team).first()
        if credential is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        ser = AccessRequestWriteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            req, created = access.create_request(
                request.user, credential, ser.validated_data["reason"], ser.validated_data["hours"]
            )
        except access.AccessRequestError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        if created:
            AuditService.log_request(
                request, ActivityLog.Action.CREDENTIAL_ACCESS_REQUESTED,
                description=f"Requested access to credential '{credential.label}'",
                resource_type="credential", resource_id=credential.pk,
                metadata={"request_id": str(req.pk), "hours": req.requested_hours},
            )
        return Response(
            AccessRequestSerializer(req).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class AccessRequestListView(APIView):
    """GET /api/v1/credentials/access-requests/?scope=to_me|mine

    `to_me` (default): pending requests on credentials you may share.
    `mine`: your own requests, newest first, last 50.
    """

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def get(self, request):
        team = request.user.active_team
        if request.query_params.get("scope") == "mine":
            rows = (
                CredentialAccessRequest.objects.filter(team=team, requester=request.user)
                .select_related("credential", "requester", "decided_by")[:50]
            )
        else:
            rows = access.requests_for_approver(request.user, team)
        return Response(AccessRequestSerializer(rows, many=True).data)


class AccessRequestDecideView(APIView):
    """POST /api/v1/credentials/access-requests/<pk>/decide/
    {approve, hours, can_view_password, note}"""

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def post(self, request, pk):
        req = (
            CredentialAccessRequest.objects.filter(pk=pk, team=request.user.active_team)
            .select_related("credential", "credential__team", "requester")
            .first()
        )
        if req is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        ser = AccessDecisionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        try:
            req = access.decide_request(
                request.user, req, d["approve"], hours=d["hours"],
                can_view_password=d["can_view_password"], note=d["note"],
            )
        except access.AccessRequestError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        AuditService.log_request(
            request,
            ActivityLog.Action.CREDENTIAL_ACCESS_APPROVED if d["approve"]
            else ActivityLog.Action.CREDENTIAL_ACCESS_DENIED,
            description=(
                f"{'Approved' if d['approve'] else 'Denied'} {_display_name(req.requester)}'s "
                f"access to credential '{req.credential.label}'"
            ),
            resource_type="credential", resource_id=req.credential.pk,
            metadata={
                "request_id": str(req.pk), "requester_id": str(req.requester_id),
                "granted_until": req.granted_until.isoformat() if req.granted_until else None,
                "can_view_password": req.can_view_password,
            },
        )
        return Response(AccessRequestSerializer(req).data)


class AccessRequestCancelView(APIView):
    """POST /api/v1/credentials/access-requests/<pk>/cancel/ — by the requester."""

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def post(self, request, pk):
        req = CredentialAccessRequest.objects.filter(
            pk=pk, team=request.user.active_team
        ).first()
        if req is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        try:
            req = access.cancel_request(request.user, req)
        except access.AccessRequestError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(AccessRequestSerializer(req).data)


# ── Handover ─────────────────────────────────────────────────────────────────


def _team_member(team, user_id):
    from apps.accounts.models import TeamMembership

    m = TeamMembership.objects.filter(team=team, user_id=user_id).select_related("user").first()
    return m.user if m else None


class MemberCredentialSummaryView(APIView):
    """GET /api/v1/credentials/members/<user_id>/summary/ — manager+.

    What a member holds (credentials they own, active shares) and every
    credential whose secret they have revealed, copied or autofilled — the
    rotation list for when they leave.
    """

    permission_classes = [permissions.IsAuthenticated, IsTeamMember, RolePermission]
    required_role = "manager"

    def get(self, request, user_id):
        team = request.user.active_team
        member = _team_member(team, user_id)
        if member is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(access.member_summary(team, member))


class MemberCredentialHandoverView(APIView):
    """POST /api/v1/credentials/members/<user_id>/handover/ — manager+.

    {to_user_id, revoke_shares} — moves the member's credentials to a colleague
    and, by default, removes every share they hold.
    """

    permission_classes = [permissions.IsAuthenticated, IsTeamMember, RolePermission]
    required_role = "manager"

    def post(self, request, user_id):
        team = request.user.active_team
        member = _team_member(team, user_id)
        recipient = _team_member(team, request.data.get("to_user_id"))
        if member is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        if recipient is None:
            return Response(
                {"detail": "Pick a team member to hand the credentials to."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        revoke = bool(request.data.get("revoke_shares", True))
        try:
            result = access.handover(team, member, recipient, revoke_shares=revoke)
        except access.AccessRequestError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        AuditService.log_request(
            request, ActivityLog.Action.CREDENTIAL_HANDOVER,
            description=(
                f"Handed {result['moved']} credential(s) from {_display_name(member)} to "
                f"{_display_name(recipient)}"
                + (f" and revoked {result['shares_revoked']} share(s)" if revoke else "")
            ),
            resource_type="user", resource_id=member.pk,
            metadata={**result, "to_user_id": str(recipient.pk)},
        )
        return Response(result)


# ── Password history ─────────────────────────────────────────────────────────


def _visible_credential(request, pk):
    return (
        Credential.objects.visible_to(request.user)
        .filter(pk=pk, team=request.user.active_team)
        .first()
    )


class PasswordHistoryListView(APIView):
    """GET /api/v1/credentials/<pk>/password-history/ — retired passwords, newest first.

    Metadata only, to anyone who can see the credential.
    """

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def get(self, request, pk):
        credential = _visible_credential(request, pk)
        if credential is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        rows = credential.password_history.select_related("changed_by")
        return Response(PasswordHistorySerializer(rows, many=True).data)


class PasswordHistoryRevealView(APIView):
    """POST /api/v1/credentials/<pk>/password-history/<entry_pk>/reveal/"""

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def post(self, request, pk, entry_pk):
        credential = _visible_credential(request, pk)
        entry = (
            CredentialPasswordHistory.objects.filter(pk=entry_pk, credential=credential).first()
            if credential else None
        )
        if entry is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        password = CredentialService.reveal_history(
            entry, request.user, ip_address=_get_client_ip(request)
        )
        AuditService.log_request(
            request, ActivityLog.Action.CREDENTIAL_REVEALED,
            description=f"Revealed an old password of credential '{credential.label}'",
            resource_type="credential", resource_id=credential.pk,
            metadata={**site_meta(credential), "history_entry": str(entry.pk)},
        )
        return Response({"password": password})


class PasswordHistoryRestoreView(APIView):
    """POST /api/v1/credentials/<pk>/password-history/<entry_pk>/restore/

    Puts an old password back. The current one goes into the history in the
    same step, so a restore is itself undoable.
    """

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def post(self, request, pk, entry_pk):
        credential = _visible_credential(request, pk)
        entry = (
            CredentialPasswordHistory.objects.filter(pk=entry_pk, credential=credential).first()
            if credential else None
        )
        if entry is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        if not can_modify_credential(request.user, credential):
            return Response(status=status.HTTP_403_FORBIDDEN)
        CredentialService.update(
            credential=credential, password=entry.get_password(), updated_by=request.user
        )
        AuditService.log_request(
            request, ActivityLog.Action.CREDENTIAL_UPDATED,
            description=f"Restored an old password of credential '{credential.label}'",
            resource_type="credential", resource_id=credential.pk,
            metadata=site_meta(credential, fields_changed=["password"]),
        )
        return Response(CredentialSerializer(credential).data)


# ── Who has access / activity / broken ───────────────────────────────────────


def _can_audit(user, credential) -> bool:
    """Managers and owners, or whoever may change the credential."""
    from apps.accounts.models import TeamMembership

    if can_modify_credential(user, credential):
        return True
    return TeamMembership.objects.filter(
        user=user, team=credential.team,
        role__in=[TeamMembership.Role.OWNER, TeamMembership.Role.MANAGER],
    ).exists()


class CredentialWhoHasAccessView(APIView):
    """GET /api/v1/credentials/<pk>/access/ — everyone who can see it, and why."""

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def get(self, request, pk):
        credential = _visible_credential(request, pk)
        if credential is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        if not _can_audit(request.user, credential):
            return Response(status=status.HTTP_403_FORBIDDEN)
        return Response(access.who_has_access(credential))


class CredentialActivityView(APIView):
    """GET /api/v1/credentials/<pk>/activity/ — this credential's access log,
    newest first (last 100): reveals, copies, autofills, code reads, edits."""

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def get(self, request, pk):
        credential = _visible_credential(request, pk)
        if credential is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        if not _can_audit(request.user, credential):
            return Response(status=status.HTTP_403_FORBIDDEN)
        rows = credential.access_logs.select_related("user")[:100]
        return Response(CredentialActivitySerializer(rows, many=True).data)


class CredentialReportBrokenView(APIView):
    """POST /api/v1/credentials/<pk>/report-broken/ {note} — anyone who can see it.

    Also on the extension's routes, since the browser is where a dead password
    is discovered.
    """

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def post(self, request, pk):
        from apps.credentials import notify

        credential = _visible_credential(request, pk)
        if credential is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        note = str(request.data.get("note") or "").strip()[:300]
        already = credential.reported_broken_at is not None
        credential.reported_broken_at = timezone.now()
        credential.reported_broken_by = request.user
        credential.reported_broken_note = note
        credential.save(update_fields=[
            "reported_broken_at", "reported_broken_by", "reported_broken_note", "updated_at",
        ])
        AuditService.log_request(
            request, ActivityLog.Action.CREDENTIAL_REPORTED_BROKEN,
            description=f"Reported credential '{credential.label}' as not working",
            resource_type="credential", resource_id=credential.pk,
            metadata=site_meta(credential, note=note),
        )
        if not already:
            # One email per breakage, not one per teammate who confirms it.
            notify.reported_broken(credential, request.user, note)
        return Response(CredentialSerializer(credential).data)


class CredentialMarkFixedView(APIView):
    """POST /api/v1/credentials/<pk>/mark-fixed/ — clears the report without a
    password change (the site was down, the account was unlocked)."""

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def post(self, request, pk):
        credential = _visible_credential(request, pk)
        if credential is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        if not can_modify_credential(request.user, credential):
            return Response(status=status.HTTP_403_FORBIDDEN)
        credential.reported_broken_at = None
        credential.reported_broken_by = None
        credential.reported_broken_note = ""
        credential.save(update_fields=[
            "reported_broken_at", "reported_broken_by", "reported_broken_note", "updated_at",
        ])
        AuditService.log_request(
            request, ActivityLog.Action.CREDENTIAL_MARKED_FIXED,
            description=f"Marked credential '{credential.label}' as working again",
            resource_type="credential", resource_id=credential.pk,
            metadata=site_meta(credential),
        )
        return Response(CredentialSerializer(credential).data)


# ── Folders ──────────────────────────────────────────────────────────────────


def _is_manager(user, team) -> bool:
    from apps.accounts.models import TeamMembership

    return TeamMembership.objects.filter(
        user=user, team=team,
        role__in=[TeamMembership.Role.OWNER, TeamMembership.Role.MANAGER],
    ).exists()


class VaultFolderListCreateView(APIView):
    """GET/POST /api/v1/credentials/folders/

    Everyone sees the team's folder names (to file and filter by) with a count
    of the credentials *they* can see in each; owners also get each folder's
    group access. Creating is for managers and owners — folders are how the
    team arranges the vault, not something each member reshapes.
    """

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def get(self, request):
        from django.db.models import Count

        team = request.user.active_team
        visible = Credential.objects.visible_to(request.user).filter(team=team)
        counts = dict(
            visible.exclude(folder=None).values("folder_id").annotate(n=Count("id"))
            .values_list("folder_id", "n")
        )
        folders = list(
            VaultFolder.objects.filter(team=team).prefetch_related("grants__sub_team", "shares__user")
        )
        for fo in folders:
            fo.credential_count = counts.get(fo.pk, 0)
        context = {
            "include_groups": _is_team_owner(request.user, team),
            "include_members": _is_manager(request.user, team),
        }
        return Response(VaultFolderSerializer(folders, many=True, context=context).data)

    def post(self, request):
        team = request.user.active_team
        if not _is_manager(request.user, team):
            return Response(status=status.HTTP_403_FORBIDDEN)
        ser = VaultFolderSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        name = ser.validated_data["name"]
        if VaultFolder.objects.filter(team=team, name__iexact=name).exists():
            return Response(
                {"detail": f"A folder called '{name}' already exists."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        folder = VaultFolder.objects.create(team=team, name=name, created_by=request.user)
        AuditService.log_request(
            request, ActivityLog.Action.CREDENTIAL_UPDATED,
            description=f"Created vault folder '{folder.name}'",
            resource_type="vault_folder", resource_id=folder.pk,
        )
        return Response(VaultFolderSerializer(folder).data, status=status.HTTP_201_CREATED)


class VaultFolderDetailView(APIView):
    """PATCH/DELETE /api/v1/credentials/folders/<pk>/ — managers and owners.

    Deleting a folder unfiles its credentials (they are not deleted) and drops
    the group access that came through it.
    """

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def _get(self, request, pk):
        team = request.user.active_team
        if not _is_manager(request.user, team):
            return None, Response(status=status.HTTP_403_FORBIDDEN)
        folder = VaultFolder.objects.filter(pk=pk, team=team).first()
        if folder is None:
            return None, Response(status=status.HTTP_404_NOT_FOUND)
        return folder, None

    def patch(self, request, pk):
        folder, err = self._get(request, pk)
        if err:
            return err
        ser = VaultFolderSerializer(folder, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        name = ser.validated_data.get("name", folder.name)
        if VaultFolder.objects.filter(team=folder.team, name__iexact=name).exclude(pk=folder.pk).exists():
            return Response(
                {"detail": f"A folder called '{name}' already exists."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        old = folder.name
        folder.name = name
        folder.save(update_fields=["name", "updated_at"])
        AuditService.log_request(
            request, ActivityLog.Action.CREDENTIAL_UPDATED,
            description=f"Renamed vault folder '{old}' to '{folder.name}'",
            resource_type="vault_folder", resource_id=folder.pk,
        )
        return Response(VaultFolderSerializer(folder).data)

    def delete(self, request, pk):
        folder, err = self._get(request, pk)
        if err:
            return err
        name, count = folder.name, folder.credentials.count()
        folder.delete()
        AuditService.log_request(
            request, ActivityLog.Action.CREDENTIAL_UPDATED,
            description=f"Deleted vault folder '{name}', unfiling {count} credential(s)",
            resource_type="vault_folder", resource_id=pk,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)



class VaultFolderMembersView(APIView):
    """POST /api/v1/credentials/folders/<pk>/members/ {user_ids, can_view_password}
    DELETE /api/v1/credentials/folders/<pk>/members/<user_id>/

    Share a whole folder with people — managers and owners. Everything filed
    in it reaches them, including what is filed later. Re-sharing updates the
    "see password" flag. Owners and managers already see the vault, and a
    viewer cannot reveal, so only member roles can be added.
    """

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def _folder(self, request, pk):
        team = request.user.active_team
        if not _is_manager(request.user, team):
            return None, Response(status=status.HTTP_403_FORBIDDEN)
        folder = VaultFolder.objects.filter(pk=pk, team=team).first()
        if folder is None:
            return None, Response(status=status.HTTP_404_NOT_FOUND)
        return folder, None

    def post(self, request, pk):
        from apps.accounts.models import TeamMembership

        folder, err = self._folder(request, pk)
        if err:
            return err
        ser = FolderShareWriteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        can_view = ser.validated_data["can_view_password"]
        members = TeamMembership.objects.filter(
            team=folder.team, user_id__in=ser.validated_data["user_ids"]
        ).select_related("user")
        if len(members) != len(set(ser.validated_data["user_ids"])):
            return Response(
                {"detail": "Some of those people are not on this team."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        targets = [m for m in members if m.role in SHAREABLE_ROLES]
        for m in targets:
            FolderShare.objects.update_or_create(
                folder=folder, user=m.user,
                defaults={"can_view_password": can_view, "shared_by": request.user},
            )
        if targets:
            AuditService.log_request(
                request, ActivityLog.Action.CREDENTIAL_SHARED,
                description=(
                    f"Shared folder '{folder.name}' with "
                    + ", ".join(_display_name(m.user) for m in targets)
                    + (" (can see passwords)" if can_view else "")
                ),
                resource_type="vault_folder", resource_id=folder.pk,
                metadata={
                    "shared_with_user_ids": [str(m.user_id) for m in targets],
                    "can_view_password": can_view,
                },
            )
        return Response({"shared_with": len(targets)})

    def delete(self, request, pk, user_id):
        folder, err = self._folder(request, pk)
        if err:
            return err
        share = FolderShare.objects.filter(folder=folder, user_id=user_id).select_related("user").first()
        if share is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        name = _display_name(share.user)
        share.delete()
        AuditService.log_request(
            request, ActivityLog.Action.CREDENTIAL_UNSHARED,
            description=f"Stopped sharing folder '{folder.name}' with {name}",
            resource_type="vault_folder", resource_id=folder.pk,
            metadata={"user_id": str(user_id)},
        )
        return Response(status=status.HTTP_204_NO_CONTENT)
