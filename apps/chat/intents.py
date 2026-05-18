import re

from django.db.models import Q


# ---------------------------------------------------------------------------
# Intent detection
# ---------------------------------------------------------------------------

def detect_intent(message: str) -> tuple[str, dict]:
    msg = message.lower().strip()

    if re.search(r'\b(help|commands?|what can you|options)\b', msg):
        return 'help', {}

    if re.search(r'\b(summary|overview|dashboard|stats|statistics)\b', msg):
        return 'summary', {}

    # Onboard / add a domain — check before generic domain check
    domain_m = re.search(r'([a-z0-9][a-z0-9\-]*\.[a-z]{2,}(?:\.[a-z]{2,})?)', msg)
    if domain_m and re.search(r'\b(onboard|add|register|new site|new website|setup)\b', msg):
        return 'onboard_website', {'query': domain_m.group(1)}

    # Check / status for a specific domain
    if domain_m and re.search(r'\b(check|status|details?|info|about|show|how is|how\'s)\b', msg):
        return 'check_website', {'query': domain_m.group(1)}

    # Bare domain mention → check
    if domain_m:
        return 'check_website', {'query': domain_m.group(1)}

    if re.search(r'\b(monitors? down|down monitors?|failing monitors?|broken monitors?)\b', msg):
        return 'monitors_down', {}

    if re.search(r'\b(monitors?|uptime|list monitors?)\b', msg):
        return 'list_monitors', {}

    if re.search(r'\b(alerts?|notifications?|unread|pending changes?|script changes?|changes?)\b', msg):
        if re.search(r'\brecent|latest|last\b', msg):
            return 'list_changes', {}
        return 'list_alerts', {}

    if re.search(r'\b(websites?|sites?|domains?|list sites?|my sites?|all sites?)\b', msg):
        return 'list_websites', {}

    if re.search(r'\b(clients?|customers?|list clients?)\b', msg):
        return 'list_clients', {}

    return 'fallback', {}


# ---------------------------------------------------------------------------
# Status helpers
# ---------------------------------------------------------------------------

_SITE_EMOJI = {'active': '✅', 'warning': '⚠️', 'critical': '🚨', 'inactive': '⏸️'}
_MON_EMOJI  = {'up': '✅', 'down': '🔴', 'degraded': '⚠️', 'paused': '⏸️', 'pending': '🔄'}
_SEV_EMOJI  = {'high': '🚨', 'medium': '⚠️', 'low': 'ℹ️', 'critical': '🚨'}


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

def handle_help(team, params):
    return {
        'reply': (
            "Here's what I can help you with:\n\n"
            "• **check [domain]** — Check a website's status (e.g. *check abc.com*)\n"
            "• **websites** — List all your monitored websites\n"
            "• **monitors** — Show all uptime monitors\n"
            "• **monitors down** — Show only failing monitors\n"
            "• **alerts** — Show unacknowledged script-change alerts\n"
            "• **changes** — Show recent script changes\n"
            "• **clients** — List your clients\n"
            "• **onboard [domain]** — Get setup instructions for a new site\n"
            "• **summary** — Dashboard overview stats"
        ),
        'type': 'help',
        'data': None,
    }


def handle_check_website(team, params):
    from apps.websites.models import Website
    from apps.scripts.models import ScriptChange

    query = params.get('query', '')
    site = Website.objects.filter(
        Q(domain__icontains=query) | Q(name__icontains=query),
        team=team,
    ).first()

    if not site:
        return {
            'reply': (
                f"I couldn't find **{query}** in your team's websites. "
                f"If you'd like to start monitoring it, try: *onboard {query}*"
            ),
            'type': 'not_found',
            'data': {'query': query},
        }

    pending = ScriptChange.objects.filter(website=site, acknowledged_at__isnull=True).count()
    emoji = _SITE_EMOJI.get(site.status, '❓')
    last_seen = (
        site.last_seen_at.strftime('%Y-%m-%d %H:%M UTC')
        if site.last_seen_at else 'Never'
    )

    return {
        'reply': (
            f"**{site.name}** ({site.domain})\n"
            f"Status: {emoji} {site.status.capitalize()}\n"
            f"Scripts detected: {site.script_count or 0}\n"
            f"Unknown scripts: {site.unknown_script_count or 0}\n"
            f"Pending changes: {pending}\n"
            f"Last seen: {last_seen}"
        ),
        'type': 'website_status',
        'data': {
            'id': str(site.id),
            'name': site.name,
            'domain': site.domain,
            'status': site.status,
            'pending_changes': pending,
        },
    }


