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
        response["Cache-Control"] = "public, max-age=3600"
        response["Access-Control-Allow-Origin"] = "*"
        return response

from apps.common.mixins import TeamScopedMixin
from apps.common.permissions import IsTeamMember
from apps.scripts.models import Script, ScriptChange
from apps.scripts.serializers import (
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
    rate = "10000/day"
    scope = "ingest"


class IngestView(APIView):
    """POST /api/ingest/ — universal snippet endpoint.

    Validates the site_id and immediately returns 202; all heavy processing
    runs asynchronously in Celery so this response stays under 50ms.
    No JWT auth required — site_id acts as the website identifier.
    """

    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = [IngestThrottle]

    def post(self, request):
        serializer = IngestPayloadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # Reject unknown site_ids fast — before queuing
        if not Website.objects.filter(site_id=data["site_id"]).exists():
            return Response(status=status.HTTP_404_NOT_FOUND)

        process_ingest_payload.delay(
            site_id=data["site_id"],
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
                "user_agent": data["user_agent"],
                "snippet_version": data["snippet_version"],
            },
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
        return Response(ScriptSerializer(script).data)


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
