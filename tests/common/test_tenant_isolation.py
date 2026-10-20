"""Every API route keeps one team's data away from every other team.

Team "alpha" gets one of everything. The owner of team "bravo" (the most
privileged role, so a 403 never hides a missing filter) then calls every
route in the URL conf with alpha's real ids, using every HTTP method. A route
passes when it refuses (401/403/404/405), or answers a read without any of
alpha's data in the body. A write that succeeds, or any 5xx, fails it.

The route list is read from the URL conf, not written out here. A new route
whose path parameter this file cannot fill with an alpha id fails
`test_every_route_parameter_is_mapped`, so nobody can add an endpoint that
skips this check by accident.
"""

import re
from datetime import timedelta

import pytest
from django.urls import URLPattern, URLResolver, get_resolver
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import SubTeam, TeamInvitation, TeamMembership, User
from apps.accounts.services import TeamService

MARK = "ALPHAMARK"

#: Routes that are public by design, keyed by path prefix, with the reason.
PUBLIC_BY_DESIGN = {
    "auth/invitations/": "the invitation token itself is the secret",
    "public/status/": "a published status page is public",
    "public/tools/": "free marketing-site tools, they read no team data",
}

#: Routes with no team data at all, or ingest endpoints authenticated by a
#: site key rather than a user.
NOT_TENANT_ROUTES = (
    "auth/login/", "auth/first-password/", "auth/token/", "auth/2fa/",
    "auth/password-reset/", "auth/me/", "auth/teams/",
    "ingest", "collect", "heartbeat", "s.js", "health",
)


# --- alpha's world ----------------------------------------------------------


@pytest.fixture
def alpha(db):
    from apps.alerts.models import AlertRule, AlertSuppression
    from apps.clients.models import Client
    from apps.credentials.models import (
        Credential,
        CredentialAccessRequest,
        CredentialPasswordHistory,
        SubTeamCredentialGrant,
        VaultFolder,
    )
    from apps.credentials import encryption
    from apps.heatmap.models import HeatmapPageSnapshot, HeatmapPageStats
    from apps.monitors.models import Monitor, MonitorNotificationRule, NotificationChannel
    from apps.reports.models import Report
    from apps.scripts.models import Script, ScriptChange
    from apps.status_pages.models import (
        MaintenanceWindow,
        StatusPage,
        StatusPageIncident,
        StatusPageMonitor,
    )
    from apps.websites.models import Website

    owner = User.objects.create_user(email="owner@alpha.test", password="RealPass1!", first_name=MARK)
    team = TeamService.create(name=f"{MARK} Agency", owner=owner)
    User.objects.filter(pk=owner.pk).update(active_team=team)
    member = User.objects.create_user(email="dev@alpha.test", password="RealPass1!", first_name=MARK)
    membership = TeamMembership.objects.create(user=member, team=team, role="developer")
    User.objects.filter(pk=member.pk).update(active_team=team)

    sub_team = SubTeam.objects.create(team=team, name=f"{MARK} Web Team")
    invitation = TeamInvitation.objects.create(
        team=team, invited_by=owner, email="invitee@alpha.test", role="developer",
    )
    client = Client.objects.create(team=team, name=f"{MARK} Client")
    website = Website.objects.create(
        team=team, client=client, name=f"{MARK} Site", domain="alphamark.test",
    )
    script = Script.objects.create(website=website, src_url=f"https://cdn.alphamark.test/{MARK}.js")
    change = ScriptChange.objects.create(
        website=website, script=script, change_type="added", description=f"{MARK} change",
    )
    folder = VaultFolder.objects.create(team=team, name=f"{MARK} Folder")
    credential = Credential.objects.create(team=team, website=website, label=f"{MARK} Login", folder=folder)
    credential.set_password(f"{MARK}-secret")
    credential.save()
    history = CredentialPasswordHistory.objects.create(
        credential=credential, _password=encryption.encrypt(f"{MARK}-old-secret"),
    )
    access_request = CredentialAccessRequest.objects.create(
        team=team, credential=credential, requester=member,
    )
    grant = SubTeamCredentialGrant.objects.create(
        sub_team=sub_team, scope=SubTeamCredentialGrant.Scope.CREDENTIAL, credential=credential,
    )
    alert_rule = AlertRule.objects.create(team=team, channel=AlertRule.Channel.EMAIL, name=f"{MARK} Rule") \
        if any(f.name == "name" for f in AlertRule._meta.fields) \
        else AlertRule.objects.create(team=team, channel=AlertRule.Channel.EMAIL)
    suppression = AlertSuppression.objects.create(
        website=website, match_type="domain", match_value=f"{MARK}.test",
    )
    monitor = Monitor.objects.create(team=team, website=website, name=f"{MARK} Monitor", url="https://alphamark.test")
    channel = NotificationChannel.objects.create(
        team=team, name=f"{MARK} Channel", channel_type="email", config={"email": "alerts@alpha.test"},
    )
    notification_rule = MonitorNotificationRule.objects.create(monitor=monitor, channel=channel)
    page = StatusPage.objects.create(team=team, name=f"{MARK} Status", slug="alphamark-status")
    page_monitor = StatusPageMonitor.objects.create(status_page=page, monitor=monitor)
    incident = StatusPageIncident.objects.create(status_page=page, title=f"{MARK} Incident")
    now = timezone.now()
    maintenance = MaintenanceWindow.objects.create(
        status_page=page, title=f"{MARK} Maintenance",
        scheduled_start=now + timedelta(days=1), scheduled_end=now + timedelta(days=1, hours=1),
    )
    snapshot = HeatmapPageSnapshot.objects.create(website=website, page_url=f"https://alphamark.test/{MARK}")
    HeatmapPageStats.objects.create(website=website, page_url=f"https://alphamark.test/{MARK}")
    report = Report.objects.create(
        team=team, website=website, period_start=now.date() - timedelta(days=30), period_end=now.date(),
    )

    return {
        "team": team, "owner": owner, "member": member, "membership": membership,
        "sub_team": sub_team, "invitation": invitation, "client": client, "website": website,
        "script": script, "change": change, "folder": folder, "credential": credential,
        "history": history, "access_request": access_request, "grant": grant,
        "alert_rule": alert_rule, "suppression": suppression, "monitor": monitor,
        "channel": channel, "notification_rule": notification_rule, "page": page,
        "page_monitor": page_monitor, "incident": incident, "maintenance": maintenance,
        "snapshot": snapshot, "report": report,
    }


