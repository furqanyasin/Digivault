import os

from django.http import HttpResponse
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView


class SnippetJsView(APIView):
    """GET /s.js — the tracking snippet served directly from Django."""
    permission_classes = []
    authentication_classes = []

    _js_path = os.path.join(os.path.dirname(__file__), "snippet.js")

    def get(self, request):
        with open(self._js_path, "r", encoding="utf-8") as f:
            content = f.read()
        response = HttpResponse(content, content_type="application/javascript; charset=utf-8")
        response["Cache-Control"] = "public, max-age=300"
        response["Access-Control-Allow-Origin"] = "*"
        return response

from apps.audit.models import ActivityLog
from apps.audit.services import AuditService
from apps.common.mixins import TeamScopedMixin
from apps.common.permissions import IsTeamMember
from apps.scripts.form_errors import (
    is_important_form_error,
    sanitize_error_message,
    sanitize_page_url,
)
from apps.scripts.models import DetectedForm, FormSubmissionError, Script, ScriptChange
from apps.scripts.serializers import (
    DetectedFormSerializer,
    FormErrorIngestSerializer,
    FormSubmissionErrorSerializer,
    IngestPayloadSerializer,
    ScriptChangeSerializer,
    ScriptSerializer,
)
from apps.scripts.tasks import process_ingest_payload
from apps.websites.models import Website


class ExtensionThrottle(AnonRateThrottle):
    rate = "300/hour"
    scope = "extension"


class IngestThrottle(AnonRateThrottle):
    """Rate limit per site_id so one site cannot starve others behind the same IP."""
    rate = "2000/day"
    scope = "ingest"

    def get_cache_key(self, request, view):
        site_id = (request.data.get("site_id") or "").strip()
        if site_id:
            return self.cache_format % {"scope": self.scope, "ident": site_id}
        return super().get_cache_key(request, view)


