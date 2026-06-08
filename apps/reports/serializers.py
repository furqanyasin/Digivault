from rest_framework import serializers

from apps.common.serializers import BaseModelSerializer
from apps.reports.models import Report


class ReportSerializer(BaseModelSerializer):
    website_domain = serializers.SerializerMethodField()
    download_url = serializers.SerializerMethodField()

    class Meta:
        model = Report
        fields = (
            "id",
            "website",
            "website_domain",
            "period_start",
            "period_end",
            "report_format",
            "status",
            "download_url",
            "error",
            "generated_at",
            "created_at",
        )
        read_only_fields = fields

    def get_website_domain(self, obj) -> str:
        return obj.website.domain

    def get_download_url(self, obj) -> str | None:
        if obj.status == Report.Status.DONE and obj.file:
            return f"/api/v1/reports/{obj.id}/download/"
        return None


class ReportGenerateSerializer(serializers.Serializer):
    website_id = serializers.UUIDField()
    period_start = serializers.DateField()
    period_end = serializers.DateField()
    report_format = serializers.ChoiceField(
        choices=Report.Format.values, default=Report.Format.PDF
    )
