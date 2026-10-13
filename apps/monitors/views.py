import json
import urllib.request

from django.conf import settings
from django.core.mail import send_mail
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.models import ActivityLog
from apps.audit.services import AuditService, site_meta
from apps.common.mixins import TeamScopedMixin
from apps.common.permissions import IsTeamMember, RolePermission, TeamRolePermission
from apps.integrations.clickup import ClickUpClient
from apps.monitors.models import Monitor, MonitorCheck, MonitorNotificationRule, NotificationChannel
from apps.monitors.serializers import (
    MonitorCheckSerializer,
    MonitorNotificationRuleSerializer,
    MonitorSerializer,
    NotificationChannelSerializer,
)


class MonitorListCreateView(TeamScopedMixin, generics.ListCreateAPIView):
    """GET /api/v1/monitors/  POST /api/v1/monitors/"""

    queryset = Monitor.objects.all()
    serializer_class = MonitorSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeamMember, TeamRolePermission]

    def get_queryset(self):
        qs = super().get_queryset()
        website_id = self.request.query_params.get("website", "").strip()
        if website_id:
            qs = qs.filter(website_id=website_id)
        return qs

    def perform_create(self, serializer):
        monitor = serializer.save(team=self.request.user.active_team)
        AuditService.log_request(
            self.request, ActivityLog.Action.MONITOR_CREATED,
            description=f"Created {monitor.monitor_type} monitor '{monitor.name}'",
            resource_type="monitor", resource_id=monitor.pk,
            metadata=site_meta(monitor),
        )


class BlockedMonitorSummaryView(APIView):
    """GET /api/v1/monitors/blocked-summary/ — every blocked site, grouped by
    the firewall blocking it, with one ready-to-send fix per firewall.

    The fix is per vendor, not per site: one SiteGround ticket can name every
    domain on the account, and one Cloudflare rule per account covers all its
    zones. Handing out a separate instruction per monitor made "fix all of
    them" twenty copy-pastes.
    """

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def get(self, request):
        from collections import defaultdict
        from urllib.parse import urlsplit

        from apps.common import outbound
        from apps.monitors import second_opinion
        from apps.monitors.serializers import block_vendor

        team = request.user.active_team
        ips = outbound.egress_ips()
        ip_text = ", ".join(ips) if ips else f"(our monitoring IP — see {settings.BOT_INFO_URL})"
        groups: dict[str, list] = defaultdict(list)
        monitors = Monitor.objects.filter(
            team=team, status=Monitor.Status.BLOCKED, is_active=True,
        ).select_related("website")
        for monitor in monitors:
            latest = (
                monitor.checks.filter(status=MonitorCheck.Status.BLOCKED)
                .order_by("-checked_at").first()
            )
            vendor = block_vendor(latest.error_message if latest else "")
            website = monitor.website
            groups[vendor].append({
                "monitor_id": str(monitor.pk),
                "name": monitor.name,
                "url": monitor.url,
                "domain": (urlsplit(monitor.url).hostname or monitor.url).removeprefix("www."),
                "since": latest.checked_at if latest else None,
                # Which inside-out evidence the site could vouch for itself
                # with (monitors.evidence). Still blocked with a heartbeat
                # means WordPress has gone quiet — worth a look, not a ticket.
                "has_heartbeat": bool(website and website.wp_connect_loopback_at),
                "has_snippet": bool(website and website.snippet_last_seen_at),
            })

        result = []
        for vendor, sites in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            domains = sorted({s["domain"] for s in sites})
            result.append({
                "vendor": vendor,
                "count": len(sites),
                "sites": sorted(sites, key=lambda s: s["domain"]),
                "fix": _vendor_fix(vendor, ips, ip_text, domains),
            })
        return Response({
            "egress_ips": ips,
            "user_agent": outbound.USER_AGENT,
            # Whether Google really is checking these for us. The panel used to
            # promise it unconditionally, so a deployment without a PageSpeed
            # key read "Google checks them" over sites nobody was checking.
            "second_opinion_enabled": second_opinion.enabled(),
            "groups": result,
        })


