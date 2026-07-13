from rest_framework import serializers

from apps.heatmaps.models import HeatmapEvent


class HeatmapEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = HeatmapEvent
        fields = [
            "id",
            "page_path",
            "page_title",
            "event_type",
            "x",
            "y",
            "viewport_width",
            "viewport_height",
            "metadata",
            "created_at",
        ]
        read_only_fields = ["id", "created_at", "team", "user"]

    def create(self, validated_data):
        request = self.context["request"]
        team = getattr(request.user, "active_team", None)
        if team is None:
            raise serializers.ValidationError("No active team is selected.")
        return HeatmapEvent.objects.create(
            team=team,
            user=request.user,
            **validated_data,
        )
