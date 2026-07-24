import csv
import io
import logging
from datetime import datetime

from django.db.models import Q
from django.http import HttpResponse
from rest_framework import generics, permissions, status
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.models import ActivityLog
from apps.audit.services import AuditService
from apps.clients.models import Client
from apps.clients.serializers import ClientLookupSerializer, ClientSerializer

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

_PPC_MAP = {
    "yes": "yes",
    "no": "no",
    "no, we can't": "no",
}

# Reverse maps (code → human label) used when EXPORTING so the sheet is readable
# and re-imports cleanly. The model stores codes; these fields carry no field-level
# `choices`, so there is no get_*_display() — we map explicitly.
_HOSTING_LABELS = {
    "wpengine": "WPEngine", "siteground": "SiteGround", "cloudways": "Cloudways",
    "bluehost": "Bluehost", "godaddy": "GoDaddy", "squarespace": "Squarespace",
    "wix": "Wix", "shopify": "Shopify", "other": "Other",
}
_TIER_LABELS = {"gold": "Gold", "silver": "Silver", "bronze": "Bronze"}
_ACCESS_LEVEL_LABELS = {
    "full_admin": "Full admin", "delegate": "Delegate access", "none": "No access",
}
_STATUS_CODES = {"active", "paused", "offboarded"}


def _parse_hosting(raw: str) -> str:
    r = raw.lower().strip()
    if r in _HOSTING_LABELS:  # already a stored code (e.g. an export round-trip)
        return r
    return _HOSTING_NORMALIZE.get(r, "")


def _parse_status(raw: str) -> str:
    r = raw.lower().strip()
    if r in _STATUS_CODES:
        return r
    if r == "inactive":  # legacy exports
        return "offboarded"
    return "active"


def _parse_tier(raw: str) -> str:
    r = raw.lower().strip()
    if r in _TIER_LABELS:
        return r
    # Legacy support-tier exports
    return {"premium": "gold", "standard": "silver", "basic": "bronze"}.get(r, "")


def _parse_access_level(raw: str) -> str:
    r = raw.lower().strip()
    if r in _ACCESS_LEVEL_LABELS:
        return r
    for code, label in _ACCESS_LEVEL_LABELS.items():
        if r == label.lower():
            return code
    return ""


def _parse_departments(raw: str) -> list:
    parts = [p.strip().lower() for p in (raw or "").split(",")]
    return [p for p in parts if p in Client.DEPARTMENTS]


def _parse_date(raw: str):
    """Parse a date cell. Exports write ISO (YYYY-MM-DD); also accept US M/D/Y."""
    r = (raw or "").strip()
    if not r:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d/%m/%Y"):
        try:
            return datetime.strptime(r, fmt).date()
        except ValueError:
            continue
    return None


def _parse_bool(raw: str, default: bool = True) -> bool:
    """Parse a Yes/No-style cell. Blank falls back to `default`."""
    r = (raw or "").strip().lower()
    if not r:
        return default
    return r in ("yes", "y", "true", "1", "on", "enabled")


# Canonical CSV columns — shared by the export, the sample, and the importer.
EXPORT_HEADERS = [
    "Client Name",
    "Websites URL (short text)",
    "Status",
    "Tier",
    "Hosting Platform (drop down)",
    "Hosting Platform (Other)",
    "Website Access Level",
    "Domain Access",
    "Hosting Renewal Date",
    "Domain Renewal Date",
    "Website Built by Digi",
    "Website Maintained by Digi",
    "Departments",
    "Desktop Notifications",
    "Email Notifications",
    "Notes",
]


def _team(request):
    return request.user.active_team


def _sync_hosting_to_websites(client) -> None:
    """Mirror the client's hosting renewal date onto its website(s).

    The website's hosting expiry lives on DomainInfo (shown on the Access & Domain
    tab and used for expiry alerts). Without this, a date set on the client never
    appears on the website. Matches by the Website.client FK or a same-domain
    website in the team. Only writes when the client has a date — never clears a
    website-set date.
    """
    if not client.hosting_renewal_date:
        return

    from datetime import datetime, time

    from django.utils import timezone

    from apps.domains.models import DomainInfo
    from apps.websites.models import Website

    dt = datetime.combine(client.hosting_renewal_date, time.min)
    if timezone.is_aware(timezone.now()):
        dt = timezone.make_aware(dt)

    websites = Website.objects.filter(team=client.team).filter(
        Q(client=client) | Q(domain__iexact=client.domain)
    )
    for w in websites:
        di, _ = DomainInfo.objects.get_or_create(website=w)
        if di.hosting_expires_at != dt:
            di.hosting_expires_at = dt
            di.save(update_fields=["hosting_expires_at", "updated_at"])


