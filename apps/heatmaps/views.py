from rest_framework import generics, permissions

from apps.common.permissions import IsTeamMember
from apps.heatmaps.models import HeatmapEvent
from apps.heatmaps.serializers import HeatmapEventSerializer


class HeatmapEventListCreateView(generics.ListCreateAPIView):
    serializer_class = HeatmapEventSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def get_queryset(self):
        user = self.request.user
        team = user.active_team
        if team is None:
            return HeatmapEvent.objects.none()

        qs = HeatmapEvent.objects.filter(team=team)
        page_path = self.request.query_params.get("page_path")
        event_type = self.request.query_params.get("event_type")
        if page_path:
            qs = qs.filter(page_path=page_path)
        if event_type:
            qs = qs.filter(event_type=event_type)
        return qs.order_by("-created_at")[:200]