def handle_list_websites(team, params):
    from apps.websites.models import Website

    sites = list(Website.objects.filter(team=team).order_by('name')[:20])
    if not sites:
        return {
            'reply': "You don't have any websites yet. Go to **Websites → Add website** to get started.",
            'type': 'empty',
            'data': [],
        }

    lines = [
        f"• {_SITE_EMOJI.get(s.status, '❓')} **{s.name}** — {s.domain}"
        for s in sites
    ]
    return {
        'reply': f"**Your websites ({len(sites)} total):**\n\n" + '\n'.join(lines),
        'type': 'websites_list',
        'data': [{'id': str(s.id), 'name': s.name, 'domain': s.domain, 'status': s.status} for s in sites],
    }


def handle_list_monitors(team, params):
    from apps.monitors.models import Monitor

    monitors = list(Monitor.objects.filter(team=team).order_by('name')[:20])
    if not monitors:
        return {
            'reply': "You don't have any uptime monitors yet. Go to **Monitors → Add monitor** to set one up.",
            'type': 'empty',
            'data': [],
        }

    lines = []
    for m in monitors:
        rt = f" ({m.last_response_time}ms)" if m.last_response_time else ''
        lines.append(f"• {_MON_EMOJI.get(m.status, '❓')} **{m.name}** — {m.url}{rt}")

    return {
        'reply': f"**Uptime monitors ({len(monitors)} total):**\n\n" + '\n'.join(lines),
        'type': 'monitors_list',
        'data': [{'id': str(m.id), 'name': m.name, 'status': m.status, 'url': m.url} for m in monitors],
    }


def handle_monitors_down(team, params):
    from apps.monitors.models import Monitor

    monitors = list(
        Monitor.objects.filter(team=team)
        .filter(Q(status='down') | Q(status='degraded'))
        .order_by('name')
    )
    if not monitors:
        return {
            'reply': "✅ All your monitors are up! No issues detected.",
            'type': 'monitors_all_up',
            'data': [],
        }

    lines = [
        f"• {_MON_EMOJI.get(m.status, '❓')} **{m.name}** — {m.status.upper()} ({m.url})"
        for m in monitors
    ]
    return {
        'reply': f"🚨 **{len(monitors)} monitor(s) need attention:**\n\n" + '\n'.join(lines),
        'type': 'monitors_down',
        'data': [{'id': str(m.id), 'name': m.name, 'status': m.status, 'url': m.url} for m in monitors],
    }


def handle_list_alerts(team, params):
    from apps.scripts.models import ScriptChange

    changes = list(
        ScriptChange.objects.filter(website__team=team, acknowledged_at__isnull=True)
        .select_related('website')
        .order_by('-created_at')[:10]
    )
    if not changes:
        return {
            'reply': "✅ No unacknowledged alerts. Everything looks good!",
            'type': 'no_alerts',
            'data': [],
        }

    lines = [
        f"• {_SEV_EMOJI.get(c.severity, '•')} **{c.website.domain}** — {c.description[:80]}"
        for c in changes
    ]
    return {
        'reply': f"**{len(changes)} unacknowledged alert(s):**\n\n" + '\n'.join(lines),
        'type': 'alerts_list',
        'data': [
            {'id': str(c.id), 'website': c.website.domain, 'severity': c.severity, 'description': c.description}
            for c in changes
        ],
    }


def handle_list_changes(team, params):
    from apps.scripts.models import ScriptChange

    query = params.get('query', '')
    qs = ScriptChange.objects.filter(website__team=team).select_related('website').order_by('-created_at')
    if query:
        qs = qs.filter(Q(website__domain__icontains=query) | Q(website__name__icontains=query))

    changes = list(qs[:10])
    if not changes:
        return {
            'reply': "No recent script changes found.",
            'type': 'empty',
            'data': [],
        }

    lines = []
    for c in changes:
        ack = ' ✅' if c.is_acknowledged else ' ⏳'
        lines.append(
            f"• **{c.website.domain}** — {c.change_type.replace('_', ' ')} ({c.severity}){ack}"
        )
    return {
        'reply': "**Recent script changes:**\n\n" + '\n'.join(lines),
        'type': 'changes_list',
        'data': [
            {'id': str(c.id), 'website': c.website.domain, 'type': c.change_type, 'severity': c.severity}
            for c in changes
        ],
    }


