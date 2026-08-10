"""Alerting on failed form submissions.

A form error is stored only when it looks like a server-side failure (see
`apps.scripts.form_errors`), which makes every stored row worth telling someone
about — a contact form that silently stopped mailing is lost business, and
nobody discovers it by watching the dashboard.

The cooldown is the whole design problem. Every visitor who hits the broken form
posts another error, so the naive "one alert per row" is a message per visitor.
Alerts are keyed on (website, form_id) and stay quiet for `ALERT_COOLDOWN` after
the first one: the form is already known-broken, and a second message adds
nothing until someone has had a chance to fix it.

Nothing here raises. The caller is the public ingest endpoint's task — a ClickUp
outage or a bad email channel must not lose the stored error.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

# Imported into this namespace so the alert path shares the monitors' notion of
# "post to whichever ClickUp target this channel configures" (chat or task).
from apps.monitors.notifications import post_clickup, resolve_channels

logger = logging.getLogger(__name__)

# One alert per broken form per day. Long because the fix is human-paced: the
# developer who reads the first message is still working on it an hour later.
ALERT_COOLDOWN = timedelta(days=1)

# Ceiling on alerts one website can raise in a cooldown window. The per-form
# cooldown is keyed on `form_id`, which arrives on the unauthenticated ingest
# endpoint — a caller minting a fresh id per request mints a fresh cooldown key
# with it, and every one would be a ClickUp message and an email. Ten distinct
# genuinely-broken forms on a single site in one day is already implausible;
# past that the honest reading is a flood, and the rows are still all stored.
MAX_ALERTS_PER_WEBSITE = 10

EMOJI = "📩"
TITLE = "has a failing form"


def _fields(error) -> list[tuple[str, str]]:
    """Labelled facts for the channel message — what broke, where, and how it reads."""
    form = error.source or "Form"
    if error.form_id:
        form = f"{form} ({error.form_id})"
    return [
        ("Form", form),
        ("Page", error.page_url),
        ("Error", error.message),
        ("First seen", timezone.localtime(error.created_at).strftime("%d %b %Y, %H:%M %Z").strip()),
    ]


def _email_message(error) -> tuple[str, str]:
    website = error.website
    label = website.name or website.domain
    subject = f"[Digivault] Form submission failing on {website.domain}"
    detail = "\n".join(f"{name}: {value}" for name, value in _fields(error) if str(value).strip())
    body = (
        f"A form on {label} ({website.domain}) is failing to submit.\n\n"
        f"{detail}\n\n"
        "This is a server-side failure reported by visitors, not a validation "
        "message. Log in to Digivault to review the form's error history."
    )
    return subject, body


def _recently_alerted(error) -> bool:
    """True when this form already raised an alert inside the cooldown.

    Keyed on alerts sent, not errors stored: counting rows would keep a
    permanently broken form silent forever, because there is always a recent
    row. Counting alerts re-reports it once a cooldown instead.
    """
    from apps.scripts.models import FormSubmissionError

    return (
        FormSubmissionError.objects.filter(
            website_id=error.website_id,
            form_id=error.form_id,
            alerted_at__gte=timezone.now() - ALERT_COOLDOWN,
        )
        .exclude(pk=error.pk)
        .exists()
    )


def _website_at_ceiling(error) -> bool:
    """True when this site has already spent its alert budget for the window.

    Counts distinct forms, not rows: the per-form cooldown stamps one row per
    form, so this is "how many separate forms have shouted today".
    """
    from apps.scripts.models import FormSubmissionError

    spent = (
        FormSubmissionError.objects.filter(
            website_id=error.website_id,
            alerted_at__gte=timezone.now() - ALERT_COOLDOWN,
        )
        .exclude(pk=error.pk)
        .values("form_id")
        .distinct()
        .count()
    )
    return spent >= MAX_ALERTS_PER_WEBSITE


def _send_email(channel, error) -> None:
    addresses = channel.config.get("addresses", [])
    if not addresses:
        logger.warning("Email channel %s has no addresses", channel.id)
        return
    subject, body = _email_message(error)
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "alerts@digivault.digilatics.co")
    send_mail(subject, body, from_email, addresses, fail_silently=False)


def _send_clickup(channel, error) -> None:
    from apps.integrations import chat

    text = chat.build_message(
        error.website, emoji=EMOJI, title=TITLE, fields=_fields(error)
    )
    if not post_clickup(channel.config, text):
        logger.warning("ClickUp channel %s has no api_token or target", channel.id)


_SENDERS = {
    "email": _send_email,
    "clickup": _send_clickup,
}


def _announce_in_team_channel(error) -> None:
    """Post the failure into the team's shared ClickUp feed, best-effort.

    Independent of the configured channels below — a team with none still wants
    a broken form in its feed, and this is the path that pings the site's
    managers by ClickUp id.
    """
    from apps.integrations import chat

    try:
        chat.notify_problem(
            error.website,
            subject=f"form:{error.website_id}:{error.form_id}",
            title=TITLE,
            fields=_fields(error),
            emoji=EMOJI,
        )
    except Exception:
        logger.exception("Team channel announce failed for form error %s", error.id)


def notify_form_error(error) -> bool:
    """Alert on one stored FormSubmissionError.

    Returns True when the alert was raised, False when the cooldown swallowed it.
    """
    if _recently_alerted(error):
        logger.info(
            "Form %s on website %s already alerted within cooldown; staying quiet",
            error.form_id, error.website_id,
        )
        return False

    if _website_at_ceiling(error):
        logger.warning(
            "Website %s hit the form-alert ceiling (%s per %s); staying quiet",
            error.website_id, MAX_ALERTS_PER_WEBSITE, ALERT_COOLDOWN,
        )
        return False

    # Stamped before delivery, not after: a channel that hangs or throws must
    # not leave the form un-stamped and every following visitor re-alerting.
    error.alerted_at = timezone.now()
    error.save(update_fields=["alerted_at"])

    _announce_in_team_channel(error)

    for channel in resolve_channels(error.website):
        sender = _SENDERS.get(channel.channel_type)
        if sender is None:
            continue
        try:
            sender(channel, error)
            logger.info(
                "Form error %s delivered via %s (%s)", error.id, channel.name, channel.channel_type
            )
        except Exception:
            logger.exception("Form error %s delivery failed via %s", error.id, channel.name)

    return True
