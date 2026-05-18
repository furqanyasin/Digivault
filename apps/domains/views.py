from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import IsTeamMember
from apps.domains.models import DomainAlert, DomainInfo
from apps.domains.serializers import DomainInfoSerializer
from apps.domains.services import (
    DOMAIN_ALERT_THRESHOLDS,
    SSL_ALERT_THRESHOLDS,
    DomainIntelligenceService,
)
from apps.websites.models import Website


def _persist_domain_check(website: Website) -> DomainInfo:
    """Run WHOIS+SSL synchronously and persist the result. Returns the DomainInfo."""
    result = DomainIntelligenceService.check(website.domain)
    domain_info, _ = DomainInfo.objects.update_or_create(
        website=website,
        defaults={
            "registrar": result.registrar,
            "registered_at": result.registered_at,
            "expires_at": result.expires_at,
            "nameservers": result.nameservers,
            "whois_privacy": result.whois_privacy,
            "hosting_provider": result.hosting_provider,
            "hosting_ip": result.hosting_ip or None,
            "uses_cloudflare": result.uses_cloudflare,
            "ssl_issuer": result.ssl_issuer,
            "ssl_expires_at": result.ssl_expires_at,
            "ssl_auto_renew": result.ssl_auto_renew,
            "last_checked_at": timezone.now(),
        },
    )
    _create_expiry_alerts(domain_info)
    return domain_info


def _create_expiry_alerts(domain_info: DomainInfo) -> None:
    now = timezone.now()
    for alert_type, expires_at, thresholds in (
        (DomainAlert.AlertType.DOMAIN, domain_info.expires_at, DOMAIN_ALERT_THRESHOLDS),
        (DomainAlert.AlertType.SSL, domain_info.ssl_expires_at, SSL_ALERT_THRESHOLDS),
    ):
        if not expires_at:
            continue
        days_left = max(0, (expires_at - now).days)
        for threshold in thresholds:
            if days_left <= threshold:
                DomainAlert.objects.get_or_create(
                    domain_info=domain_info,
                    alert_type=alert_type,
                    days_until_expiry=threshold,
                    defaults={"sent": False},
                )


class DomainInfoView(APIView):
    """GET /api/v1/websites/<website_pk>/domain/
    POST /api/v1/websites/<website_pk>/domain/refresh/
    """

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def _get_website(self, request, website_pk):
        team = request.user.active_team
        try:
            return Website.objects.get(pk=website_pk, team=team)
        except Website.DoesNotExist:
            return None

    def get(self, request, website_pk):
        website = self._get_website(request, website_pk)
        if not website:
            return Response(status=status.HTTP_404_NOT_FOUND)
        try:
            info = website.domain_info
        except DomainInfo.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(DomainInfoSerializer(info).data)

    def post(self, request, website_pk):
        """Run WHOIS + SSL check synchronously and return the updated data.

        Runs in-process (no Celery required) so the caller gets the result
        immediately in the response. The Celery task still exists for the
        scheduled daily run.
        """
        website = self._get_website(request, website_pk)
        if not website:
            return Response(status=status.HTTP_404_NOT_FOUND)
        try:
            info = _persist_domain_check(website)
        except Exception as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        return Response(DomainInfoSerializer(info).data, status=status.HTTP_200_OK)
