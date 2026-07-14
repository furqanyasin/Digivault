from django.http import FileResponse
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.models import ActivityLog
from apps.audit.services import AuditService
from apps.common.permissions import IsTeamMember
from apps.reports.models import Report
from apps.reports.serializers import ReportGenerateSerializer, ReportSerializer
from apps.reports.services import generate_report
from apps.websites.models import Website


class ReportListCreateView(generics.ListAPIView):
    """GET /api/v1/reports/ — team's reports (optionally ?website_id=)."""

    serializer_class = ReportSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def get_queryset(self):
        team = self.request.user.active_team
        if team is None:
            return Report.objects.none()
        qs = Report.objects.filter(team=team).select_related("website")
        website_id = self.request.query_params.get("website_id")
        if website_id:
            qs = qs.filter(website_id=website_id)
        return qs


class ReportGenerateView(APIView):
    """POST /api/v1/reports/generate/ — generate a report on demand (synchronous)."""

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def post(self, request):
        serializer = ReportGenerateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        team = request.user.active_team
        website = Website.objects.filter(pk=data["website_id"], team=team).first()
        if website is None:
            return Response(status=status.HTTP_404_NOT_FOUND)

        report = generate_report(
            website,
            data["period_start"],
            data["period_end"],
            report_format=data["report_format"],
            sections=data.get("sections") or None,
        )
        code = (
            status.HTTP_201_CREATED
            if report.status == Report.Status.DONE
            else status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        if report.status == Report.Status.DONE:
            AuditService.log_request(
                request, ActivityLog.Action.REPORT_GENERATED,
                description=f"Generated {report.report_format.upper()} report for '{website.name or website.domain}'",
                resource_type="report", resource_id=report.pk,
            )
        return Response(ReportSerializer(report).data, status=code)


class ReportDeleteView(generics.DestroyAPIView):
    """DELETE /api/v1/reports/<pk>/ — delete a report and its stored file."""

    serializer_class = ReportSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def get_queryset(self):
        team = self.request.user.active_team
        if team is None:
            return Report.objects.none()
        return Report.objects.filter(team=team)

    def perform_destroy(self, instance):
        label = instance.website.name or instance.website.domain
        AuditService.log_request(
            self.request, ActivityLog.Action.REPORT_DELETED,
            description=f"Deleted {instance.report_format.upper()} report for '{label}'",
            resource_type="report", resource_id=instance.pk,
        )
        if instance.file:
            instance.file.delete(save=False)
        instance.delete()


class ReportDownloadView(APIView):
    """GET /api/v1/reports/<pk>/download/ — stream the generated file."""

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def get(self, request, pk):
        team = request.user.active_team
        report = Report.objects.filter(pk=pk, team=team).first()
        if report is None or report.status != Report.Status.DONE or not report.file:
            return Response(status=status.HTTP_404_NOT_FOUND)

        content_type = (
            "application/pdf"
            if report.report_format == Report.Format.PDF
            else "text/csv"
        )
        return FileResponse(
            report.file.open("rb"),
            content_type=content_type,
            as_attachment=True,
            filename=report.file.name.split("/")[-1],
        )
