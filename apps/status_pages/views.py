from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.mixins import TeamScopedMixin
from apps.common.permissions import IsTeamMember, TeamRolePermission
from apps.monitors.models import Monitor
from apps.status_pages.models import (
    MaintenanceWindow,
    StatusPage,
    StatusPageIncident,
    StatusPageMonitor,
)
from apps.status_pages.serializers import (
    MaintenanceWindowSerializer,
    PublicStatusPageSerializer,
    StatusPageIncidentSerializer,
    StatusPageMonitorSerializer,
    StatusPageSerializer,
)


class _PageScopedChildMixin:
    """Shared team-scoped access to a status page's child objects."""

    permission_classes = [permissions.IsAuthenticated, IsTeamMember, TeamRolePermission]
    child_model = None
    child_related = None  # related_name on StatusPage
    # Audit action codes set per subclass.
    audit_create_action = None
    audit_update_action = None
    audit_delete_action = None

    def _get_page(self):
        team = self.request.user.active_team
        return StatusPage.objects.filter(pk=self.kwargs["page_pk"], team=team).first()

    def get_queryset(self):
        page = self._get_page()
        if page is None:
            return self.child_model.objects.none()
        return getattr(page, self.child_related).all()

    def _audit(self, action, instance):
        if not action:
            return
        from apps.audit.services import AuditService
        AuditService.log_request(
            self.request, action,
            description=f"{action.label} on status page",
            resource_type="status_page", resource_id=getattr(instance, "status_page_id", instance.pk),
        )

    def perform_create(self, serializer):
        page = self._get_page()
        if page is None:
            from rest_framework.exceptions import NotFound
            raise NotFound("Status page not found.")
        instance = serializer.save(status_page=page)
        self._audit(self.audit_create_action, instance)

    def perform_update(self, serializer):
        instance = serializer.save()
        self._audit(self.audit_update_action, instance)

    def perform_destroy(self, instance):
        self._audit(self.audit_delete_action, instance)
        instance.delete()


class StatusPageIncidentListCreateView(_PageScopedChildMixin, generics.ListCreateAPIView):
    """GET/POST /api/v1/status-pages/<page_pk>/incidents/"""

    serializer_class = StatusPageIncidentSerializer
    child_model = StatusPageIncident
    child_related = "incidents"

    @property
    def audit_create_action(self):
        from apps.audit.models import ActivityLog
        return ActivityLog.Action.INCIDENT_POSTED


class StatusPageIncidentDetailView(_PageScopedChildMixin, generics.RetrieveUpdateDestroyAPIView):
    """GET/PATCH/DELETE /api/v1/status-pages/<page_pk>/incidents/<pk>/"""

    serializer_class = StatusPageIncidentSerializer
    child_model = StatusPageIncident
    child_related = "incidents"

    @property
    def audit_update_action(self):
        from apps.audit.models import ActivityLog
        return ActivityLog.Action.INCIDENT_UPDATED

    @property
    def audit_delete_action(self):
        from apps.audit.models import ActivityLog
        return ActivityLog.Action.INCIDENT_DELETED


class MaintenanceWindowListCreateView(_PageScopedChildMixin, generics.ListCreateAPIView):
    """GET/POST /api/v1/status-pages/<page_pk>/maintenance/"""

    serializer_class = MaintenanceWindowSerializer
    child_model = MaintenanceWindow
    child_related = "maintenance_windows"

    @property
    def audit_create_action(self):
        from apps.audit.models import ActivityLog
        return ActivityLog.Action.MAINTENANCE_SCHEDULED


class MaintenanceWindowDetailView(_PageScopedChildMixin, generics.RetrieveUpdateDestroyAPIView):
    """GET/PATCH/DELETE /api/v1/status-pages/<page_pk>/maintenance/<pk>/"""

    serializer_class = MaintenanceWindowSerializer
    child_model = MaintenanceWindow
    child_related = "maintenance_windows"

    @property
    def audit_delete_action(self):
        from apps.audit.models import ActivityLog
        return ActivityLog.Action.MAINTENANCE_DELETED


class StatusPageListCreateView(TeamScopedMixin, generics.ListCreateAPIView):
    """GET /api/v1/status-pages/   POST /api/v1/status-pages/"""

    queryset = StatusPage.objects.all()
    serializer_class = StatusPageSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeamMember, TeamRolePermission]

    def perform_create(self, serializer):
        from apps.audit.models import ActivityLog
        from apps.audit.services import AuditService
        page = serializer.save(team=self.request.user.active_team)
        AuditService.log_request(
            self.request, ActivityLog.Action.STATUS_PAGE_CREATED,
            description=f"Created status page '{page.name}'",
            resource_type="status_page", resource_id=page.pk,
        )


class StatusPageDetailView(TeamScopedMixin, generics.RetrieveUpdateDestroyAPIView):
    """GET/PATCH/DELETE /api/v1/status-pages/<pk>/"""

    queryset = StatusPage.objects.all()
    serializer_class = StatusPageSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeamMember, TeamRolePermission]

    def perform_destroy(self, instance):
        from apps.audit.models import ActivityLog
        from apps.audit.services import AuditService
        AuditService.log_request(
            self.request, ActivityLog.Action.STATUS_PAGE_DELETED,
            description=f"Deleted status page '{instance.name}'",
            resource_type="status_page", resource_id=instance.pk,
        )
        instance.delete()


class StatusPageMonitorListCreateView(generics.ListCreateAPIView):
    """GET /api/v1/status-pages/<page_pk>/monitors/
    POST /api/v1/status-pages/<page_pk>/monitors/
    """

    serializer_class = StatusPageMonitorSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeamMember, TeamRolePermission]

    def _get_page(self):
        team = self.request.user.active_team
        return StatusPage.objects.get(pk=self.kwargs["page_pk"], team=team)

    def get_queryset(self):
        try:
            page = self._get_page()
        except StatusPage.DoesNotExist:
            return StatusPageMonitor.objects.none()
        return page.monitors.select_related("monitor").all()

    def perform_create(self, serializer):
        page = self._get_page()
        team = self.request.user.active_team
        monitor = Monitor.objects.get(
            pk=serializer.validated_data.pop("monitor_id"), team=team
        )
        serializer.save(status_page=page, monitor=monitor)


class StatusPageMonitorDetailView(generics.RetrieveUpdateDestroyAPIView):
    """GET/PATCH/DELETE /api/v1/status-pages/<page_pk>/monitors/<pk>/"""

    serializer_class = StatusPageMonitorSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeamMember, TeamRolePermission]

    def get_queryset(self):
        team = self.request.user.active_team
        if team is None:
            return StatusPageMonitor.objects.none()
        return StatusPageMonitor.objects.filter(
            status_page__team=team,
            status_page_id=self.kwargs["page_pk"],
        ).select_related("monitor")


class PublicStatusPageView(APIView):
    """GET /api/v1/public/status/<slug>/  — no authentication required."""

    permission_classes = []
    authentication_classes = []

    def get(self, request, slug):
        try:
            page = (
                StatusPage.objects.prefetch_related(
                    "monitors__monitor", "incidents", "maintenance_windows"
                ).get(slug=slug)
            )
        except StatusPage.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        serializer = PublicStatusPageSerializer(page)
        return Response(serializer.data)
