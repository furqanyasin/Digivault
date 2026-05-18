from apps.common.serializers import BaseModelSerializer
from apps.performance.models import CruxReport, PerformanceReport


class PerformanceReportSerializer(BaseModelSerializer):
    class Meta:
        model = PerformanceReport
        fields = (
            "id", "url", "strategy",
            "performance_score",
            "fcp_ms", "lcp_ms", "cls_score", "tbt_ms", "ttfb_ms", "si_ms", "tti_ms", "inp_ms",
            "fcp_rating", "lcp_rating", "cls_rating", "tbt_rating",
            "error", "checked_at",
        )
        read_only_fields = fields


class CruxReportSerializer(BaseModelSerializer):
    class Meta:
        model = CruxReport
        fields = (
            "id", "origin",
            "lcp_p75_ms", "fcp_p75_ms", "cls_p75", "inp_p75_ms", "ttfb_p75_ms", "fid_p75_ms",
            "lcp_good", "lcp_ni", "lcp_poor",
            "fcp_good", "fcp_ni", "fcp_poor",
            "cls_good", "cls_ni", "cls_poor",
            "inp_good", "inp_ni", "inp_poor",
            "error", "fetched_at",
        )
        read_only_fields = fields