def _vendor_fix(vendor: str, ips: list[str], ip_text: str, domains: list[str]) -> dict:
    """What to do about one firewall, for every site it blocks at once."""
    from apps.common import outbound

    domain_lines = "\n".join(f"- {d}" for d in domains)
    if vendor == "SiteGround":
        return {
            "how": "SiteGround challenges our monitoring IP itself, so no setting on our side or yours clears it. No ticket needed for a WordPress site: paste the latest WP Connect snippet and the site reports its own uptime every 5 minutes, which SiteGround cannot block; sites with the tracking snippet are also vouched for by their real visitors. For anything else, this one ticket (Site Tools → Help → Contact support) covers every site below.",
            "copy_label": "Copy support ticket",
            "text": (
                "Hello SiteGround support,\n\n"
                "Your bot protection is blocking our uptime monitor (it receives the "
                "HTTP 202 challenge page) on the sites below. Please whitelist our "
                f"monitoring IP {ip_text} for these domains:\n\n{domain_lines}\n\n"
                f"Our requests identify themselves as: {outbound.USER_AGENT}\n"
                "It sends one HEAD/GET request to each homepage about every 15 "
                "minutes, never logs in, submits forms or crawls.\n\nThank you."
            ),
        }
    if vendor == "Cloudflare":
        ip_rule = f" or (ip.src in {{{' '.join(ips)}}})" if ips else ""
        return {
            "how": "Add this rule once per Cloudflare account (Security → WAF → Custom rules → Create rule), Action: Skip → all remaining custom rules + Bot Fight Mode. It covers every site in the account.",
            "copy_label": "Copy WAF expression",
            "text": f'(http.user_agent contains "Digivault-Monitor"){ip_rule}',
        }
    if vendor == "Wordfence":
        return {
            "how": "On each site: Wordfence → Firewall → Blocking → Whitelisted IP addresses.",
            "copy_label": "Copy IP",
            "text": ip_text,
        }
    if vendor == "Sucuri":
        return {
            "how": "Sucuri dashboard → Security → Access Control → Whitelist IP addresses, for each site below.",
            "copy_label": "Copy IP",
            "text": ip_text,
        }
    return {
        "how": "Ask the host to allowlist our monitor's IP for these sites — a uniform block like this is usually a server firewall (Imunify360, CSF, ModSecurity).",
        "copy_label": "Copy request",
        "text": (
            f"Please allowlist our uptime monitor's IP {ip_text} "
            f"(user agent {outbound.USER_AGENT}) for:\n\n{domain_lines}"
        ),
    }


class MonitorDetailView(TeamScopedMixin, generics.RetrieveUpdateDestroyAPIView):
    """GET/PATCH/DELETE /api/v1/monitors/<pk>/"""

    queryset = Monitor.objects.all()
    serializer_class = MonitorSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeamMember, TeamRolePermission]

    def perform_update(self, serializer):
        monitor = serializer.save()
        AuditService.log_request(
            self.request, ActivityLog.Action.MONITOR_UPDATED,
            description=f"Updated monitor '{monitor.name}'",
            resource_type="monitor", resource_id=monitor.pk,
            metadata=site_meta(monitor),
        )

    def perform_destroy(self, instance):
        AuditService.log_request(
            self.request, ActivityLog.Action.MONITOR_DELETED,
            description=f"Deleted monitor '{instance.name}'",
            resource_type="monitor", resource_id=instance.pk,
            metadata=site_meta(instance),
        )
        instance.delete()


class MonitorCheckListView(generics.ListAPIView):
    """GET /api/v1/monitors/<monitor_pk>/checks/"""

    serializer_class = MonitorCheckSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def get_queryset(self):
        team = self.request.user.active_team
        if team is None:
            return MonitorCheck.objects.none()
        return MonitorCheck.objects.filter(
            monitor__team=team,
            monitor_id=self.kwargs["monitor_pk"],
        ).order_by("-checked_at")[:200]


