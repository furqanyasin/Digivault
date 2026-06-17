import csv
import io
import logging

from django.db.models import Q
from rest_framework import generics, permissions, status
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.models import ActivityLog
from apps.audit.services import AuditService
from apps.clients.models import Client
from apps.clients.serializers import ClientLookupSerializer, ClientSerializer
from apps.clients.services import push_status_to_clickup, sync_client_from_clickup

logger = logging.getLogger(__name__)

_HOSTING_NORMALIZE = {
    "site ground": "siteground",
    "siteground": "siteground",
    "wpengine": "wpengine",
    "wp engine": "wpengine",
    "cloudways": "cloudways",
    "bluehost": "bluehost",
    "godaddy": "godaddy",
    "squarespace": "squarespace",
    "wix": "wix",
    "shopify": "shopify",
}

_MIGRATION_STATUS_MAP = {
    "no - we didn't do": "not_done",
    "no we didn't do": "not_done",
    "yes - from wpengin to siteground": "done_to_siteground",
    "yes - from wpengine to siteground": "done_to_siteground",
}

_MIGRATION_CONFIRM_MAP = {
    "yes, we can do migration": "can_do",
    "no, we can't": "cannot",
}

_PPC_MAP = {
    "yes": "yes",
    "no": "no",
    "no, we can't": "no",
}


def _parse_hosting(raw: str) -> str:
    return _HOSTING_NORMALIZE.get(raw.lower().strip(), "")


def _team(request):
    return request.user.active_team


class ClientListCreateView(generics.ListCreateAPIView):
    """GET /api/v1/clients/   POST /api/v1/clients/"""

    serializer_class = ClientSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        team = _team(self.request)
        qs = Client.objects.for_team(team)
        q = self.request.query_params.get("q", "").strip()
        status_filter = self.request.query_params.get("status", "").strip()
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(website_url__icontains=q))
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs

    def perform_create(self, serializer):
        client = serializer.save(team=_team(self.request))
        AuditService.log_request(
            self.request, ActivityLog.Action.CLIENT_CREATED,
            description=f"Created client '{client.name}'",
            resource_type="client", resource_id=client.pk,
        )


class ClientDetailView(generics.RetrieveUpdateAPIView):
    """GET /api/v1/clients/<pk>/   PATCH /api/v1/clients/<pk>/"""

    serializer_class = ClientSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Client.objects.for_team(_team(self.request))

    def perform_update(self, serializer):
        client = serializer.save()
        AuditService.log_request(
            self.request, ActivityLog.Action.CLIENT_UPDATED,
            description=f"Updated client '{client.name}'",
            resource_type="client", resource_id=client.pk,
        )


class ClientActivateView(APIView):
    """POST /api/v1/clients/<pk>/activate/"""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        try:
            client = Client.objects.for_team(_team(request)).get(pk=pk)
        except Client.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        Client.objects.filter(pk=pk).update(status=Client.Status.ACTIVE)
        client.status = Client.Status.ACTIVE
        push_status_to_clickup(client)
        AuditService.log_request(
            request, ActivityLog.Action.CLIENT_STATUS_CHANGED,
            description=f"Activated client '{client.name}'",
            resource_type="client", resource_id=client.pk,
            metadata={"status": "active"},
        )
        return Response({"detail": "Client activated."})


class ClientDeactivateView(APIView):
    """POST /api/v1/clients/<pk>/deactivate/"""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        try:
            client = Client.objects.for_team(_team(request)).get(pk=pk)
        except Client.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        Client.objects.filter(pk=pk).update(status=Client.Status.INACTIVE)
        client.status = Client.Status.INACTIVE
        push_status_to_clickup(client)
        AuditService.log_request(
            request, ActivityLog.Action.CLIENT_STATUS_CHANGED,
            description=f"Deactivated client '{client.name}'",
            resource_type="client", resource_id=client.pk,
            metadata={"status": "inactive"},
        )
        return Response({"detail": "Client deactivated (not deleted)."})


class ClientSyncClickUpView(APIView):
    """POST /api/v1/clients/<pk>/sync/"""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        try:
            client = Client.objects.for_team(_team(request)).get(pk=pk)
        except Client.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        ok = sync_client_from_clickup(client)
        if not ok:
            return Response({"detail": "Sync failed. Check CLICKUP_API_TOKEN and task ID."}, status=status.HTTP_502_BAD_GATEWAY)
        client.refresh_from_db()
        AuditService.log_request(
            request, ActivityLog.Action.CLIENT_SYNCED,
            description=f"Synced client '{client.name}' from ClickUp",
            resource_type="client", resource_id=client.pk,
        )
        return Response(ClientSerializer(client).data)