class IngestView(APIView):
    """POST /api/ingest/ — universal snippet endpoint.

    Validates the site_id and immediately returns 202; all heavy processing
    runs asynchronously in Celery so this response stays under 50ms.
    No JWT auth required — site_id acts as the website identifier.
    """

    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = [IngestThrottle]

    # Reject obviously-oversized bodies before parsing JSON.
    MAX_BODY_BYTES = 1 * 1024 * 1024  # 1 MB

    def post(self, request):
        content_length = request.META.get("CONTENT_LENGTH")
        try:
            if content_length and int(content_length) > self.MAX_BODY_BYTES:
                return Response(status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        except (TypeError, ValueError):
            pass

        serializer = IngestPayloadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # Reject unknown site_ids fast — before queuing
        try:
            website = Website.objects.get(site_id=data["site_id"])
        except Website.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        # Domain-binding: verify the request origin matches the registered domain
        origin = request.META.get("HTTP_ORIGIN") or request.META.get("HTTP_REFERER", "")
        if origin and website.domain:
            from urllib.parse import urlparse
            origin_host = urlparse(origin).netloc.lower().removeprefix("www.")
            site_host = website.domain.lower().removeprefix("www.").removeprefix("https://").removeprefix("http://").split("/")[0]
            if origin_host and site_host and origin_host != site_host:
                import logging as _log
                _log.getLogger(__name__).warning(
                    "Ingest domain mismatch: site_id=%s origin=%s registered=%s",
                    data["site_id"], origin_host, site_host,
                )
                return Response(status=status.HTTP_403_FORBIDDEN)

        process_ingest_payload.delay(
            site_id=website.site_id,
            payload={
                "page_url": data["page_url"],
                "scripts": [
                    {
                        "src": s["src"],
                        "location": s["location"],
                        "is_async": s["is_async"],
                        "is_defer": s["is_defer"],
                        "is_inline": s["is_inline"],
                        "inline_hash": s["inline_hash"],
                        "wp_plugin": s["wp_plugin"],
                        "wp_post_id": s["wp_post_id"],
                    }
                    for s in data["scripts"]
                ],
                "forms": [
                    {
                        "form_id": f["form_id"],
                        "form_name": f["form_name"],
                        "form_action": f["form_action"],
                        "form_method": f["form_method"],
                        "detection_type": f["detection_type"],
                        "provider": f["provider"],
                        "fields": f["fields"],
                    }
                    for f in data.get("forms", [])
                ],
                "user_agent": data["user_agent"],
                "snippet_version": data["snippet_version"],
            },
        )
        return Response(status=status.HTTP_202_ACCEPTED)


class FormErrorIngestView(APIView):
    """POST /api/ingest/form-errors/ — failed form submissions from the snippet.

    Same trust model as ingest: site_id identifies the website, origin must
    match the registered domain. Validation noise is acknowledged (202) but
    never stored, so probing reveals nothing; important failures are sanitised
    before save (no PII at rest).
    """

    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = [IngestThrottle]

    def post(self, request):
        serializer = FormErrorIngestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            website = Website.objects.get(site_id=data["site_id"])
        except Website.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        origin = request.META.get("HTTP_ORIGIN") or request.META.get("HTTP_REFERER", "")
        if origin and website.domain:
            from urllib.parse import urlparse
            origin_host = urlparse(origin).netloc.lower().removeprefix("www.")
            site_host = website.domain.lower().removeprefix("www.").removeprefix("https://").removeprefix("http://").split("/")[0]
            if origin_host and site_host and origin_host != site_host:
                return Response(status=status.HTTP_403_FORBIDDEN)

        if is_important_form_error(data["message"]):
            FormSubmissionError.objects.create(
                website=website,
                source=data["source"][:100],
                form_id=data["form_id"][:200],
                page_url=sanitize_page_url(data["page_url"]),
                message=sanitize_error_message(data["message"]),
            )
        return Response(status=status.HTTP_202_ACCEPTED)


class WebsiteScriptListView(generics.ListAPIView):
    """GET /api/v1/websites/<website_pk>/scripts/ — active scripts for a site."""

    serializer_class = ScriptSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def get_queryset(self):
        team = self.request.user.active_team
        if team is None:
            return Script.objects.none()

        scripts = Script.objects.filter(
            website__team=team,
            website_id=self.kwargs["website_pk"],
        ).active()

        category = self.request.query_params.get("category")
        provider = self.request.query_params.get("provider")
        scope = self.request.query_params.get("scope")
        location = self.request.query_params.get("location")

        if category:
            scripts = scripts.filter(category=category)
        if provider:
            scripts = scripts.filter(provider__icontains=provider)
        if scope:
            scripts = scripts.filter(scope=scope)
        if location:
            scripts = scripts.filter(location=location)

        return scripts.select_related("website")


class WebsiteChangeListView(generics.ListAPIView):
    """GET /api/v1/websites/<website_pk>/changes/ — change log for a site."""

    serializer_class = ScriptChangeSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def get_queryset(self):
        team = self.request.user.active_team
        if team is None:
            return ScriptChange.objects.none()

        qs = ScriptChange.objects.filter(
            website__team=team,
            website_id=self.kwargs["website_pk"],
        ).select_related("script", "acknowledged_by")

        severity = self.request.query_params.get("severity")
        change_type = self.request.query_params.get("change_type")
        unacknowledged = self.request.query_params.get("unacknowledged")

        if severity:
            qs = qs.filter(severity=severity)
        if change_type:
            qs = qs.filter(change_type=change_type)
        if unacknowledged == "true":
            qs = qs.filter(acknowledged_at__isnull=True)

        return qs


class AcknowledgeChangeView(APIView):
    """POST /api/v1/changes/<pk>/acknowledge/ — mark a change as reviewed."""

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def post(self, request, pk):
        team = request.user.active_team
        try:
            change = ScriptChange.objects.get(
                pk=pk, website__team=team
            )
        except ScriptChange.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        if change.acknowledged_at:
            return Response(
                {"detail": "Already acknowledged."},
                status=status.HTTP_200_OK,
            )

        change.acknowledged_at = timezone.now()
        change.acknowledged_by = request.user
        change.save(update_fields=["acknowledged_at", "acknowledged_by"])

        AuditService.log_request(
            request, ActivityLog.Action.WEBSITE_CHANGE_ACKNOWLEDGED,
            description=f"Acknowledged script change on '{change.website.domain}'",
            resource_type="script_change", resource_id=change.pk,
        )

        # Recalculate website status immediately so the dashboard reflects
        # the acknowledgement without waiting for the next ingest.
        from apps.scripts.tasks import _update_website_status
        _update_website_status(change.website)

        change.website.recalculate_health_score()

        return Response(ScriptChangeSerializer(change).data)


class ScriptReviewView(APIView):
    """PATCH /api/v1/websites/<website_pk>/scripts/<pk>/review/ — update review_status."""

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    _ALLOWED = {s.value for s in Script.ReviewStatus}

    def patch(self, request, website_pk, pk):
        team = request.user.active_team
        review_status = request.data.get("review_status")
        if review_status not in self._ALLOWED:
            return Response(
                {"detail": f"review_status must be one of {sorted(self._ALLOWED)}."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            script = Script.objects.get(pk=pk, website_id=website_pk, website__team=team)
        except Script.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        script.review_status = review_status
        script.save(update_fields=["review_status"])
        AuditService.log_request(
            request, ActivityLog.Action.SCRIPT_REVIEWED,
            description=f"Marked script '{script.src_url}' as {review_status}",
            resource_type="script", resource_id=script.pk,
            metadata={"review_status": review_status},
        )
        return Response(ScriptSerializer(script).data)


class BulkScriptReviewView(APIView):
    """POST /api/v1/websites/<website_pk>/scripts/bulk-review/

    Body: {"script_ids": [...], "review_status": "approved|blocked|ignored|pending"}
    Updates review_status on all listed scripts that belong to the caller's team.
    Returns {"updated": <count>}.
    """

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    _ALLOWED = {s.value for s in Script.ReviewStatus}

    def post(self, request, website_pk):
        team = request.user.active_team
        review_status = request.data.get("review_status")
        script_ids = request.data.get("script_ids") or []

        if review_status not in self._ALLOWED:
            return Response(
                {"detail": f"review_status must be one of {sorted(self._ALLOWED)}."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not isinstance(script_ids, list) or not script_ids:
            return Response(
                {"detail": "script_ids must be a non-empty list."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        updated = Script.objects.filter(
            pk__in=script_ids,
            website_id=website_pk,
            website__team=team,
        ).update(review_status=review_status)

        if updated:
            AuditService.log_request(
                request, ActivityLog.Action.SCRIPT_REVIEWED,
                description=f"Marked {updated} script(s) as {review_status}",
                resource_type="website", resource_id=website_pk,
                metadata={"review_status": review_status, "count": updated},
            )
        return Response({"updated": updated})


class ScriptTimelineView(generics.ListAPIView):
    """GET /api/v1/websites/<website_pk>/scripts/<pk>/timeline/

    The change history for a single script, newest first.
    """

    serializer_class = ScriptChangeSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def get_queryset(self):
        team = self.request.user.active_team
        if team is None:
            return ScriptChange.objects.none()
        return ScriptChange.objects.filter(
            website__team=team,
            website_id=self.kwargs["website_pk"],
            script_id=self.kwargs["pk"],
        ).select_related("script", "acknowledged_by")


class WebsiteFormErrorListView(generics.ListAPIView):
    """GET /api/v1/websites/<website_pk>/form-errors/ — failed submissions."""

    serializer_class = FormSubmissionErrorSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def get_queryset(self):
        team = self.request.user.active_team
        if team is None:
            return FormSubmissionError.objects.none()
        return FormSubmissionError.objects.filter(
            website__team=team,
            website_id=self.kwargs["website_pk"],
        )


class WebsiteFormListView(generics.ListAPIView):
    """GET /api/v1/websites/<website_pk>/forms/ — detected forms for a site."""

    serializer_class = DetectedFormSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def get_queryset(self):
        team = self.request.user.active_team
        if team is None:
            return DetectedForm.objects.none()
        return DetectedForm.objects.filter(
            website__team=team,
            website_id=self.kwargs["website_pk"],
        ).order_by("page_url", "form_action")


class ExtensionLookupView(APIView):
    """GET /api/extension/lookup/?domain=example.com

    Public endpoint for the browser extension.  No authentication required.
    Returns a sanitised summary — full src URLs are deliberately omitted so
    this endpoint cannot be used to enumerate a team's private script inventory.
    """

    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = [ExtensionThrottle]

    # Maximum scripts returned in the truncated list
    _SCRIPT_LIMIT = 10

    def get(self, request):
        domain = request.query_params.get("domain", "").strip().lower()
        if not domain:
            return Response(
                {"detail": "domain query parameter is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Strip scheme/path if the extension sends full URLs by mistake
        domain = domain.replace("https://", "").replace("http://", "").split("/")[0]

        website = (
            Website.objects.filter(domain__iexact=domain)
            .only("id", "domain", "status")
            .first()
        )

        if website is None:
            return Response(
                {
                    "registered": False,
                    "domain": domain,
                    "script_count": 0,
                    "has_unknown": False,
                    "scripts": [],
                }
            )

        active_scripts = (
            Script.objects.filter(website=website, is_active=True)
            .only("provider", "category", "src_domain", "is_inline")
            .order_by("provider", "src_domain")
        )

        script_count = active_scripts.count()
        has_unknown = active_scripts.filter(provider="unknown").exists()

        truncated = [
            {
                "provider": s.provider,
                "category": s.category,
                "src_domain": s.src_domain,
                "is_inline": s.is_inline,
            }
            for s in active_scripts[: self._SCRIPT_LIMIT]
        ]

        return Response(
            {
                "registered": True,
                "domain": domain,
                "script_count": script_count,
                "has_unknown": has_unknown,
                "scripts": truncated,
            }
        )
