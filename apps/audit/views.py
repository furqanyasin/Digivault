import csv

from django.http import HttpResponse
from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.models import ActivityLog
from apps.audit.serializers import ActivityLogSerializer
from apps.common.permissions import IsTeamMember

_MANAGER_ROLES = {"manager", "owner"}


def _role(user, team) -> str:
    from apps.accounts.models import TeamMembership
    try:
        return TeamMembership.objects.get(user=user, team=team).role
    except TeamMembership.DoesNotExist:
        return "viewer"


def _scoped_logs(request):
    """Role-aware base queryset: managers/owners see the whole team (optionally
    filtered by ?user_id); everyone else sees only their own activity."""
    user = request.user
    team = user.active_team
    if team is None:
        return ActivityLog.objects.none()

    is_manager = _role(user, team) in _MANAGER_ROLES
    if is_manager:
        user_id = request.query_params.get("user_id")
        qs = ActivityLog.objects.filter(team=team)
        if user_id:
            qs = qs.filter(actor_id=user_id)
    else:
        qs = ActivityLog.objects.filter(team=team, actor=user)
    return qs.select_related("actor")


def _valid_uuids(values):
    """Keep only well-formed UUIDs — resource_id is a free-text column, so a
    non-UUID value would make an id__in lookup raise."""
    import uuid

    out = set()
    for value in values:
        try:
            out.add(str(uuid.UUID(str(value))))
        except (ValueError, AttributeError, TypeError):
            continue
    return out


def _resource_names(rows):
    """Bulk-resolve website and client names for one page of log rows.

    Two queries whatever the page size; a SerializerMethodField doing its own
    lookup would be one query per row.
    """
    from apps.audit.serializers import ActivityLogSerializer
    from apps.clients.models import Client
    from apps.websites.models import Website

    website_ids, client_ids = set(), set()
    for row in rows:
        website_id = ActivityLogSerializer.website_id_of(row)
        if website_id:
            website_ids.add(website_id)
        if row.resource_type == "client" and row.resource_id:
            client_ids.add(str(row.resource_id))

    website_names = {}
    for site in (
        Website.objects.filter(id__in=_valid_uuids(website_ids))
        .select_related("client")
        .only("id", "name", "client__name")
    ):
        website_names[str(site.id)] = (
            site.name,
            site.client.name if site.client_id else "",
        )

    client_names = {
        str(c.id): c.name
        for c in Client.objects.filter(id__in=_valid_uuids(client_ids)).only("id", "name")
    }
    return {"website_names": website_names, "client_names": client_names}


def _apply_filters(qs, request):
    """Shared query-param filters: action, actions, resource_type, website_id,
    start/end, q."""
    params = request.query_params
    action = params.get("action")
    # A named view like "approvals" spans several action types, which a single
    # ?action= cannot express. Comma-separated, and ignored when empty so a
    # stray "?actions=" doesn't silently return nothing.
    actions = [a for a in (params.get("actions") or "").split(",") if a.strip()]
    resource_type = params.get("resource_type")
    website_id = params.get("website_id")
    client_id = params.get("client_id")
    start = params.get("start")
    end = params.get("end")
    q = params.get("q")

    if client_id:
        # Logs carry no client reference, so a client's activity is the actions
        # on the client record itself plus everything on the sites it owns.
        from django.db.models import Q

        from apps.websites.models import Website

        site_ids = [
            str(pk)
            for pk in Website.objects.filter(client_id=client_id).values_list("id", flat=True)
        ]
        clause = Q(resource_type="client", resource_id=str(client_id))
        if site_ids:
            clause |= Q(resource_id__in=site_ids) | Q(metadata__website_id__in=site_ids)
        qs = qs.filter(clause)
    if website_id:
        # Website-scoped actions carry the id either as the resource itself or
        # in metadata (script reviews, change acknowledgements).
        from django.db.models import Q

        qs = qs.filter(
            Q(resource_id=website_id) | Q(metadata__website_id=website_id)
        )
    if action:
        qs = qs.filter(action=action)
    if actions:
        qs = qs.filter(action__in=actions)
    if resource_type:
        qs = qs.filter(resource_type=resource_type)
    if start:
        qs = qs.filter(created_at__gte=start)
    if end:
        qs = qs.filter(created_at__lte=end)
    if q:
        qs = qs.filter(description__icontains=q)
    return qs


class ActivityLogListView(generics.ListAPIView):
    """GET /api/v1/logs/ — searchable activity log.

    Filters: ?action= &actions= &resource_type= &website_id= &client_id=
    &start= &end= &q= &user_id= (managers).
    """

    serializer_class = ActivityLogSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def get_queryset(self):
        return _apply_filters(_scoped_logs(self.request), self.request)

    def list(self, request, *args, **kwargs):
        """Serialize with website/client names resolved for the page in bulk.

        Overridden rather than using get_serializer_context() because the names
        can only be looked up once the page is known.
        """
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        rows = list(page) if page is not None else list(queryset)

        context = self.get_serializer_context()
        context.update(_resource_names(rows))
        serializer = self.get_serializer_class()(rows, many=True, context=context)

        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)


class ActivityLogExportView(APIView):
    """GET /api/v1/logs/export/ — CSV export of the (filtered) activity log."""

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    _COLUMNS = [
        "created_at", "actor_email", "action", "resource_type",
        "resource_id", "description", "ip_address",
    ]

    def get(self, request):
        qs = _apply_filters(_scoped_logs(request), request).order_by("-created_at")

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="activity-log.csv"'
        writer = csv.writer(response)
        writer.writerow(self._COLUMNS)
        for log in qs.iterator():
            writer.writerow([
                log.created_at.isoformat(),
                log.actor.email if log.actor else "system",
                log.action,
                log.resource_type,
                log.resource_id,
                log.description,
                log.ip_address or "",
            ])
        return response
