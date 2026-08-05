import re

from django.db.models import Q

from .followups import suggest


# ---------------------------------------------------------------------------
# Intent detection
# ---------------------------------------------------------------------------

def detect_intent(message: str) -> tuple[str, dict]:
    msg = message.lower().strip()

    if re.search(r'\b(help|commands?|what can you|options|guide)\b', msg):
        return 'help', {}

    if re.search(r'\b(summary|overview|dashboard|stats|statistics)\b', msg):
        return 'summary', {}

    domain_m = re.search(r'([a-z0-9][a-z0-9\-]*\.[a-z]{2,}(?:\.[a-z]{2,})?)', msg)

    # Onboard / add a domain — check before generic domain check
    if domain_m and re.search(r'\b(onboard|add|register|new site|new website|setup)\b', msg):
        return 'onboard_website', {'query': domain_m.group(1)}

    # Scripts for a specific site
    if domain_m and re.search(r'\b(scripts?|third.?party|trackers?|tags?|pixels?)\b', msg):
        return 'website_scripts', {'query': domain_m.group(1)}

    # Check / status for a specific domain
    if domain_m and re.search(r'\b(check|status|details?|info|about|show|how is|how\'s|forms?)\b', msg):
        return 'check_website', {'query': domain_m.group(1)}

    # Bare domain mention → check
    if domain_m:
        return 'check_website', {'query': domain_m.group(1)}

    # Client lookup
    if re.search(r'\b(clients?|customers?)\b', msg):
        if re.search(r'\b(check|details?|info|hosting|access|how|status)\b', msg):
            name_m = re.search(r'(?:client|customer)\s+(.+)', msg)
            return 'check_client', {'query': name_m.group(1).strip() if name_m else ''}
        return 'list_clients', {}

    if re.search(r'\b(monitors? down|down monitors?|failing monitors?|broken monitors?)\b', msg):
        return 'monitors_down', {}

    if re.search(r'\b(monitors?|uptime|list monitors?)\b', msg):
        return 'list_monitors', {}

    # High / critical alerts
    if re.search(r'\b(high|critical|urgent|serious)\b', msg) and re.search(r'\b(alerts?|changes?|issues?|risks?)\b', msg):
        return 'high_alerts', {}

    if re.search(r'\b(alerts?|notifications?|unread|pending changes?)\b', msg):
        return 'list_alerts', {}

    if re.search(r'\b(recent|latest|last)\b', msg) and re.search(r'\b(changes?|updates?)\b', msg):
        return 'list_changes', {}

    if re.search(r'\b(script changes?|changes?)\b', msg):
        return 'list_changes', {}

    # Unknown / unclassified scripts
    if re.search(r'\b(unknown|unidentified|unclassified|suspicious)\b', msg) and re.search(r'\b(scripts?|trackers?|tags?)\b', msg):
        return 'unknown_scripts', {}

    if re.search(r'\b(scripts?|trackers?|third.?party|all scripts?)\b', msg):
        return 'list_scripts', {}

    if re.search(r'\b(forms?|detected forms?|contact forms?)\b', msg):
        return 'list_forms', {}

    if re.search(r'\b(websites?|sites?|domains?|list sites?|my sites?|all sites?)\b', msg):
        return 'list_websites', {}

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
            "Here's everything I can help with:\n\n"
            "**Websites**\n"
            "• **check [domain]** — Status, scripts, pending alerts\n"
            "• **scripts for [domain]** — What third-party scripts are running\n"
            "• **websites** — List all monitored sites\n"
            "• **onboard [domain]** — Setup instructions for a new site\n\n"
            "**Monitoring**\n"
            "• **monitors** — All uptime monitors\n"
            "• **monitors down** — Only failing monitors\n\n"
            "**Alerts & Changes**\n"
            "• **alerts** — Unacknowledged script-change alerts\n"
            "• **high alerts** — Critical/high severity only\n"
            "• **recent changes** — Latest script change history\n"
            "• **unknown scripts** — Unclassified third-party scripts\n\n"
            "**Clients**\n"
            "• **clients** — List all your clients\n"
            "• **client [name]** — Details for a specific client\n\n"
            "**Other**\n"
            "• **forms** — Detected forms across all sites\n"
            "• **summary** — Full dashboard overview"
        ),
        'type': 'help',
        'data': None,
    }


