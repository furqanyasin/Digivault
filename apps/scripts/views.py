import logging
import os

from django.http import HttpResponse
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from apps.audit.models import ActivityLog
from apps.audit.services import AuditService
from apps.common.mixins import TeamScopedMixin
from apps.common.permissions import IsTeamMember
from apps.scripts.js_errors import (
    browser_label,
    fingerprint as js_fingerprint,
    is_reportable,
)
from apps.scripts.form_errors import (
    is_important_form_error,
    sanitize_error_message,
    sanitize_page_url,
)
from apps.scripts.models import DetectedForm, FormSubmissionError, JsError, Script, ScriptChange
from apps.scripts.normalize import normalize_page_url
from apps.scripts.serializers import (
    DetectedFormSerializer,
    FormErrorIngestSerializer,
    FormSubmissionErrorSerializer,
    FormSubmissionIngestSerializer,
    IngestPayloadSerializer,
    JsErrorIngestSerializer,
    JsErrorSerializer,
    ScriptChangeSerializer,
    ScriptSerializer,
)
from apps.scripts.tasks import (
    _upsert_form,
    deliver_form_error_alert,
    process_ingest_payload,
)
from apps.websites.models import Website

logger = logging.getLogger(__name__)


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
                        "recipient_email": f["recipient_email"],
                        "fields": f["fields"],
                    }
                    for f in data.get("forms", [])
                ],
                "user_agent": data["user_agent"],
                "snippet_version": data["snippet_version"],
            },
        )
        return Response(status=status.HTTP_202_ACCEPTED)