@pytest.fixture
def bravo(db):
    owner = User.objects.create_user(email="owner@bravo.test", password="RealPass1!")
    team = TeamService.create(name="Bravo Agency", owner=owner)
    User.objects.filter(pk=owner.pk).update(active_team=team)
    owner.refresh_from_db()
    client = APIClient()
    client.force_authenticate(owner)
    # A crash is reported as a 500 like in production, not raised, so one
    # broken view does not hide the rest of the sweep.
    client.raise_request_exception = False
    return client


# --- reading the URL conf ---------------------------------------------------

_REGEX_GROUP = re.compile(r"\(\?P<(\w+)>[^)]*\)")
_PATH_PARAM = re.compile(r"<(?:\w+:)?(\w+)>")


def _api_routes():
    """Every api/v1 route as a path template like 'monitors/<pk>/pause/'."""

    def walk(patterns, prefix=""):
        for p in patterns:
            if isinstance(p, URLResolver):
                yield from walk(p.url_patterns, prefix + str(p.pattern))
            elif isinstance(p, URLPattern):
                yield prefix + str(p.pattern)

    routes = set()
    for raw in walk(get_resolver().url_patterns):
        if not raw.startswith("api/v1/"):
            continue
        path = raw[len("api/v1/"):]
        # DRF router duplicates: format-suffix variants and the API root.
        if "format" in path or path in ("", "^$"):
            continue
        path = path.replace("^", "").replace("$", "")
        path = _REGEX_GROUP.sub(lambda m: f"<{m.group(1)}>", path)
        path = _PATH_PARAM.sub(lambda m: f"<{m.group(1)}>", path)
        routes.add(path)
    return sorted(routes)


def _skipped(path):
    return any(path.startswith(p) for p in PUBLIC_BY_DESIGN) or any(
        token in path for token in NOT_TENANT_ROUTES if not path.startswith("auth/teams/<")
    )


#: (literal segment before the parameter, parameter name) -> alpha object.
#: Checked after the status-page overrides below.
_PARAM_SOURCES = {
    ("teams", "pk"): "team", ("teams", "team_pk"): "team",
    ("members", "pk"): "membership", ("members", "user_id"): "member_user",
    ("sub-teams", "pk"): "sub_team", ("sub-teams", "sub_team_pk"): "sub_team",
    ("invitations", "pk"): "invitation",
    ("websites", "pk"): "website", ("websites", "website_pk"): "website",
    ("changes", "pk"): "change", ("scripts", "pk"): "script",
    ("folders", "pk"): "folder", ("access-requests", "pk"): "access_request",
    ("credentials", "pk"): "credential", ("password-history", "entry_pk"): "history",
    ("credential-grants", "pk"): "grant", ("shares", "user_id"): "member_user",
    ("alert-rules", "pk"): "alert_rule", ("alert-suppressions", "pk"): "suppression",
    ("monitors", "pk"): "monitor", ("monitors", "monitor_pk"): "monitor",
    ("notification-rules", "pk"): "notification_rule",
    ("notification-channels", "pk"): "channel",
    ("status-pages", "pk"): "page", ("status-pages", "page_pk"): "page",
    ("incidents", "pk"): "incident", ("maintenance", "pk"): "maintenance",
    ("clients", "pk"): "client", ("snapshots", "pk"): "snapshot", ("reports", "pk"): "report",
    ("users", "pk"): "member_user",
}


