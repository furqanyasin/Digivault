from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import IsTeamMember
from apps.performance.models import CruxReport, PerformanceReport
from apps.performance.serializers import CruxReportSerializer, PerformanceReportSerializer
from apps.websites.models import Website


class WebsitePerformanceListView(generics.ListAPIView):
    """GET /api/v1/websites/<website_pk>/performance/?strategy=mobile&limit=30"""

    serializer_class = PerformanceReportSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def get_queryset(self):
        team = self.request.user.active_team
        if team is None:
            return PerformanceReport.objects.none()
        strategy = self.request.query_params.get("strategy", "mobile")
        limit = min(int(self.request.query_params.get("limit", 30)), 90)
        return (
            PerformanceReport.objects.filter(
                website__team=team,
                website_id=self.kwargs["website_pk"],
                strategy=strategy,
            )
            .order_by("-checked_at")[:limit]
        )


class WebsitePerformanceRunView(APIView):
    """POST /api/v1/websites/<website_pk>/performance/run/

    Runs PageSpeed synchronously and returns the report immediately.
    """

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def post(self, request, website_pk):
        team = request.user.active_team
        try:
            website = Website.objects.get(pk=website_pk, team=team)
        except Website.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        strategy = request.data.get("strategy", "mobile")
        if strategy not in ("mobile", "desktop"):
            strategy = "mobile"

        url = website.domain
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"

        from apps.performance.services import PageSpeedService
        result = PageSpeedService.check(url, strategy=strategy)

        report = PerformanceReport.objects.create(
            website=website,
            url=url,
            strategy=strategy,
            performance_score=result.performance_score,
            fcp_ms=result.fcp_ms,
            lcp_ms=result.lcp_ms,
            cls_score=result.cls_score,
            tbt_ms=result.tbt_ms,
            ttfb_ms=result.ttfb_ms,
            si_ms=result.si_ms,
            tti_ms=result.tti_ms,
            inp_ms=result.inp_ms,
            fcp_rating=result.fcp_rating,
            lcp_rating=result.lcp_rating,
            cls_rating=result.cls_rating,
            tbt_rating=result.tbt_rating,
            error=result.error,
        )

        if result.error:
            return Response(
                {"detail": result.error, "report": PerformanceReportSerializer(report).data},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        # Fire an in-app alert if this run is a significant regression.
        from apps.performance.trends import alert_on_regression
        alert_on_regression(website, strategy)

        return Response(PerformanceReportSerializer(report).data, status=status.HTTP_201_CREATED)


class WebsitePerformanceTrendView(APIView):
    """GET /api/v1/websites/<website_pk>/performance/trends/?strategy=mobile&weeks=8"""

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def get(self, request, website_pk):
        team = request.user.active_team
        website = Website.objects.filter(pk=website_pk, team=team).first()
        if website is None:
            return Response(status=status.HTTP_404_NOT_FOUND)

        from apps.performance.trends import detect_regression, weekly_trend

        strategy = request.query_params.get("strategy", "mobile")
        if strategy not in ("mobile", "desktop"):
            strategy = "mobile"
        weeks = min(int(request.query_params.get("weeks", 8)), 26)

        return Response({
            "strategy": strategy,
            "weekly": weekly_trend(website, strategy, weeks),
            "regression": detect_regression(website, strategy),
        })


class WebsiteCruxListView(generics.ListAPIView):
    """GET /api/v1/websites/<website_pk>/crux/ — latest CrUX reports."""

    serializer_class = CruxReportSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def get_queryset(self):
        team = self.request.user.active_team
        if team is None:
            return CruxReport.objects.none()
        return CruxReport.objects.filter(
            website__team=team,
            website_id=self.kwargs["website_pk"],
        ).order_by("-fetched_at")[:12]


class WebsiteCruxRunView(APIView):
    """POST /api/v1/websites/<website_pk>/crux/run/ — fetch fresh CrUX data."""

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def post(self, request, website_pk):
        team = request.user.active_team
        try:
            website = Website.objects.get(pk=website_pk, team=team)
        except Website.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        url = website.domain
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"

        from apps.performance.services import CruxService
        result = CruxService.fetch(url)

        report = CruxReport.objects.create(
            website=website,
            origin=result.origin,
            lcp_p75_ms=result.lcp_p75_ms,
            fcp_p75_ms=result.fcp_p75_ms,
            cls_p75=result.cls_p75,
            inp_p75_ms=result.inp_p75_ms,
            ttfb_p75_ms=result.ttfb_p75_ms,
            fid_p75_ms=result.fid_p75_ms,
            lcp_good=result.lcp_good,
            lcp_ni=result.lcp_ni,
            lcp_poor=result.lcp_poor,
            fcp_good=result.fcp_good,
            fcp_ni=result.fcp_ni,
            fcp_poor=result.fcp_poor,
            cls_good=result.cls_good,
            cls_ni=result.cls_ni,
            cls_poor=result.cls_poor,
            inp_good=result.inp_good,
            inp_ni=result.inp_ni,
            inp_poor=result.inp_poor,
            error=result.error,
        )

        if result.error:
            return Response(
                {"detail": result.error, "report": CruxReportSerializer(report).data},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        return Response(CruxReportSerializer(report).data, status=status.HTTP_201_CREATED)
