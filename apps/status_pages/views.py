from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.mixins import TeamScopedMixin
from apps.common.permissions import IsTeamMember
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

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]
    child_model = None
    child_related = None  # related_name on StatusPage

    def _get_page(self):
        team = self.request.user.active_team
        return StatusPage.objects.filter(pk=self.kwargs["page_pk"], team=team).first()

    def get_queryset(self):
        page = self._get_page()
        if page is None:
            return self.child_model.objects.none()
        return getattr(page, self.child_related).all()

    def perform_create(self, serializer):
        page = self._get_page()
        if page is None:
            from rest_framework.exceptions import NotFound
            raise NotFound("Status page not found.")
        serializer.save(status_page=page)


class StatusPageIncidentListCreateView(_PageScopedChildMixin, generics.ListCreateAPIView):
    """GET/POST /api/v1/status-pages/<page_pk>/incidents/"""

    serializer_class = StatusPageIncidentSerializer
    child_model = StatusPageIncident
    child_related = "incidents"


class StatusPageIncidentDetailView(_PageScopedChildMixin, generics.RetrieveUpdateDestroyAPIView):
    """GET/PATCH/DELETE /api/v1/status-pages/<page_pk>/incidents/<pk>/"""

    serializer_class = StatusPageIncidentSerializer
    child_model = StatusPageIncident
    child_related = "incidents"


class MaintenanceWindowListCreateView(_PageScopedChildMixin, generics.ListCreateAPIView):
    """GET/POST /api/v1/status-pages/<page_pk>/maintenance/"""

    serializer_class = MaintenanceWindowSerializer
    child_model = MaintenanceWindow
    child_related = "maintenance_windows"


class MaintenanceWindowDetailView(_PageScopedChildMixin, generics.RetrieveUpdateDestroyAPIView):
    """GET/PATCH/DELETE /api/v1/status-pages/<page_pk>/maintenance/<pk>/"""

    serializer_class = MaintenanceWindowSerializer
    child_model = MaintenanceWindow
    child_related = "maintenance_windows"


class StatusPageListCreateView(TeamScopedMixin, generics.ListCreateAPIView):
    """GET /api/v1/status-pages/   POST /api/v1/status-pages/"""

    queryset = StatusPage.objects.all()
    serializer_class = StatusPageSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def perform_create(self, serializer):
        serializer.save(team=self.request.user.active_team)


class StatusPageDetailView(TeamScopedMixin, generics.RetrieveUpdateDestroyAPIView):
    """GET/PATCH/DELETE /api/v1/status-pages/<pk>/"""

    queryset = StatusPage.objects.all()
    serializer_class = StatusPageSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeamMember]


class StatusPageMonitorListCreateView(generics.ListCreateAPIView):
    """GET /api/v1/status-pages/<page_pk>/monitors/
    POST /api/v1/status-pages/<page_pk>/monitors/
    """

    serializer_class = StatusPageMonitorSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

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
    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

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
