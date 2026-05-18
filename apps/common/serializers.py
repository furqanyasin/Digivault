from rest_framework import serializers


class BaseModelSerializer(serializers.ModelSerializer):
    """Base serializer that always includes id, created_at, updated_at as read-only."""

    class Meta:
        read_only_fields = ("id", "created_at", "updated_at")
