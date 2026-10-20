"""Platform owner endpoints: every workspace and every user, across tenants.

Superusers only. A superuser is the person who runs Stacks Monitor itself,
not a team owner, so these views deliberately ignore `active_team`. They
never return vault data: only names, counts, plans and account flags.

GET   /api/v1/platform/overview/
GET   /api/v1/platform/teams/?q=
PATCH /api/v1/platform/teams/<pk>/    {plan, require_2fa}
GET   /api/v1/platform/users/?q=
PATCH /api/v1/platform/users/<pk>/    {is_active}
"""

from __future__ import annotations

from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Team, TeamMembership, User
from apps.audit.models import ActivityLog
from apps.audit.services import AuditService

_MAX_ROWS = 500


class IsPlatformAdmin(permissions.BasePermission):
    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.is_superuser)


class _PlatformView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsPlatformAdmin]


def _team_row(team) -> dict:
    return {
        "id": str(team.pk),
        "name": team.name,
        "slug": team.slug,
        "plan": team.plan,
        "plan_label": team.get_plan_display(),
        "require_2fa": team.require_2fa,
        "owner_email": team.owner.email,
        "member_count": getattr(team, "member_count", None),
        "website_count": getattr(team, "website_count", None),
        "created_at": team.created_at.isoformat(),
    }


def _user_row(user) -> dict:
    return {
        "id": str(user.pk),
        "email": user.email,
        "name": f"{user.first_name} {user.last_name}".strip(),
        "is_active": user.is_active,
        "is_platform_admin": user.is_superuser,
        "totp_enabled": user.totp_enabled,
        "last_login": user.last_login.isoformat() if user.last_login else None,
        "created_at": user.created_at.isoformat(),
        "teams": [
            {"id": str(m.team_id), "name": m.team.name, "role": m.role, "plan": m.team.plan}
            for m in user.memberships.all()
        ],
    }


class PlatformOverviewView(_PlatformView):
    def get(self, request):
        from apps.websites.models import Website

        week_ago = timezone.now() - timedelta(days=7)
        plans = dict(
            Team.objects.values_list("plan").annotate(n=Count("id")).values_list("plan", "n")
        )
        return Response({
            "users": User.objects.count(),
            "active_users": User.objects.filter(is_active=True).count(),
            "teams": Team.objects.count(),
            "websites": Website.objects.count(),
            "signups_last_7_days": User.objects.filter(created_at__gte=week_ago).count(),
            "teams_by_plan": plans,
            "plans": [{"value": v, "label": label} for v, label in Team.Plan.choices],
        })


class PlatformTeamListView(_PlatformView):
    def get(self, request):
        q = (request.query_params.get("q") or "").strip()
        qs = Team.objects.select_related("owner").annotate(
            member_count=Count("memberships", distinct=True),
            website_count=Count("websites", distinct=True),
        ).order_by("-created_at")
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(owner__email__icontains=q))
        return Response([_team_row(t) for t in qs[:_MAX_ROWS]])


class PlatformTeamDetailView(_PlatformView):
    def patch(self, request, pk):
        team = Team.objects.select_related("owner").filter(pk=pk).first()
        if team is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        changes = []
        plan = request.data.get("plan")
        if plan is not None:
            if plan not in Team.Plan.values:
                return Response({"detail": f"Unknown plan: {plan}"}, status=status.HTTP_400_BAD_REQUEST)
            if plan != team.plan:
                changes.append(f"plan {team.plan} -> {plan}")
                team.plan = plan
        require_2fa = request.data.get("require_2fa")
        if require_2fa is not None:
            require_2fa = bool(require_2fa)
            if require_2fa != team.require_2fa:
                changes.append(f"require_2fa {team.require_2fa} -> {require_2fa}")
                team.require_2fa = require_2fa
        if changes:
            team.save(update_fields=["plan", "require_2fa", "updated_at"])
            AuditService.log(
                actor=request.user, action=ActivityLog.Action.PLATFORM_PLAN_CHANGED, team=team,
                description=f"Platform owner {request.user.email} changed {', '.join(changes)}",
                resource_type="team", resource_id=team.pk,
            )
        team = Team.objects.select_related("owner").annotate(
            member_count=Count("memberships", distinct=True),
            website_count=Count("websites", distinct=True),
        ).get(pk=team.pk)
        return Response(_team_row(team))


class PlatformUserListView(_PlatformView):
    def get(self, request):
        q = (request.query_params.get("q") or "").strip()
        qs = User.objects.prefetch_related("memberships__team").order_by("-created_at")
        if q:
            qs = qs.filter(Q(email__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q))
        return Response([_user_row(u) for u in qs[:_MAX_ROWS]])


class PlatformUserDetailView(_PlatformView):
    def patch(self, request, pk):
        user = User.objects.prefetch_related("memberships__team").filter(pk=pk).first()
        if user is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        is_active = request.data.get("is_active")
        if is_active is not None:
            is_active = bool(is_active)
            if user.pk == request.user.pk and not is_active:
                return Response({"detail": "You cannot deactivate your own account."}, status=status.HTTP_400_BAD_REQUEST)
            if user.is_superuser and not is_active:
                return Response({"detail": "Remove platform owner rights in Django admin first."}, status=status.HTTP_400_BAD_REQUEST)
            if is_active != user.is_active:
                user.is_active = is_active
                user.save(update_fields=["is_active", "updated_at"])
                membership = TeamMembership.objects.select_related("team").filter(user=user).first()
                AuditService.log(
                    actor=request.user, action=ActivityLog.Action.PLATFORM_USER_UPDATED,
                    team=membership.team if membership else None,
                    description=f"Platform owner {request.user.email} {'activated' if is_active else 'deactivated'} {user.email}",
                    resource_type="user", resource_id=user.pk,
                )
        return Response(_user_row(user))