class UptimeTrendView(APIView):
    """GET /api/v1/monitors/uptime-trend/?days=14
       GET /api/v1/monitors/uptime-trend/?from=2026-07-01&to=2026-07-14

    One team-wide uptime percentage per day, for the dashboard trend charts.
    Aggregated from MonitorCheck rather than the cached uptime_* fields, which
    only hold rolling 24h/7d/30d figures and so cannot draw a curve.

    A day with no checks returns `null`, never 0 or 100: no data means we were
    blind, and inventing either number would draw a cliff or a clean run that
    never happened.

    Blocked checks are excluded from both sides, as in
    `Monitor.recalculate_uptime`. Counting them as "not up" drew the chart at
    78% beside a 97.75% headline on a team with a few firewalled sites.

    Each point also carries the day's `up`/`total`, so the dashboard can pool
    them over the selected window for its headline instead of averaging daily
    percentages (or reading a cached 30-day figure under a 7-day caption).
    """

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    DEFAULT_DAYS = 14
    MAX_DAYS = 90

    def _window(self, request):
        """Resolve (first_day, last_day). An explicit from+to range wins.

        Both bounds are required — half a range is not a range, so a lone
        `from` falls back to the rolling `days` window rather than silently
        inventing an end date.
        """
        from datetime import date, timedelta

        from django.utils import timezone

        raw_from = request.query_params.get("from")
        raw_to = request.query_params.get("to")
        if raw_from and raw_to:
            try:
                start, end = date.fromisoformat(raw_from), date.fromisoformat(raw_to)
            except ValueError:
                start = end = None
            if start and end:
                # A picker can hand the pair back in either order.
                if start > end:
                    start, end = end, start
                # Truncate from the start so the range keeps its end date, which
                # is the one the reader is looking at.
                if (end - start).days + 1 > self.MAX_DAYS:
                    start = end - timedelta(days=self.MAX_DAYS - 1)
                return start, end

        try:
            days = int(request.query_params.get("days", self.DEFAULT_DAYS))
        except (TypeError, ValueError):
            days = self.DEFAULT_DAYS
        days = max(1, min(days, self.MAX_DAYS))
        today = timezone.localdate()
        return today - timedelta(days=days - 1), today

    def get(self, request):
        from datetime import timedelta

        from django.db.models import Count, Q
        from django.db.models.functions import TruncDate

        team = request.user.active_team
        first_day, last_day = self._window(request)
        days = (last_day - first_day).days + 1

        by_day: dict[str, tuple[int, int]] = {}
        if team is not None:
            rows = (
                MonitorCheck.objects.filter(
                    monitor__team=team,
                    checked_at__date__gte=first_day,
                    checked_at__date__lte=last_day,
                )
                .exclude(status=MonitorCheck.Status.BLOCKED)
                .annotate(day=TruncDate("checked_at"))
                .values("day")
                .annotate(
                    total=Count("id"),
                    up=Count("id", filter=Q(status=MonitorCheck.Status.UP)),
                )
                .order_by("day")
            )
            for row in rows:
                if row["total"]:
                    by_day[row["day"].isoformat()] = (row["up"], row["total"])

        points = []
        for offset in range(days):
            day = (first_day + timedelta(days=offset)).isoformat()
            up, total = by_day.get(day, (0, 0))
            points.append({
                "date": day,
                "value": round(up * 100.0 / total, 2) if total else None,
                "up": up,
                "total": total,
            })

        return Response({"days": days, "points": points})


class MonitorPauseView(APIView):
    """POST /api/v1/monitors/<pk>/pause/"""

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def post(self, request, pk):
        team = request.user.active_team
        try:
            monitor = Monitor.objects.get(pk=pk, team=team)
        except Monitor.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        Monitor.objects.filter(pk=pk).update(status=Monitor.Status.PAUSED, is_active=False)
        monitor.refresh_from_db()
        AuditService.log_request(
            request, ActivityLog.Action.MONITOR_PAUSED,
            description=f"Paused monitor '{monitor.name}'",
            resource_type="monitor", resource_id=monitor.pk,
            metadata=site_meta(monitor),
        )
        return Response(MonitorSerializer(monitor).data)