class ClientSyncAllView(APIView):
    """POST /api/v1/clients/sync-all/ — sync every client that has a ClickUp task ID."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        clients = Client.objects.for_team(_team(request)).exclude(clickup_task_id="")
        synced, failed = 0, 0
        for client in clients:
            if sync_client_from_clickup(client):
                synced += 1
            else:
                failed += 1
        if synced:
            AuditService.log_request(
                request, ActivityLog.Action.CLIENT_SYNCED,
                description=f"Synced {synced} client(s) from ClickUp",
                resource_type="client", metadata={"synced": synced, "failed": failed},
            )
        return Response({"synced": synced, "failed": failed})


class ClientSearchView(APIView):
    """GET /api/v1/clients/search/?q=abc.com  — instant lookup for CSM queries."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        q = request.query_params.get("q", "").strip().lower()
        if not q:
            return Response({"results": []})

        # Strip protocol / www for flexible matching
        for prefix in ("https://", "http://", "www."):
            q = q.removeprefix(prefix)
        q = q.rstrip("/")

        clients = Client.objects.for_team(_team(request)).filter(
            Q(website_url__icontains=q) | Q(name__icontains=q)
        )
        return Response({
            "query": q,
            "count": clients.count(),
            "results": ClientLookupSerializer(clients, many=True).data,
        })


class ClientImportView(APIView):
    """POST /api/v1/clients/import/ — import from ClickUp CSV export."""

    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request):
        team = _team(request)
        file_obj = request.FILES.get("file")
        if not file_obj:
            return Response({"detail": "No file provided."}, status=status.HTTP_400_BAD_REQUEST)

        _MAX_CSV_BYTES = 5 * 1024 * 1024  # 5 MB
        if file_obj.size > _MAX_CSV_BYTES:
            return Response({"detail": "File too large. Maximum allowed size is 5 MB."}, status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)

        try:
            text = file_obj.read().decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(text))
        except Exception:
            return Response({"detail": "Could not parse the file. Please upload a valid UTF-8 CSV."}, status=status.HTTP_400_BAD_REQUEST)

        created, updated, skipped = 0, 0, 0
        errors = []

        for i, row in enumerate(reader, start=2):
            task_id = (row.get("Task ID") or "").strip()
            name = (row.get("Task Name") or "").strip()
            if not name:
                skipped += 1
                continue

            website_url = (row.get("Websites URL (short text)") or "").strip()
            raw_hosting = (row.get("Hosting Platform (drop down)") or "").strip()
            hosting = _parse_hosting(raw_hosting) if raw_hosting else ""

            raw_migration = (row.get("Migration Status (drop down)") or "").strip().lower()
            migration_status = _MIGRATION_STATUS_MAP.get(raw_migration, "not_done" if raw_migration else "")

            raw_confirm = (row.get("Confirmation from CSM for Migration (drop down)") or "").strip().lower()
            csm_confirm = _MIGRATION_CONFIRM_MAP.get(raw_confirm, "")

            raw_ppc = (row.get("Are we running PPC Ads (drop down)") or "").strip().lower()
            ppc = "yes" if raw_ppc.startswith("yes") else ("no" if raw_ppc.startswith("no") else "")

            # "Domain Access" is the current sample header; the long
            # "Where we have the domain access (drop down)" is the legacy
            # ClickUp-export header, still accepted for backward compatibility.
            domain_access = (
                row.get("Domain Access")
                or row.get("Where we have the domain access (drop down)")
                or ""
            ).strip()
            comments = (row.get("Comments (short text)") or "").strip()

            raw_built = (row.get("Website Built by Digi") or row.get("Website built by Digi  (drop down)") or "").strip()
            built_by_digi = raw_built if raw_built else ""

            raw_maintained = (row.get("Website Maintained by Digi") or row.get("Website Maintained by Digi (drop down)") or "").strip()
            maintained_by_digi = raw_maintained if raw_maintained else ""

            defaults = {
                "name": name,
                "website_url": website_url,
                "hosting_platform": hosting,
                "migration_status": migration_status,
                "csm_migration_confirmation": csm_confirm,
                "running_ppc_ads": ppc,
                "domain_access_location": domain_access,
                "comments": comments,
                "website_built_by_digi": built_by_digi,
                "website_maintained_by_digi": maintained_by_digi,
            }

            if task_id:
                obj, was_created = Client.objects.update_or_create(
                    team=team, clickup_task_id=task_id,
                    defaults=defaults,
                )
            else:
                obj, was_created = Client.objects.update_or_create(
                    team=team, name=name,
                    defaults=defaults,
                )

            if was_created:
                created += 1
            else:
                updated += 1

        if created or updated:
            AuditService.log_request(
                request, ActivityLog.Action.CLIENT_IMPORTED,
                description=f"Imported clients from CSV — {created} created, {updated} updated",
                resource_type="client",
                metadata={"created": created, "updated": updated, "skipped": skipped},
            )
        return Response({
            "created": created,
            "updated": updated,
            "skipped": skipped,
            "errors": errors,
        })