def _auto_create_website(client, request) -> None:
    """Attach a Website to a newly added client, creating one if needed.

    Matches by domain (case-insensitive) within the team, so re-adding a client
    never duplicates a tracked site. An existing site with no client is adopted
    rather than skipped — that's what makes "wipe the clients and re-import"
    reattach the sites (Website.client is SET_NULL, so deleting a client leaves
    its website behind, orphaned).

    A site already owned by a different client is left alone: re-importing must
    never silently move a website between clients.

    Creation triggers the usual post_save provisioning (uptime monitor, status
    page, initial checks) via apps.websites.signals.
    """
    if not client.website_url:
        return

    from apps.websites.models import Website

    domain = client.domain
    if not domain:
        return

    existing = Website.objects.filter(team=client.team, domain__iexact=domain).first()
    if existing is not None:
        if existing.client_id is None:
            existing.client = client
            existing.save(update_fields=["client", "updated_at"])
            AuditService.log_request(
                request, ActivityLog.Action.WEBSITE_UPDATED,
                description=f"Linked existing website '{existing.domain}' to client '{client.name}'",
                resource_type="website", resource_id=existing.pk,
            )
        return

    website = Website.objects.create(
        team=client.team,
        client=client,
        name=client.name,
        domain=domain,
    )
    AuditService.log_request(
        request, ActivityLog.Action.WEBSITE_CREATED,
        description=f"Auto-created website '{website.domain}' for client '{client.name}'",
        resource_type="website", resource_id=website.pk,
    )


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
        _sync_hosting_to_websites(client)
        _auto_create_website(client, self.request)
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
        old_status = serializer.instance.status
        client = serializer.save()
        _sync_hosting_to_websites(client)
        if client.status != old_status:
            AuditService.log_request(
                self.request, ActivityLog.Action.CLIENT_STATUS_CHANGED,
                description=f"Changed client '{client.name}' status to {client.status}",
                resource_type="client", resource_id=client.pk,
                metadata={"status": client.status},
            )
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
        AuditService.log_request(
            request, ActivityLog.Action.CLIENT_STATUS_CHANGED,
            description=f"Activated client '{client.name}'",
            resource_type="client", resource_id=client.pk,
            metadata={"status": "active"},
        )
        return Response({"detail": "Client activated."})


class ClientDeactivateView(APIView):
    """POST /api/v1/clients/<pk>/deactivate/ — marks the client offboarded."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        try:
            client = Client.objects.for_team(_team(request)).get(pk=pk)
        except Client.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        Client.objects.filter(pk=pk).update(status=Client.Status.OFFBOARDED)
        AuditService.log_request(
            request, ActivityLog.Action.CLIENT_STATUS_CHANGED,
            description=f"Offboarded client '{client.name}'",
            resource_type="client", resource_id=client.pk,
            metadata={"status": "offboarded"},
        )
        return Response({"detail": "Client offboarded (not deleted)."})


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
    """POST /api/v1/clients/import/ — import clients from a CSV export."""

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
            # "Client Name" is the current header; "Task Name" is the legacy
            # ClickUp-export header, still accepted for backward compatibility.
            name = ((row.get("Client Name") or row.get("Task Name")) or "").strip()
            if not name:
                skipped += 1
                continue

            website_url = (row.get("Websites URL (short text)") or "").strip()
            hosting = _parse_hosting(row.get("Hosting Platform (drop down)") or "")
            hosting_other = (row.get("Hosting Platform (Other)") or "").strip()
            hosting_renewal_date = _parse_date(row.get("Hosting Renewal Date") or "")
            domain_renewal_date = _parse_date(row.get("Domain Renewal Date") or "")
            notify_desktop = _parse_bool(row.get("Desktop Notifications") or "")
            notify_email = _parse_bool(row.get("Email Notifications") or "")

            # "Domain Access" is the current sample header; the long
            # "Where we have the domain access (drop down)" is the legacy
            # ClickUp-export header, still accepted for backward compatibility.
            domain_access = (
                row.get("Domain Access")
                or row.get("Where we have the domain access (drop down)")
                or ""
            ).strip()
            notes = (row.get("Notes") or "").strip()

            raw_built = (row.get("Website Built by Digi") or row.get("Website built by Digi  (drop down)") or "").strip()
            built_by_digi = raw_built if raw_built else ""

            raw_maintained = (row.get("Website Maintained by Digi") or row.get("Website Maintained by Digi (drop down)") or "").strip()
            maintained_by_digi = raw_maintained if raw_maintained else ""

            defaults = {
                "name": name,
                "website_url": website_url,
                "status": _parse_status(row.get("Status") or ""),
                "tier": _parse_tier(row.get("Tier") or ""),
                "hosting_platform": hosting,
                "hosting_platform_other": hosting_other,
                "hosting_renewal_date": hosting_renewal_date,
                "domain_renewal_date": domain_renewal_date,
                "domain_access_location": domain_access,
                "website_access_level": _parse_access_level(row.get("Website Access Level") or ""),
                "departments": _parse_departments(row.get("Departments") or ""),
                "notes": notes,
                "website_built_by_digi": built_by_digi,
                "website_maintained_by_digi": maintained_by_digi,
                "notify_desktop": notify_desktop,
                "notify_email": notify_email,
            }

            obj, was_created = Client.objects.update_or_create(
                team=team, name=name,
                defaults=defaults,
            )

            if was_created:
                created += 1
                _auto_create_website(obj, request)
            else:
                updated += 1

            _sync_hosting_to_websites(obj)

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


class ClientExportView(APIView):
    """GET /api/v1/clients/export/ — download all clients as a re-importable CSV."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        clients = Client.objects.for_team(_team(request)).order_by("name")

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(EXPORT_HEADERS)
        for c in clients:
            writer.writerow([
                c.name,
                c.website_url,
                c.status,
                _TIER_LABELS.get(c.tier, ""),
                _HOSTING_LABELS.get(c.hosting_platform, c.hosting_platform or ""),
                c.hosting_platform_other,
                _ACCESS_LEVEL_LABELS.get(c.website_access_level, ""),
                c.domain_access_location,
                c.hosting_renewal_date.isoformat() if c.hosting_renewal_date else "",
                c.domain_renewal_date.isoformat() if c.domain_renewal_date else "",
                c.website_built_by_digi,
                c.website_maintained_by_digi,
                ",".join(c.departments or []),
                "Yes" if c.notify_desktop else "No",
                "Yes" if c.notify_email else "No",
                c.notes,
            ])

        AuditService.log_request(
            request, ActivityLog.Action.CLIENT_EXPORTED,
            description=f"Exported {clients.count()} client(s) to CSV",
            resource_type="client",
        )

        resp = HttpResponse(buf.getvalue(), content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = 'attachment; filename="clients-export.csv"'
        return resp