class MonitorResumeView(APIView):
    """POST /api/v1/monitors/<pk>/resume/"""

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def post(self, request, pk):
        team = request.user.active_team
        try:
            monitor = Monitor.objects.get(pk=pk, team=team)
        except Monitor.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        Monitor.objects.filter(pk=pk).update(status=Monitor.Status.PENDING, is_active=True)
        monitor.refresh_from_db()
        AuditService.log_request(
            request, ActivityLog.Action.MONITOR_RESUMED,
            description=f"Resumed monitor '{monitor.name}'",
            resource_type="monitor", resource_id=monitor.pk,
            metadata=site_meta(monitor),
        )
        return Response(MonitorSerializer(monitor).data)


class MonitorCheckNowView(APIView):
    """POST /api/v1/monitors/<pk>/check-now/

    Runs the check synchronously so it works without Celery in development.
    """

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def post(self, request, pk):
        from apps.monitors.checker import run_check
        from apps.monitors.notifications import notify_status_change
        from django.utils import timezone

        team = request.user.active_team
        try:
            monitor = Monitor.objects.get(pk=pk, team=team)
        except Monitor.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        previous_status = monitor.status
        try:
            result = run_check(monitor)
        except Exception as exc:
            result = {"status": "down", "response_time_ms": None, "status_code": None, "error_message": str(exc)[:300]}

        new_status = result["status"]
        MonitorCheck.objects.create(
            monitor=monitor,
            status=new_status,
            response_time_ms=result.get("response_time_ms"),
            status_code=result.get("status_code"),
            error_message=result.get("error_message", ""),
        )
        Monitor.objects.filter(pk=monitor.pk).update(
            status=new_status,
            last_checked_at=timezone.now(),
            last_response_time=result.get("response_time_ms"),
        )
        monitor.refresh_from_db()
        monitor.recalculate_uptime()

        if previous_status != new_status and previous_status != "pending":
            try:
                notify_status_change(monitor, previous_status, new_status)
            except Exception:
                pass

        return Response(MonitorSerializer(monitor).data)


# ------------------------------------------------------------------
# Notification channels
# ------------------------------------------------------------------

class NotificationChannelListCreateView(TeamScopedMixin, generics.ListCreateAPIView):
    """GET /api/v1/notification-channels/  POST /api/v1/notification-channels/"""

    queryset = NotificationChannel.objects.all()
    serializer_class = NotificationChannelSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeamMember, TeamRolePermission]

    def get_queryset(self):
        team = self.request.user.active_team
        if team is None:
            return NotificationChannel.objects.none()
        return NotificationChannel.objects.filter(team=team)

    def perform_create(self, serializer):
        channel = serializer.save(team=self.request.user.active_team)
        AuditService.log_request(
            self.request, ActivityLog.Action.NOTIFICATION_CHANNEL_CREATED,
            description=f"Created {channel.channel_type} notification channel",
            resource_type="notification_channel", resource_id=channel.pk,
        )


class NotificationChannelDetailView(generics.RetrieveUpdateDestroyAPIView):
    """GET/PATCH/DELETE /api/v1/notification-channels/<pk>/"""

    serializer_class = NotificationChannelSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeamMember, TeamRolePermission]

    def get_queryset(self):
        team = self.request.user.active_team
        if team is None:
            return NotificationChannel.objects.none()
        return NotificationChannel.objects.filter(team=team)

    def perform_destroy(self, instance):
        AuditService.log_request(
            self.request, ActivityLog.Action.NOTIFICATION_CHANNEL_DELETED,
            description=f"Deleted {instance.channel_type} notification channel",
            resource_type="notification_channel", resource_id=instance.pk,
        )
        instance.delete()