def handle_list_clients(team, params):
    try:
        from apps.clients.models import Client

        clients = list(Client.objects.filter(team=team).order_by('name')[:20])
        if not clients:
            return {
                'reply': "You don't have any clients yet. Go to **Clients** to add your first client.",
                'type': 'empty',
                'data': [],
            }

        lines = [f"• **{c.name}**" for c in clients]
        return {
            'reply': f"**Your clients ({len(clients)} total):**\n\n" + '\n'.join(lines),
            'type': 'clients_list',
            'data': [{'id': str(c.id), 'name': c.name} for c in clients],
        }
    except Exception:
        return {
            'reply': "Unable to retrieve clients. Please visit the Clients section.",
            'type': 'error',
            'data': None,
        }


def handle_summary(team, params):
    from apps.monitors.models import Monitor
    from apps.scripts.models import ScriptChange
    from apps.websites.models import Website

    total_sites = Website.objects.filter(team=team).count()
    critical_sites = Website.objects.filter(team=team, status='critical').count()
    warning_sites = Website.objects.filter(team=team, status='warning').count()
    total_monitors = Monitor.objects.filter(team=team).count()
    down_monitors = Monitor.objects.filter(team=team).filter(Q(status='down') | Q(status='degraded')).count()
    pending = ScriptChange.objects.filter(website__team=team, acknowledged_at__isnull=True).count()
    high_risk = ScriptChange.objects.filter(
        website__team=team, acknowledged_at__isnull=True, severity='high'
    ).count()

    site_detail = f" ({critical_sites} critical, {warning_sites} warning)" if (critical_sites or warning_sites) else " (all healthy ✅)"
    mon_detail = f" (**{down_monitors} down** ⚠️)" if down_monitors else " (all up ✅)"
    risk_detail = f" ({high_risk} high risk 🚨)" if high_risk else ''

    return {
        'reply': (
            "**Dashboard Summary**\n\n"
            f"🌐 Websites: **{total_sites}** total{site_detail}\n"
            f"📡 Monitors: **{total_monitors}** total{mon_detail}\n"
            f"🔔 Pending changes: **{pending}**{risk_detail}"
        ),
        'type': 'summary',
        'data': {
            'total_sites': total_sites,
            'critical_sites': critical_sites,
            'total_monitors': total_monitors,
            'down_monitors': down_monitors,
            'pending_changes': pending,
            'high_risk': high_risk,
        },
    }


def handle_onboard_website(team, params):
    from apps.websites.models import Website

    query = params.get('query', '')
    existing = Website.objects.filter(
        Q(domain__icontains=query) | Q(name__icontains=query),
        team=team,
    ).first()

    if existing:
        return {
            'reply': (
                f"✅ **{query}** is already registered! "
                f"Current status: **{existing.status}**.\n"
                f"You can view it in the Websites section."
            ),
            'type': 'already_onboarded',
            'data': {'id': str(existing.id), 'domain': existing.domain},
        }

    return {
        'reply': (
            f"To onboard **{query}**:\n\n"
            "1. Go to **Websites → Add website**\n"
            f"2. Enter the domain: `{query}`\n"
            "3. Select the platform (WordPress, Webflow, Shopify…)\n"
            "4. Copy the generated snippet and paste it before `</body>`\n"
            "5. The dashboard will start detecting scripts within minutes ✅"
        ),
        'type': 'onboard_instructions',
        'data': {'domain': query},
    }


def handle_fallback(team, params):
    return {
        'reply': "I'm not sure what you're asking. Type **help** to see what I can do.",
        'type': 'fallback',
        'data': None,
    }


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

_HANDLERS = {
    'help': handle_help,
    'check_website': handle_check_website,
    'list_websites': handle_list_websites,
    'list_monitors': handle_list_monitors,
    'monitors_down': handle_monitors_down,
    'list_alerts': handle_list_alerts,
    'list_changes': handle_list_changes,
    'list_clients': handle_list_clients,
    'summary': handle_summary,
    'onboard_website': handle_onboard_website,
    'fallback': handle_fallback,
}


def process_message(team, message: str) -> dict:
    intent, params = detect_intent(message)
    handler = _HANDLERS.get(intent, handle_fallback)
    return handler(team, params)