def handle_check_website(team, params):
    from apps.websites.models import Website
    from apps.scripts.models import ScriptChange, Script

    query = params.get('query', '')
    site = Website.objects.filter(
        Q(domain__icontains=query) | Q(name__icontains=query),
        team=team,
    ).first()

    if not site:
        return {
            'reply': (
                f"I couldn't find **{query}** in your monitored websites. "
                f"Try: *onboard {query}* to start monitoring it."
            ),
            'type': 'not_found',
            'data': {'query': query},
        }

    pending = ScriptChange.objects.filter(website=site, acknowledged_at__isnull=True).count()
    high_pending = ScriptChange.objects.filter(
        website=site, acknowledged_at__isnull=True, severity__in=['high', 'critical']
    ).count()
    # Compute counts directly — script_count/unknown_script_count are annotation
    # -only attributes that don't exist on a plainly-fetched Website.
    script_count = Script.objects.filter(website=site, is_active=True).count()
    unknown_count = Script.objects.filter(
        website=site, is_active=True, provider='unknown', review_status='pending'
    ).count()
    emoji = _SITE_EMOJI.get(site.status, '❓')
    last_seen = site.last_seen_at.strftime('%d %b %Y %H:%M UTC') if site.last_seen_at else 'Never'

    # Top providers
    top_providers = list(
        Script.objects.filter(website=site, is_active=True)
        .exclude(provider='unknown')
        .values_list('provider', flat=True)
        .distinct()[:5]
    )
    providers_str = ', '.join(top_providers) if top_providers else 'None detected yet'

    alert_str = ''
    if high_pending:
        alert_str = f"\n⚠️ **{high_pending} high-severity alert(s) need attention!**"

    return {
        'reply': (
            f"**{site.name}** ({site.domain})\n"
            f"Status: {emoji} {site.status.capitalize()}\n"
            f"Scripts detected: **{script_count}** ({unknown_count} unknown)\n"
            f"Key providers: {providers_str}\n"
            f"Pending changes: **{pending}**{alert_str}\n"
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


def handle_website_scripts(team, params):
    from apps.websites.models import Website
    from apps.scripts.models import Script

    query = params.get('query', '')
    site = Website.objects.filter(
        Q(domain__icontains=query) | Q(name__icontains=query),
        team=team,
    ).first()

    if not site:
        return {
            'reply': f"I couldn't find **{query}** in your websites.",
            'type': 'not_found',
            'data': {'query': query},
        }

    scripts = list(Script.objects.filter(website=site, is_active=True).order_by('provider', 'category')[:20])
    if not scripts:
        return {
            'reply': f"No scripts detected yet for **{site.domain}**. Make sure the tracking snippet is installed.",
            'type': 'empty',
            'data': [],
        }

    known = [s for s in scripts if s.provider != 'unknown']
    unknown = [s for s in scripts if s.provider == 'unknown']

    lines = []
    for s in known:
        lines.append(f"• **{s.provider}** — {s.category or 'uncategorized'}")
    if unknown:
        lines.append(f"• ⚠️ **{len(unknown)} unknown script(s)** — review recommended")

    return {
        'reply': (
            f"**Scripts on {site.domain}** ({len(scripts)} active):\n\n"
            + '\n'.join(lines)
        ),
        'type': 'scripts_list',
        'data': [{'provider': s.provider, 'category': s.category, 'src_url': s.src_url} for s in scripts],
    }


def handle_list_scripts(team, params):
    from apps.scripts.models import Script

    scripts = list(
        Script.objects.filter(website__team=team, is_active=True)
        .values('provider', 'category')
        .distinct()
        .order_by('provider')[:25]
    )
    if not scripts:
        return {
            'reply': "No scripts detected yet across your sites.",
            'type': 'empty',
            'data': [],
        }

    lines = [f"• **{s['provider']}** — {s['category'] or 'uncategorized'}" for s in scripts]
    return {
        'reply': f"**Active script providers across all sites:**\n\n" + '\n'.join(lines),
        'type': 'scripts_list',
        'data': scripts,
    }


def handle_unknown_scripts(team, params):
    from apps.scripts.models import Script

    unknown = list(
        Script.objects.filter(website__team=team, is_active=True, provider='unknown')
        .select_related('website')
        .order_by('website__domain')[:20]
    )
    if not unknown:
        return {
            'reply': "✅ No unknown scripts detected! All your third-party scripts are identified.",
            'type': 'no_unknowns',
            'data': [],
        }

    lines = [f"• **{s.website.domain}** — `{s.src_url[:60]}...`" if len(s.src_url) > 60 else f"• **{s.website.domain}** — `{s.src_url}`" for s in unknown]
    return {
        'reply': (
            f"⚠️ **{len(unknown)} unknown script(s) found** — these are unclassified third-party scripts that may need review:\n\n"
            + '\n'.join(lines)
        ),
        'type': 'unknown_scripts',
        'data': [{'website': s.website.domain, 'src_url': s.src_url} for s in unknown],
    }


def handle_high_alerts(team, params):
    from apps.scripts.models import ScriptChange

    changes = list(
        ScriptChange.objects.filter(
            website__team=team,
            acknowledged_at__isnull=True,
            severity__in=['high', 'critical'],
        )
        .select_related('website')
        .order_by('-created_at')[:10]
    )
    if not changes:
        return {
            'reply': "✅ No high or critical severity alerts! Your sites look safe.",
            'type': 'no_alerts',
            'data': [],
        }

    lines = [
        f"• 🚨 **{c.website.domain}** — {c.description[:80]}"
        for c in changes
    ]
    return {
        'reply': f"**{len(changes)} high/critical alert(s) requiring attention:**\n\n" + '\n'.join(lines),
        'type': 'alerts_list',
        'data': [{'id': str(c.id), 'website': c.website.domain, 'severity': c.severity, 'description': c.description} for c in changes],
    }


def handle_list_forms(team, params):
    try:
        from apps.scripts.models import DetectedForm

        forms = list(
            DetectedForm.objects.filter(website__team=team)
            .select_related('website')
            .order_by('website__domain')[:20]
        )
        if not forms:
            return {
                'reply': "No forms detected yet. Make sure the tracking snippet is installed and visitors have loaded your pages.",
                'type': 'empty',
                'data': [],
            }

        lines = [f"• **{f.website.domain}** — {f.form_action or 'no action'} ({len(f.fields or [])} fields)" for f in forms]
        return {
            'reply': f"**Detected forms ({len(forms)} total):**\n\n" + '\n'.join(lines),
            'type': 'forms_list',
            'data': [{'website': f.website.domain, 'form_action': f.form_action} for f in forms],
        }
    except Exception:
        return {'reply': "Unable to retrieve forms. Please visit the website detail page.", 'type': 'error', 'data': None}


def handle_list_websites(team, params):
    from apps.websites.models import Website

    sites = list(Website.objects.filter(team=team).order_by('name')[:25])
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
            f"• {_SEV_EMOJI.get(c.severity, '•')} **{c.website.domain}** — {c.change_type.replace('_', ' ')} ({c.severity}){ack}"
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

        clients = list(Client.objects.filter(team=team, status='active').order_by('name')[:25])
        total = Client.objects.filter(team=team).count()
        if not clients:
            return {
                'reply': "You don't have any clients yet. Go to **Clients** to add or import them.",
                'type': 'empty',
                'data': [],
            }

        lines = []
        for c in clients:
            hosting = c.hosting_platform.capitalize() if c.hosting_platform else '—'
            lines.append(f"• **{c.name}** — {c.website_url or 'no URL'} ({hosting})")

        note = f"\n\n_Showing {len(clients)} active of {total} total clients._" if total > len(clients) else ''
        return {
            'reply': f"**Active clients ({len(clients)}):**\n\n" + '\n'.join(lines) + note,
            'type': 'clients_list',
            'data': [{'id': str(c.id), 'name': c.name, 'website_url': c.website_url} for c in clients],
        }
    except Exception:
        return {
            'reply': "Unable to retrieve clients. Please visit the Clients section.",
            'type': 'error',
            'data': None,
        }


def handle_check_client(team, params):
    try:
        from apps.clients.models import Client

        query = params.get('query', '').strip()
        if not query:
            return handle_list_clients(team, params)

        client = Client.objects.filter(
            Q(name__icontains=query) | Q(website_url__icontains=query),
            team=team,
        ).first()

        if not client:
            return {
                'reply': f"I couldn't find a client matching **{query}**. Try **clients** to see the full list.",
                'type': 'not_found',
                'data': {'query': query},
            }

        hosting = client.hosting_platform.capitalize() if client.hosting_platform else 'Unknown'
        access = client.domain_access_location or 'Not recorded'
        built = client.website_built_by_digi or 'Unknown'
        maintained = client.website_maintained_by_digi or 'Unknown'
        status_emoji = '✅' if client.status == 'active' else '⏸️'

        return {
            'reply': (
                f"**{client.name}** {status_emoji}\n"
                f"Website: {client.website_url or '—'}\n"
                f"Hosting: {hosting}\n"
                f"Domain access: {access}\n"
                f"Built by Digi: {built}\n"
                f"Maintained by Digi: {maintained}"
            ),
            'type': 'client_detail',
            'data': {'id': str(client.id), 'name': client.name},
        }
    except Exception:
        return {'reply': "Unable to retrieve client details.", 'type': 'error', 'data': None}


def handle_summary(team, params):
    from apps.monitors.models import Monitor
    from apps.scripts.models import ScriptChange, Script
    from apps.websites.models import Website

    total_sites = Website.objects.filter(team=team).count()
    critical_sites = Website.objects.filter(team=team, status='critical').count()
    warning_sites = Website.objects.filter(team=team, status='warning').count()
    total_monitors = Monitor.objects.filter(team=team).count()
    down_monitors = Monitor.objects.filter(team=team).filter(Q(status='down') | Q(status='degraded')).count()
    pending = ScriptChange.objects.filter(website__team=team, acknowledged_at__isnull=True).count()
    high_risk = ScriptChange.objects.filter(
        website__team=team, acknowledged_at__isnull=True, severity__in=['high', 'critical']
    ).count()
    unknown_scripts = Script.objects.filter(website__team=team, is_active=True, provider='unknown').count()

    try:
        from apps.clients.models import Client
        total_clients = Client.objects.filter(team=team, status='active').count()
        clients_str = f"\n👥 Active clients: **{total_clients}**"
    except Exception:
        clients_str = ''

    site_detail = f" ({critical_sites} critical, {warning_sites} warning)" if (critical_sites or warning_sites) else " (all healthy ✅)"
    mon_detail = f" (**{down_monitors} down** ⚠️)" if down_monitors else " (all up ✅)"
    risk_detail = f" ({high_risk} high-risk 🚨)" if high_risk else ''
    unknown_detail = f" (**{unknown_scripts} unknown** ⚠️)" if unknown_scripts else ''

    return {
        'reply': (
            "**Dashboard Summary**\n\n"
            f"🌐 Websites: **{total_sites}** total{site_detail}\n"
            f"📡 Monitors: **{total_monitors}** total{mon_detail}\n"
            f"🔔 Pending alerts: **{pending}**{risk_detail}\n"
            f"🔍 Unknown scripts: **{unknown_scripts}**{unknown_detail}"
            f"{clients_str}"
        ),
        'type': 'summary',
        'data': {
            'total_sites': total_sites,
            'critical_sites': critical_sites,
            'total_monitors': total_monitors,
            'down_monitors': down_monitors,
            'pending_changes': pending,
            'high_risk': high_risk,
            'unknown_scripts': unknown_scripts,
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
            "5. Scripts and forms will start appearing within minutes ✅"
        ),
        'type': 'onboard_instructions',
        'data': {'domain': query},
    }


def handle_fallback(team, params):
    return {
        'reply': (
            "I'm not sure what you're asking. Here are some things I can help with:\n\n"
            "• Type **summary** for a dashboard overview\n"
            "• Type **alerts** to see pending issues\n"
            "• Type **check [domain]** for a website status\n"
            "• Type **help** to see all commands"
        ),
        'type': 'fallback',
        'data': None,
    }


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

_HANDLERS = {
    'help': handle_help,
    'check_website': handle_check_website,
    'website_scripts': handle_website_scripts,
    'list_scripts': handle_list_scripts,
    'unknown_scripts': handle_unknown_scripts,
    'high_alerts': handle_high_alerts,
    'list_forms': handle_list_forms,
    'list_websites': handle_list_websites,
    'list_monitors': handle_list_monitors,
    'monitors_down': handle_monitors_down,
    'list_alerts': handle_list_alerts,
    'list_changes': handle_list_changes,
    'list_clients': handle_list_clients,
    'check_client': handle_check_client,
    'summary': handle_summary,
    'onboard_website': handle_onboard_website,
    'fallback': handle_fallback,
}


def process_message(team, message: str) -> dict:
    intent, params = detect_intent(message)
    handler = _HANDLERS.get(intent, handle_fallback)
    result = handler(team, params)
    # Attached here rather than in each handler so a new intent gets follow-ups
    # for free, and can never ship a reply that dead-ends the conversation.
    result['suggestions'] = suggest(result)
    return result