class NotificationChannelTestView(APIView):
    """POST /api/v1/notification-channels/<pk>/test/ — send a test payload through the channel."""

    permission_classes = [permissions.IsAuthenticated, IsTeamMember]

    def post(self, request, pk):
        team = request.user.active_team
        if not team:
            return Response({"success": False, "message": "No active team."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            channel = NotificationChannel.objects.get(pk=pk, team=team)
        except NotificationChannel.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        ok, message = _test_channel(channel)
        return Response({"success": ok, "message": message})


class NotificationChannelApplyAllView(APIView):
    """POST /api/v1/notification-channels/<pk>/apply-to-all-websites/

    Points every website in the team at this channel. Routing is otherwise set
    one site at a time, and a team that has just wired up a channel wants all of
    them on it — the sites missed in that manual pass are the ones that go on
    alerting nowhere.

    Any per-site uptime override is cleared as well. Leaving downtime routed to
    an older channel would defeat the point of the action, and uptime falls back
    to the general channel when unset.
    """

    permission_classes = [permissions.IsAuthenticated, IsTeamMember, RolePermission]
    # Rerouting every alert in the team is not a per-site edit.
    required_role = "manager"

    def post(self, request, pk):
        from apps.websites.models import Website

        team = request.user.active_team
        if not team:
            return Response({"detail": "No active team."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            channel = NotificationChannel.objects.get(pk=pk, team=team)
        except NotificationChannel.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        updated = Website.objects.filter(team=team).update(
            notification_channel=channel, uptime_notification_channel=None
        )

        AuditService.log_request(
            request, ActivityLog.Action.NOTIFICATION_CHANNEL_APPLIED_ALL,
            description=f"Routed {updated} website(s) to notification channel '{channel.name}'",
            resource_type="notification_channel", resource_id=channel.pk,
        )
        return Response({"updated": updated, "channel": channel.name})


def _test_channel(channel) -> tuple[bool, str]:
    if channel.channel_type == "email":
        return _test_email(channel)
    if channel.channel_type == "clickup":
        return _test_clickup(channel)
    if channel.channel_type == "slack":
        return _test_slack(channel)
    return False, f"Unknown channel type: {channel.channel_type}"


def _test_slack(channel) -> tuple[bool, str]:
    webhook_url = channel.config.get("webhook_url", "")
    if not webhook_url:
        return False, "Missing webhook_url in config."
    payload = {"text": "[Stacks Monitor] Test notification — your Slack alerts are working."}
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        webhook_url, data=data,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                return True, "Test message sent to Slack."
            return False, f"Slack returned HTTP {resp.status}."
    except Exception as e:
        return False, str(e)


def _test_email(channel) -> tuple[bool, str]:
    addresses = channel.config.get("addresses", [])
    if not addresses:
        return False, "No email addresses configured."
    from_email = settings.DEFAULT_FROM_EMAIL
    try:
        send_mail(
            subject="[Stacks Monitor] Test notification",
            message="This is a test notification from Stacks Monitor. Your email alerts are working correctly.",
            from_email=from_email,
            recipient_list=addresses,
            fail_silently=False,
        )
        return True, f"Test email sent to {', '.join(addresses)}"
    except Exception as e:
        return False, str(e)


def _test_clickup(channel) -> tuple[bool, str]:
    api_token = channel.config.get("api_token", "")
    task_id = channel.config.get("task_id", "")
    if not api_token or not task_id:
        return False, "Missing api_token or task_id in config."
    try:
        ClickUpClient(api_token).get_task(task_id)
        return True, f"ClickUp task '{task_id}' verified successfully."
    except Exception as e:
        return False, str(e)


# ------------------------------------------------------------------
# Monitor notification rules
# ------------------------------------------------------------------

class MonitorNotificationRuleListCreateView(generics.ListCreateAPIView):
    """GET /api/v1/monitors/<monitor_pk>/notification-rules/
    POST /api/v1/monitors/<monitor_pk>/notification-rules/
    """

    serializer_class = MonitorNotificationRuleSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeamMember, TeamRolePermission]

    def get_queryset(self):
        team = self.request.user.active_team
        if team is None:
            return MonitorNotificationRule.objects.none()
        return MonitorNotificationRule.objects.filter(
            monitor__team=team,
            monitor_id=self.kwargs["monitor_pk"],
        ).select_related("channel")

    def perform_create(self, serializer):
        team = self.request.user.active_team
        monitor = Monitor.objects.get(pk=self.kwargs["monitor_pk"], team=team)
        channel = NotificationChannel.objects.get(
            pk=serializer.validated_data.pop("channel_id"), team=team
        )
        rule = serializer.save(monitor=monitor, channel=channel)
        AuditService.log_request(
            self.request, ActivityLog.Action.MONITOR_RULE_CREATED,
            description=f"Added notification rule to monitor '{monitor.name}'",
            resource_type="monitor", resource_id=monitor.pk,
            metadata=site_meta(monitor),
        )


class MonitorNotificationRuleDetailView(generics.RetrieveUpdateDestroyAPIView):
    """GET/PATCH/DELETE /api/v1/monitors/<monitor_pk>/notification-rules/<pk>/"""

    serializer_class = MonitorNotificationRuleSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeamMember, TeamRolePermission]

    def get_queryset(self):
        team = self.request.user.active_team
        if team is None:
            return MonitorNotificationRule.objects.none()
        return MonitorNotificationRule.objects.filter(
            monitor__team=team,
            monitor_id=self.kwargs["monitor_pk"],
        ).select_related("channel")

    def perform_destroy(self, instance):
        AuditService.log_request(
            self.request, ActivityLog.Action.MONITOR_RULE_DELETED,
            description=f"Removed notification rule from monitor '{instance.monitor.name}'",
            resource_type="monitor", resource_id=instance.monitor_id,
            metadata=site_meta(instance.monitor),
        )
        instance.delete()


class MonitoringInfoView(APIView):
    """GET /api/v1/monitoring-info/ — who we are, so a client can allowlist us.

    Deliberately unauthenticated. The person who needs this is a site owner
    staring at a firewall log, or an agency staffer pasting a rule into a
    client's Cloudflare dashboard — neither is signed into Stacks Monitor at that
    moment. There is nothing secret here: the user-agent is already in every
    request we send, and the egress IP is already in the client's access log.

    This is the page the `+URL` in our user-agent points at, and the thing that
    makes "monitoring blocked" a thirty-second fix instead of a dead end.
    """

    permission_classes = [permissions.AllowAny]
    authentication_classes: list = []

    def get(self, request):
        from apps.common import outbound

        ips = outbound.egress_ips()
        ip_list = ", ".join(ips) if ips else "(contact your agency for the current IP)"
        first_ip = ips[0] if ips else "<monitor-ip>"

        return Response({
            "user_agent": outbound.USER_AGENT,
            "egress_ips": ips,
            "allowlist": {
                "cloudflare": (
                    "Security → WAF → Custom rules → Create rule.\n"
                    f'Expression:  (http.user_agent contains "Digivault-Monitor")'
                    f'{" or (ip.src in {" + " ".join(ips) + "})" if ips else ""}\n'
                    "Action: Skip → All remaining custom rules, plus Bot Fight Mode."
                ),
                "wordfence": (
                    "Wordfence → Firewall → Blocking → Whitelisted IP addresses.\n"
                    f"Add: {ip_list}\n"
                    "Also add 'Digivault-Monitor' under Tools → Whitelisted URLs if "
                    "rate limiting is set to block unknown crawlers."
                ),
                "siteground": (
                    "SiteGround's anti-bot has no customer-side allowlist. Open a "
                    "ticket with SiteGround support (Site Tools → Help) asking them "
                    f"to whitelist {ip_list} for the site's domain."
                ),
                "sucuri": (
                    "Sucuri Firewall dashboard → Security → Access Control → "
                    f"Whitelist IP addresses.\nAdd: {ip_list}"
                ),
                "htaccess": (
                    "# Stacks Monitor uptime monitor\n"
                    "<RequireAny>\n"
                    "  Require all granted\n"
                    f"  Require ip {first_ip}\n"
                    "</RequireAny>"
                ),
            },
            "docs": (
                "Stacks Monitor checks your site from a single IP and identifies itself "
                "honestly on every request. If your firewall blocks it, the "
                "dashboard reports 'blocked' rather than 'down' — your site is "
                "fine, we just cannot see it. Allowlisting restores coverage."
            ),
        })
