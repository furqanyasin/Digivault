from rest_framework import serializers

from apps.common.serializers import BaseModelSerializer
from apps.scripts.models import (
    DetectedForm,
    FormSubmissionError,
    JsError,
    Script,
    ScriptChange,
)

# Hard caps on ingest payload list lengths — a single page should never
# legitimately exceed these, and they bound the work queued into Celery.
MAX_SCRIPTS_PER_PAYLOAD = 500
MAX_FORMS_PER_PAYLOAD = 100
MAX_FIELDS_PER_FORM = 200


class IngestScriptSerializer(serializers.Serializer):
    """A single script entry within an ingest payload."""

    src = serializers.CharField(max_length=2048, allow_blank=True)
    location = serializers.ChoiceField(
        choices=Script.Location.values, default=Script.Location.UNKNOWN
    )
    is_async = serializers.BooleanField(default=False)
    is_defer = serializers.BooleanField(default=False)
    is_inline = serializers.BooleanField(default=False)
    inline_hash = serializers.CharField(max_length=64, allow_blank=True, default="")
    wp_plugin = serializers.CharField(max_length=200, allow_blank=True, default="")
    wp_post_id = serializers.IntegerField(allow_null=True, default=None)


class IngestFormFieldSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200, allow_blank=True, default="")
    type = serializers.CharField(max_length=50, allow_blank=True, default="text")
    label = serializers.CharField(max_length=200, allow_blank=True, default="")
    required = serializers.BooleanField(default=False)


class IngestFormSerializer(serializers.Serializer):
    form_id = serializers.CharField(max_length=200, allow_blank=True, default="")
    form_name = serializers.CharField(max_length=200, allow_blank=True, default="")
    form_action = serializers.CharField(max_length=2048, allow_blank=True, default="")
    form_method = serializers.CharField(max_length=10, allow_blank=True, default="post")
    detection_type = serializers.ChoiceField(
        choices=DetectedForm.DetectionType.values,
        default=DetectedForm.DetectionType.NATIVE,
    )
    provider = serializers.CharField(max_length=100, allow_blank=True, default="")
    # Where this form's submissions go. Ingest-side it is only leniently
    # validated — a malformed value must not 400 the whole payload (which would
    # drop the scripts too) — normalization happens in the upsert task.
    recipient_email = serializers.CharField(
        max_length=254, allow_blank=True, default=""
    )
    fields = IngestFormFieldSerializer(
        many=True, default=list, max_length=MAX_FIELDS_PER_FORM
    )


class FormErrorIngestSerializer(serializers.Serializer):
    """Posted by the snippet when a form submission visibly fails."""

    site_id = serializers.CharField(max_length=64)
    page_url = serializers.URLField(max_length=2048)
    source = serializers.CharField(max_length=100, allow_blank=True, default="")
    form_id = serializers.CharField(max_length=200, allow_blank=True, default="")
    message = serializers.CharField(max_length=2000)


class JsErrorIngestSerializer(serializers.Serializer):
    """Posted by the snippet when a page throws an uncaught JavaScript error."""

    site_id = serializers.CharField(max_length=64)
    page_url = serializers.URLField(max_length=2048)
    message = serializers.CharField(max_length=2000)
    source_url = serializers.CharField(max_length=2048, allow_blank=True, default="")
    line_no = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    col_no = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    stack = serializers.CharField(max_length=4000, allow_blank=True, default="")


class JsErrorSerializer(BaseModelSerializer):
    class Meta:
        model = JsError
        fields = (
            "id", "message", "source_url", "line_no", "col_no", "stack",
            "page_url", "browser", "hits", "is_resolved",
            "last_seen_at", "created_at",
        )
        read_only_fields = fields


class FormSubmissionIngestSerializer(serializers.Serializer):
    """Posted by the snippet when a native form is submitted, to count it."""

    site_id = serializers.CharField(max_length=64)
    page_url = serializers.URLField(max_length=2048)
    form = IngestFormSerializer()


class FormSubmissionErrorSerializer(BaseModelSerializer):
    # Attribution for the team-wide /form-errors/ list, which mixes sites — the
    # same reason ScriptChangeSerializer carries website_name. Without it a
    # caller can see that N forms are broken but not on which site.
    website_name = serializers.SerializerMethodField()

    class Meta:
        model = FormSubmissionError
        fields = (
            "id", "website", "website_name", "source", "form_id",
            "page_url", "message", "created_at",
        )
        read_only_fields = fields

    def get_website_name(self, obj) -> str:
        return obj.website.name or obj.website.domain


class IngestPayloadSerializer(serializers.Serializer):
    """Payload posted by the universal JS snippet."""

    site_id = serializers.CharField(max_length=64)
    page_url = serializers.URLField(max_length=2048)
    scripts = IngestScriptSerializer(many=True, max_length=MAX_SCRIPTS_PER_PAYLOAD)
    forms = IngestFormSerializer(
        many=True, default=list, max_length=MAX_FORMS_PER_PAYLOAD
    )
    user_agent = serializers.CharField(max_length=512, allow_blank=True, default="")
    snippet_version = serializers.CharField(max_length=20, allow_blank=True, default="")


class ScriptSerializer(BaseModelSerializer):
    class Meta:
        model = Script
        fields = (
            "id",
            "src_url",
            "src_domain",
            "provider",
            "category",
            "location",
            "scope",
            "is_async",
            "is_defer",
            "is_inline",
            "wp_plugin",
            "seen_on_pages",
            "is_active",
            "is_suspicious",
            "suspicion_severity",
            "suspicion_reasons",
            "review_status",
            "first_seen_at",
            "last_seen_at",
            "created_at",
        )
        read_only_fields = (
            "id", "src_url", "src_domain", "provider", "category", "location",
            "scope", "is_async", "is_defer", "is_inline", "wp_plugin",
            "seen_on_pages", "is_active", "first_seen_at", "last_seen_at", "created_at",
        )


class DetectedFormSerializer(BaseModelSerializer):
    # Embedded (cross-origin iframe) forms belong to a third party — their
    # submissions can't be verified from the page, so the UI counts only
    # managed (native / div-based) forms.
    is_managed = serializers.SerializerMethodField()

    class Meta:
        model = DetectedForm
        fields = (
            "id", "page_url", "form_id", "form_name",
            "form_action", "form_method", "fields",
            "detection_type", "provider", "recipient_email", "recipient_source",
            "is_managed",
            "submission_count", "last_submission_at",
            "first_seen_at", "last_seen_at",
        )
        read_only_fields = fields

    def get_is_managed(self, obj) -> bool:
        return obj.detection_type != DetectedForm.DetectionType.EMBEDDED


class ScriptChangeSerializer(BaseModelSerializer):
    script = ScriptSerializer(read_only=True)
    is_acknowledged = serializers.ReadOnlyField()
    # Who resolved the change — shown in the per-site change log.
    acknowledged_by_email = serializers.SerializerMethodField()
    # Attribution for the team-wide change list, which mixes sites together.
    website_name = serializers.SerializerMethodField()

    class Meta:
        model = ScriptChange
        fields = (
            "id",
            "website",
            "website_name",
            "change_type",
            "severity",
            "description",
            "old_value",
            "new_value",
            "script",
            "is_acknowledged",
            "acknowledged_at",
            "acknowledged_by",
            "acknowledged_by_email",
            "created_at",
        )
        read_only_fields = fields

    def get_acknowledged_by_email(self, obj) -> str | None:
        return obj.acknowledged_by.email if obj.acknowledged_by_id else None

    def get_website_name(self, obj) -> str:
        if not obj.website_id:
            return ""
        return obj.website.name or obj.website.domain