def _source_for(path, segment, name):
    if path.startswith("status-pages/") and (segment, name) == ("monitors", "pk"):
        return "page_monitor"
    return _PARAM_SOURCES.get((segment, name))


def _fill(path, alpha):
    """Concrete URL for `path` using alpha's ids, or None for an unmapped param."""
    out = []
    segments = path.strip("/").split("/")
    for i, seg in enumerate(segments):
        m = _PATH_PARAM.fullmatch(seg)
        if not m:
            out.append(seg)
            continue
        source = _source_for(path, segments[i - 1] if i else "", m.group(1))
        if source is None:
            return None
        obj = alpha["member"] if source == "member_user" else alpha[source]
        out.append(str(obj.pk))
    return "/api/v1/" + "/".join(out) + "/"


def _id_routes():
    return [p for p in _api_routes() if "<" in p and not _skipped(p)]


def _list_routes():
    return [p for p in _api_routes() if "<" not in p and not _skipped(p)]


# --- the checks -------------------------------------------------------------


@pytest.mark.django_db
def test_every_route_parameter_is_mapped(alpha):
    unmapped = [p for p in _id_routes() if _fill(p, alpha) is None]
    assert not unmapped, (
        "These routes take an id this suite cannot fill, so their isolation is "
        f"untested. Add them to _PARAM_SOURCES: {unmapped}"
    )


def _leaks(resp):
    body = resp.content.decode("utf-8", errors="replace") if resp.content else ""
    return MARK in body or "alphamark" in body


@pytest.mark.django_db
def test_no_route_hands_alpha_data_to_bravo(alpha, bravo):
    failures = []
    for path in _id_routes():
        url = _fill(path, alpha)
        for method in ("get", "post", "put", "patch", "delete"):
            resp = getattr(bravo, method)(url, {}, format="json")
            if resp.status_code in (401, 403, 404, 405):
                continue
            # A crash can sit after the lookup it skipped, so it counts too.
            if resp.status_code >= 500 or _leaks(resp) or (method != "get" and 200 <= resp.status_code < 300):
                failures.append(f"{method.upper()} {url} -> {resp.status_code}")
    assert not failures, "Cross-team access:\n" + "\n".join(failures)


@pytest.mark.django_db
def test_list_routes_never_show_alpha_rows(alpha, bravo):
    """Lists are scoped by the active team. Filters that take an id in the
    query string (?website=, ?client_id=, ...) must not widen that scope."""
    ids = {
        "website": alpha["website"].pk, "website_id": alpha["website"].pk,
        "client": alpha["client"].pk, "client_id": alpha["client"].pk,
        "monitor": alpha["monitor"].pk, "credential": alpha["credential"].pk,
        # Matches alpha's names, but a search that echoes its query back
        # must not trip the leak check on its own.
        "folder": alpha["folder"].pk, "q": "alpha",
    }
    failures = []
    for path in _list_routes():
        url = f"/api/v1/{path}"
        for params in ({}, ids):
            resp = bravo.get(url, params)
            if _leaks(resp):
                failures.append(f"GET {url} {params or ''} -> {resp.status_code}")
    assert not failures, "Alpha rows visible to bravo:\n" + "\n".join(failures)


@pytest.mark.django_db
def test_alpha_data_survives_bravo_probing(alpha, bravo):
    """The write probes above must not have changed or deleted anything."""
    for path in _id_routes():
        url = _fill(path, alpha)
        for method in ("post", "put", "patch", "delete"):
            getattr(bravo, method)(url, {"name": "bravo was here"}, format="json")

    for key, obj in alpha.items():
        if not hasattr(obj, "refresh_from_db"):
            continue
        type(obj).objects.get(pk=obj.pk)  # still exists
        obj.refresh_from_db()
        for field in ("name", "label", "title"):
            value = getattr(obj, field, None)
            if isinstance(value, str) and value:
                assert value.startswith(MARK), f"{key}.{field} changed to {value!r}"