class JsErrorIngestView(APIView):
    """POST /api/ingest/js-errors/ — uncaught JavaScript errors from the snippet.

    Same trust model as ingest: site_id identifies the website and the request
    origin must match its registered domain. Noise and browser-extension errors
    are acknowledged (202) but never stored, so probing reveals nothing.

    Deduplicated on (website, fingerprint) with a hit counter — a broken script
    on a busy page throws the same error thousands of times, and one row per
    occurrence would bury everything else.
    """

    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = [IngestThrottle]

    def post(self, request):
        serializer = JsErrorIngestSerializer(data=request.data)
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
            site_host = (
                website.domain.lower().removeprefix("www.")
                .removeprefix("https://").removeprefix("http://").split("/")[0]
            )
            if origin_host and site_host and origin_host != site_host:
                return Response(status=status.HTTP_403_FORBIDDEN)

        message = data["message"]
        source_url = data.get("source_url", "")
        if not is_reportable(message, source_url):
            return Response(status=status.HTTP_202_ACCEPTED)

        fp = js_fingerprint(message, source_url, data.get("line_no"))
        existing = JsError.objects.filter(website=website, fingerprint=fp).first()
        if existing:
            # F() so concurrent hits from the same page don't lose counts.
            from django.db.models import F

            JsError.objects.filter(pk=existing.pk).update(
                hits=F("hits") + 1,
                last_seen_at=timezone.now(),
                # A recurrence reopens it: a "resolved" error still firing is not
                # resolved.
                is_resolved=False,
            )
        else:
            JsError.objects.create(
                website=website,
                fingerprint=fp,
                message=sanitize_error_message(message),
                source_url=source_url[:2048],
                line_no=data.get("line_no"),
                col_no=data.get("col_no"),
                stack=(data.get("stack") or "")[:4000],
                page_url=sanitize_page_url(data["page_url"]),
                browser=browser_label(request.META.get("HTTP_USER_AGENT", "")),
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
            error = FormSubmissionError.objects.create(
                website=website,
                source=data["source"][:100],
                form_id=data["form_id"][:200],
                page_url=sanitize_page_url(data["page_url"]),
                message=sanitize_error_message(data["message"]),
            )
            # Best-effort: the row is the record of truth. A broker outage or a
            # failing channel must not turn a captured error into a 500 that the
            # snippet retries.
            try:
                deliver_form_error_alert.delay(str(error.pk))
            except Exception:
                logger.exception("Could not queue alert for form error %s", error.pk)
        return Response(status=status.HTTP_202_ACCEPTED)


class FormSubmissionIngestView(APIView):
    """POST /api/ingest/form-submission/ — counts a native form submission.

    The snippet fires this on submit. We recompute the form's fingerprint the
    same way ingest does and increment the matching DetectedForm's counter.
    Same trust model as the other ingest endpoints (site_id + origin check).
    """

    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = [IngestThrottle]

    def post(self, request):
        serializer = FormSubmissionIngestSerializer(data=request.data)
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

        from django.db.models import F

        fingerprint = DetectedForm.compute_fingerprint(data["form"])
        # DetectedForm.page_url holds the *normalized* page identity (see
        # process_ingest_payload), while the snippet reports
        # window.location.href verbatim — carrying www., UTM params, a fragment
        # and a trailing slash. Matching those raw against each other silently
        # matched zero rows, so live sites sat at 0 submissions forever.
        page_url = normalize_page_url(data["page_url"])
        updated = DetectedForm.objects.filter(
            website=website,
            page_url=page_url,
            fingerprint=fingerprint,
        ).update(
            submission_count=F("submission_count") + 1,
            last_submission_at=timezone.now(),
        )
        if not updated:
            # A form can first appear after the page's last collectForms() —
            # a popup opened past the snippet's 30s observer window is the
            # common case — so its descriptor was never ingested. This used to
            # drop the submit, losing a real conversion and leaving the form
            # itself invisible. Recording it is not "phantom" data: the
            # descriptor arrives through the same serializer, from the same
            # collector, behind the same site_id + origin gate as
            # POST /api/ingest/, which could already create the row.
            _record_late_form_submission(website, page_url, data["form"], fingerprint)
        return Response({"counted": True}, status=status.HTTP_202_ACCEPTED)


def _record_late_form_submission(
    website, page_url: str, form_data: dict, fingerprint: str
) -> None:
    """Store a form first seen at submit time, with that submit counted.

    Goes through the ingest upsert so the row is byte-identical to the one a
    later ingest of the same page would write — otherwise the next pageview
    would create a second row and strand the count on the first. Upsert then
    increment (rather than create with count=1) also keeps a concurrent ingest
    of the same descriptor from losing the submit.
    """
    from django.db.models import F

    _upsert_form(website, page_url, form_data)
    DetectedForm.objects.filter(
        website=website, page_url=page_url, fingerprint=fingerprint
    ).update(
        submission_count=F("submission_count") + 1,
        last_submission_at=timezone.now(),
    )


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


class TeamChangeListView(generics.ListAPIView):
    """GET /api/v1/changes/ — every change across the team, newest first.

    The alerts view previously fetched /websites/<id>/changes/ once per site,
    which was one HTTP round trip per website (60+ for a real agency). This
    collapses that into a single query.
    """

    serializer_class = ScriptChangeSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def get_queryset(self):
        team = self.request.user.active_team
        if team is None:
            return ScriptChange.objects.none()

        qs = ScriptChange.objects.filter(website__team=team).select_related(
            "script", "acknowledged_by", "website"
        )

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
            metadata={"website_id": str(change.website_id)},
        )

        # Recalculate immediately so the dashboard reflects the acknowledgement
        # without waiting for the next ingest. This writes status too.
        change.website.recalculate_health_score()

        return Response(ScriptChangeSerializer(change).data)


class BulkAcknowledgeChangesView(APIView):
    """POST /api/v1/changes/bulk-acknowledge/ — body {"change_ids": [...]}.

    Acknowledges every listed change, then recalculates each affected website's
    status + health score ONCE. Doing it per-website-once avoids the race that
    happens when the UI fires many single-acknowledge requests in parallel — none
    of which sees the others' uncommitted acks, so the site stays 'critical'.
    """

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def post(self, request):
        team = request.user.active_team
        change_ids = request.data.get("change_ids") or []
        if not isinstance(change_ids, list) or not change_ids:
            return Response({"detail": "change_ids must be a non-empty list."}, status=status.HTTP_400_BAD_REQUEST)

        qs = ScriptChange.objects.filter(
            pk__in=change_ids, website__team=team, acknowledged_at__isnull=True
        )
        # Counted before the update, while the queryset still means "not yet
        # acknowledged" — re-querying afterwards would also pick up changes that
        # someone else had already acknowledged.
        from collections import Counter

        counts = Counter(qs.values_list("website_id", flat=True))
        website_ids = list(counts)
        updated = qs.update(acknowledged_at=timezone.now(), acknowledged_by=request.user)

        from apps.websites.models import Website
        for website in Website.objects.filter(pk__in=website_ids):
            website.recalculate_health_score()

        if updated:
            # One entry per website rather than one for the batch: a bulk ack can
            # span sites, and a single row could name only one of them — leaving
            # the Activity Log's Website column empty and the site's own activity
            # tab missing the acknowledgement entirely.
            for website in Website.objects.filter(pk__in=counts):
                AuditService.log_request(
                    request, ActivityLog.Action.WEBSITE_CHANGE_ACKNOWLEDGED,
                    description=(
                        f"Acknowledged {counts[website.pk]} script change(s) on "
                        f"'{website.name or website.domain}'"
                    ),
                    resource_type="script_change",
                    metadata={"website_id": str(website.pk)},
                )
        return Response({"updated": updated})


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
            metadata={"review_status": review_status, "website_id": str(website_pk)},
        )

        # Triaging a script (approve/block/ignore) resolves the open changes that
        # flagged it — most importantly the HIGH "Unknown script detected" change
        # that drives the site to 'critical'. Acknowledge them and recompute so
        # the dashboard heals immediately instead of staying stuck at critical.
        if review_status != Script.ReviewStatus.PENDING:
            self._resolve_open_changes(script, request.user)

        return Response(ScriptSerializer(script).data)

    @staticmethod
    def _resolve_open_changes(script, user) -> None:
        script.changes.filter(acknowledged_at__isnull=True).update(
            acknowledged_at=timezone.now(), acknowledged_by=user
        )
        script.website.recalculate_health_score()


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

        scripts = Script.objects.filter(
            pk__in=script_ids,
            website_id=website_pk,
            website__team=team,
        )
        updated = scripts.update(review_status=review_status)

        # Resolve the open changes flagged against these scripts, then recompute
        # the website's status + health ONCE so a bulk approve heals 'critical'.
        if updated and review_status != Script.ReviewStatus.PENDING:
            ScriptChange.objects.filter(
                script__in=list(scripts.values_list("pk", flat=True)),
                acknowledged_at__isnull=True,
            ).update(acknowledged_at=timezone.now(), acknowledged_by=request.user)

            from apps.websites.models import Website
            website = Website.objects.filter(pk=website_pk).first()
            if website:
                website.recalculate_health_score()

        if updated:
            AuditService.log_request(
                request, ActivityLog.Action.SCRIPT_REVIEWED,
                description=f"Marked {updated} script(s) as {review_status}",
                resource_type="website", resource_id=website_pk,
                metadata={"review_status": review_status, "count": updated,
                          "website_id": str(website_pk)},
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


class TeamFormListView(generics.ListAPIView):
    """GET /api/v1/forms/ — detected forms across the whole team.

    Lets the dashboard summarise forms in one request instead of one per site.
    """

    serializer_class = DetectedFormSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def get_queryset(self):
        team = self.request.user.active_team
        if team is None:
            return DetectedForm.objects.none()
        return DetectedForm.objects.filter(website__team=team).order_by(
            "page_url", "form_action"
        )


class TeamFormErrorListView(generics.ListAPIView):
    """GET /api/v1/form-errors/ — failed submissions across the whole team."""

    serializer_class = FormSubmissionErrorSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def get_queryset(self):
        team = self.request.user.active_team
        if team is None:
            return FormSubmissionError.objects.none()
        return FormSubmissionError.objects.filter(website__team=team)


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


class WebsiteJsErrorListView(TeamScopedMixin, generics.ListAPIView):
    """GET /api/v1/websites/<website_pk>/js-errors/ — this site's JS errors,
    most recently seen first."""

    serializer_class = JsErrorSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def get_queryset(self):
        team = self.request.user.active_team
        if team is None:
            return JsError.objects.none()
        return JsError.objects.filter(
            website_id=self.kwargs["website_pk"], website__team=team
        )
