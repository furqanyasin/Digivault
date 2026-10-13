"""Celery tasks for script processing.

The ingest view accepts the HTTP request immediately (202 Accepted) and
delegates all heavy work here so the snippet endpoint stays under 50ms.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import time
from collections import Counter
from datetime import datetime, timedelta
from urllib.parse import urlparse

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.scripts import presence
from apps.scripts.classifier import ScriptClassifier
from apps.scripts.monitored import tag_identity
from apps.scripts.suspicion import SEVERITY_HIGH, analyse
from apps.scripts.diff_engine import DiffEngine
from apps.scripts.models import DetectedForm, Script, ScriptChange, ScriptSnapshot
from apps.scripts.normalize import (
    normalize_page_url,
    normalize_script_url,
    resolve_form_action,
)
from apps.scripts.recipient_changes import record_recipient_change
from apps.scripts.recipients import all_recipients, build_recipients
from apps.scripts.wp_assets import diff_assets
from apps.site_health.models import SiteEvent
from apps.websites.models import Website

# ---------------------------------------------------------------------------
# Script noise filter
# ---------------------------------------------------------------------------

def _internal_hosts() -> frozenset[str]:
    """Stacks Monitor's own infra hosts — the tracking snippet and dashboard.

    These must never be tracked as third-party scripts on a client site: the
    snippet (`/api/s.js`) is served from here, so the page reports it like any
    other script and it would otherwise log a high-severity "added" change that
    the UI hides (internal domain) yet which pins the site to 'critical'.
    """
    hosts = set()
    for url in (getattr(settings, "PRODUCT_URL", ""), getattr(settings, "SNIPPET_CDN_URL", "")):
        host = urlparse(url or "").netloc.lower().removeprefix("www.")
        if host:
            hosts.add(host)
    return frozenset(hosts)


def _should_track_script(src: str, website_domain: str) -> bool:
    """Whether `src` belongs on this site's inventory and change log.

    Only tags from the monitored vendors (monitored.VENDORS: Google, HubSpot,
    Hotjar, WhatConverts, ClickUp, GoHighLevel), and only the tag the site
    installed — not the files its loader fetches afterwards. Everything else is
    dropped here, before it can mint a Script row or a ScriptChange: an agency
    watching six vendors does not want an alert every time a consent banner, a
    CDN or somebody else's pixel changes.

    The one exception is a URL carrying high-confidence signs of injected code
    (obfuscation markers, SEO-spam keywords, a bare IP or a shortener host).
    That is not a vendor at all, and a vendor allowlist must not be the rule
    that hides a hack. The weaker "machine-generated hostname" signal is not
    enough on its own — ordinary vendors trip it (WhatConverts serves from
    `ksrndkehqnwntyxlhgto.com`).

    Raw ScriptSnapshot rows still record everything, for audit.
    """
    # Relative URLs are always self-hosted.
    if not src.startswith(("http://", "https://", "//")):
        return False

    parsed = urlparse(src if not src.startswith("//") else "https:" + src)
    script_host = parsed.netloc.lower().removeprefix("www.")

    # Stacks Monitor's own snippet / dashboard — never a client's third-party script.
    if script_host in _internal_hosts():
        return False

    # Self-hosted: same domain or any subdomain of the site.
    site = website_domain
    if site.startswith(("http://", "https://")):
        site = urlparse(site).netloc
    site = site.lower().removeprefix("www.")
    if site and (script_host == site or script_host.endswith("." + site)):
        return False

    if tag_identity(src):
        return True
    return analyse(src, site_domain=website_domain).severity == SEVERITY_HIGH


# ---------------------------------------------------------------------------
# Comparison windows
# ---------------------------------------------------------------------------

# How many *page loads* make up "what this page carries now", and the same
# number again for the baseline it is compared against.
#
# A single snapshot is NOT an inventory of a page — it is one observation of it.
# The snippet posts at DOMContentLoaded, again at 2.5s, and again after each DOM
# mutation burst for 30s, so the first post of every page load predates the tags
# GTM injects (GA4, Meta Pixel, Clarity, Hotjar, HubSpot). Diffing consecutive
# snapshots made that partial capture indistinguishable from an uninstall: every
# page load reported the whole marketing stack as removed and then added again,
# forever, on every page of every site.
#
# Comparing the union of a run of observations against the union of the run
# before it fixes that — an absence has to hold across the run before it counts
# as a removal. What the run has to be measured in is the part that was wrong.
# Counted in snapshots (it was 5), the window silently depended on how chatty
# the page is: one real load of a GTM site posts six or more times within three
# seconds, so both windows fit *inside a single page load* and the diff compared
# a load against itself while it was still loading. Live data from one such
# page: six posts across three seconds carrying 35, 39, 36, 37, 36 and 37
# scripts — and that four-script spread, pure mid-load capture order, is what
# surfaced as a daily added/removed pair for the whole marketing stack.
#
# Counted in loads, the run means what the comment above always claimed: a tag
# must be missing from every post of three consecutive loads of that page
# before it is called removed.
_DIFF_LOADS = 3

# One observation bucket. All of a page load's posts land within the snippet's
# 30s MutationObserver window, so a 60-second bucket holds a whole load.
_LOAD_BUCKET = timedelta(seconds=60)

# Hard cap on rows pulled to build the two windows, since every row carries a
# whole page's script list and this runs on every post.
#
# It bounds the windows by *posts* while they are defined in *buckets*, so a
# page posting more than ~20 times a minute can fill all six buckets' worth of
# rows with three buckets of traffic and leave the baseline window empty. That
# fails toward the bootstrap path — the baseline becomes a subset of the current
# window, so nothing can look removed — which is the right direction: a very
# busy page under-reports a removal rather than inventing one.
_SNAPSHOT_FETCH_CAP = 120


def _group_into_loads(
    rows: list[tuple], bucket: timedelta = _LOAD_BUCKET
) -> list[list[list[dict]]]:
    """Split newest-first (captured_at, scripts_data) rows into observation runs.

    Returns runs newest-first, each a list of that run's `scripts_data`.

    Bucketed on absolute time rather than on the gap between posts. Chaining on
    gaps looks more precise and fails badly under traffic: a page getting a
    visit every twenty seconds has no gap anywhere in its history, so every post
    it ever received collapses into one unbounded "load", leaving the baseline
    window permanently empty and removal detection permanently off. A fixed
    bucket cannot chain — it is 60 seconds wide whatever the traffic — so the
    windows degrade the right way at both ends: on a quiet page three buckets
    are three separate visits, and on a busy one they are three minutes of all
    its traffic unioned together, which is more evidence for a removal, not
    less.

    A load straddling a bucket boundary is split, and harmless: the windows are
    unions three buckets wide, so the early partial post is still unioned with
    the settled posts either side of it.
    """
    seconds = max(int(bucket.total_seconds()), 1)
    loads: list[list[list[dict]]] = []
    current: list[list[dict]] = []
    current_bucket = None
    for captured_at, scripts_data in rows:
        which = int(captured_at.timestamp()) // seconds
        if current_bucket is not None and which != current_bucket:
            loads.append(current)
            current = []
        current.append(scripts_data or [])
        current_bucket = which
    if current:
        loads.append(current)
    return loads


# Written by the two server-side scan entry points (the websites viewset `scan`
# action and websites.passive_scan_website). The difference it marks is between
# "this tag is not on the page" and "this tag is not in the markup and may still
# be injected by GTM".
_SERVER_SCAN_VERSION = ScriptSnapshot.SERVER_SCAN_VERSION


def _is_server_scan(payload: dict) -> bool:
    return payload.get("snippet_version") == _SERVER_SCAN_VERSION


# How long a reported change stays suppressed after it is acknowledged. Without
# this, dedupe only skipped changes that were still open, so acknowledging one
# re-armed it for the next page load — the opposite of what acknowledging means.
# A tag that goes missing again months later is genuinely news; one that does so
# the same afternoon is the same event.
_CHANGE_COOLDOWN = timedelta(days=7)


def _window_scripts(rows: list[list[dict]], keep=None) -> list[dict]:
    """Collapse newest-first snapshot rows into one script dict per identity.

    `rows` are `scripts_data` lists ordered newest first; the newest observation
    of a given normalized URL wins, so attribute comparisons (location, inline
    hash) still see current values rather than stale ones.
    """
    merged: dict[str, dict] = {}
    for scripts in rows:
        for script in scripts:
            src = (script.get("src") or "").strip()
            if not src or (keep and not keep(script)):
                continue
            merged.setdefault(normalize_script_url(src), script)
    return list(merged.values())


# ---------------------------------------------------------------------------
# What counts as added, and what counts as removed
# ---------------------------------------------------------------------------
#
# Both used to come straight out of the per-page window diff above, and that
# is what made the change log repeat itself. "Added" meant "in this page's
# current window and not in its previous one" — so a tag the site had carried
# for a year was announced again whenever one page's window happened to lack
# it, held back only by a seven-day cooldown, which is why the same tags came
# back week after week. "Removed" meant "missing from three buckets of one
# page", which three visitors declining cookies satisfies. See presence.py.
#
# The inventory is the site's, so both are now judged against it:
#   * added   — an identity this website has never had a Script row for, or one
#               that returns after its removal was reported *and acknowledged*;
#   * removed — confirmed by presence.confirmed_absences on this page's own
#               history, and only if no page of the site has seen it since.
# A tag reappearing while its removal is still open closes that removal: the
# alert was wrong, or the problem fixed itself, and either way nothing is left
# for anyone to do. The window diff still supplies url_changed (for identities
# that are new) and the attribute changes, which is what it is good at.

# Evidence for a removal is drawn from more history than the diff windows need,
# so it is fetched separately and only once per observation bucket.
_EVIDENCE_FETCH_CAP = 300

# A bucket is only complete once the snippet can have stopped posting into it:
# its MutationObserver runs for 30s after load, so a bucket whose newest post is
# younger than this may still be receiving the tags GTM injects late.
_LOAD_SETTLE = timedelta(seconds=45)


def _inventory_changes(
    website: Website, observed: list[dict], window_changes: list
) -> tuple[list, set[int], bool]:
    """Judge this post's scripts against the site's inventory.

    Returns `(changes, cooldown_exempt, reactivated)`. `cooldown_exempt` holds
    the `id()` of each "returned" change: those follow a removal someone has
    acknowledged, so they are news even inside `_CHANGE_COOLDOWN`.
    """
    ct = ScriptChange.ChangeType
    by_ident = {normalize_script_url(s["src"]): s for s in observed}
    known = {
        row.normalized_url: row
        for row in Script.objects.filter(
            website=website, normalized_url__in=list(by_ident)
        )
    }
    swaps = {
        c.src_url: c for c in window_changes if c.change_type == ct.URL_CHANGED
    }
    changes = [
        c for c in window_changes
        if c.change_type not in (ct.ADDED, ct.REMOVED, ct.URL_CHANGED)
    ]
    exempt: set[int] = set()
    reactivated = False

    for ident, script in by_ident.items():
        row = known.get(ident)
        if row is None:
            # New to the site. A 1-to-1 swap in this page's window is still the
            # calmer, truer description of a versioned widget file.
            changes.append(swaps.get(ident) or DiffEngine._build_added(ident, script))
            continue
        if row.is_active:
            continue
        reactivated = True
        last_removal = (
            ScriptChange.objects.filter(
                website=website, script=row, change_type=ct.REMOVED
            )
            .order_by("-created_at")
            .first()
        )
        if last_removal is None:
            # Retired silently (url swap, stale sweep, noise) — never announced
            # as gone, so its return is not announced either.
            continue
        if last_removal.acknowledged_at is None:
            ScriptChange.objects.filter(pk=last_removal.pk).update(
                acknowledged_at=timezone.now()
            )
            continue
        added = DiffEngine._build_added(ident, script)
        label = (
            DiffEngine._label(ident, added.provider)
            if added.provider != "unknown"
            else ident[:120]
        )
        returned = dataclasses.replace(
            added, description=f"Script returned after removal: {label}"
        )
        exempt.add(id(returned))
        changes.append(returned)

    return changes, exempt, reactivated


def _confirmed_removals(website: Website, page_snapshots, is_trackable) -> list:
    """REMOVED changes this page's history is confident about. See presence.py."""
    rows = list(
        page_snapshots.order_by("-captured_at")
        .values_list("captured_at", "scripts_data")[:_EVIDENCE_FETCH_CAP]
    )
    seconds = max(int(_LOAD_BUCKET.total_seconds()), 1)
    settled_before = timezone.now() - _LOAD_SETTLE
    identity: dict[str, str | None] = {}

    # [bucket, newest captured_at, oldest captured_at, identities]
    buckets: list[list] = []
    for captured_at, scripts in rows:
        which = int(captured_at.timestamp()) // seconds
        if not buckets or buckets[-1][0] != which:
            buckets.append([which, captured_at, captured_at, set()])
        load = buckets[-1]
        load[2] = captured_at
        for script in scripts or []:
            src = (script.get("src") or "").strip()
            if not src:
                continue
            if src not in identity:
                identity[src] = normalize_script_url(src) if is_trackable(script) else None
            if identity[src]:
                load[3].add(identity[src])

    # Loads that may still be posting are not evidence of an absence — but what
    # they have already seen (this very post included) is evidence of presence.
    seen_just_now: set[str] = set()
    while buckets and buckets[0][1] >= settled_before:
        seen_just_now |= buckets.pop(0)[3]
    confirmed = presence.confirmed_absences([b[3] for b in buckets])
    for ident in seen_just_now:
        confirmed.pop(ident, None)
    if not confirmed:
        return []

    removals = []
    for row in Script.objects.filter(
        website=website, is_active=True, normalized_url__in=list(confirmed)
    ):
        absent_since = buckets[confirmed[row.normalized_url] - 1][2]
        # Another page has loaded it since this one stopped: still installed.
        if row.last_seen_at and row.last_seen_at >= absent_since:
            continue
        removals.append(DiffEngine._build_removed(row.normalized_url, {
            "src": row.src_url,
            "location": row.location,
            "is_async": row.is_async,
            "is_defer": row.is_defer,
            "is_inline": row.is_inline,
            "inline_hash": row.inline_hash,
            "wp_plugin": row.wp_plugin,
        }))
    return removals


logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=10,
    name="scripts.process_ingest_payload",
)
def process_ingest_payload(self, site_id: str, payload: dict) -> None:
    """Process one snippet ingest payload as it arrives.

    The unbatched path, and the one every site uses unless it is listed in
    INGEST_BATCH_SITES (see apps/scripts/ingest_batch.py). Both paths run the
    same `_ingest_observations`; this one hands it a batch of one.
    """
    try:
        website = Website.objects.get(site_id=site_id)
    except Website.DoesNotExist:
        logger.warning("process_ingest_payload: unknown site_id %s", site_id)
        return

    try:
        _ingest_observations(website, [Observation(payload)])
    except Exception as exc:
        logger.exception("process_ingest_payload failed for site_id=%s", site_id)
        raise self.retry(exc=exc)


@dataclasses.dataclass(frozen=True)
class Observation:
    """One snippet post. `received_at` is when it arrived; None means now."""

    payload: dict
    received_at: datetime | None = None

    @property
    def scripts(self) -> list[dict]:
        return self.payload.get("scripts", [])


def _ingest_observations(website: Website, observations: list[Observation]) -> None:
    """Save, diff and record a run of posts for one page, from one source.

    Steps:
    1. Save a ScriptSnapshot per post, stamped with its arrival time.
    2. Build the page's comparison windows from its snapshot history.
    3. Decide what changed: the window diff, judged against the inventory.
    4. Upsert Script records.
    5. Persist ScriptChange records and dispatch their alerts.
    6. Upsert detected forms.
    7. Touch website.last_seen_at for real browser snippet traffic.

    `observations` are in arrival order. A batch is several posts of one
    page's loads, processed under one lock and one diff instead of one each:
    the windows are unions of 60s buckets, so a load's six or more posts were
    always going to be unioned into the same window anyway. Everything that
    is per *post* rather than per *window* — the raw snapshot, the WordPress
    asset comparison, the arrival time — is still done per post.
    """
    first = observations[0].payload
    # Normalized so /contact, /contact/ and /contact?utm=… are one page.
    page_url: str = normalize_page_url(first["page_url"])
    # A batch never mixes sources: only browser posts are batched.
    server_scan = _is_server_scan(first)
    newest_first = list(reversed(observations))

    def _is_trackable(s: dict) -> bool:
        src = s.get("src", "")
        if not src:
            return False
        if "/wp-includes/" in src or "/wp-admin/" in src:
            return False
        return _should_track_script(src, website.domain)

    with transaction.atomic():
        # Serialize all ingest decisions for this website. The snippet
        # posts several observations per page load and different pages can
        # arrive concurrently; locking only near change creation lets two
        # transactions both diff against the same baseline and create the
        # same logical alert.
        lock_requested = time.monotonic()
        website = Website.objects.select_for_update().get(pk=website.pk)
        lock_acquired = time.monotonic()

        # --- 1. Save snapshots (raw — unfiltered for audit purposes) ---
        # One per post, stamped with when it *arrived*: a batch is written some
        # seconds after its posts came in, and the load buckets below are cut
        # on captured_at.
        now = timezone.now()
        batch_pks = [
            ScriptSnapshot.objects.create(
                website=website,
                page_url=page_url,
                scripts_data=o.scripts,
                user_agent=o.payload.get("user_agent", ""),
                snippet_version=o.payload.get("snippet_version", ""),
                captured_at=o.received_at or now,
            ).pk
            for o in observations
        ]

        # --- 2. Build the two comparison windows for this page ---
        # Newest first, this snapshot included. One query serves both
        # windows; see _DIFF_LOADS for why a single snapshot can't be one,
        # and why the windows are counted in page loads rather than posts.
        #
        # Restricted to snapshots from the same *source*, because the two
        # sources do not observe the same thing. A server-side scan reads
        # static HTML and can never see what GTM injects at runtime; a
        # browser can. Mixing them means a run of scans eventually pushes
        # every browser snapshot out of the window, and the union then loses
        # Hotjar, HubSpot and every other injected tag — a removal reported
        # from an observation structurally incapable of seeing them. Diffing
        # scan against scan keeps removal detection working on sites with no
        # snippet at all (the scan is the floor), while a snippet site's
        # browser posts are never judged against a view of the page that
        # only ever contained the static tags.
        page_snapshots = ScriptSnapshot.objects.filter(
            website=website, page_url=page_url
        )
        if server_scan:
            page_snapshots = page_snapshots.filter(
                snippet_version=_SERVER_SCAN_VERSION
            )
        else:
            page_snapshots = page_snapshots.exclude(
                snippet_version=_SERVER_SCAN_VERSION
            )
        recent_rows = list(
            page_snapshots
            .order_by("-captured_at")
            .values_list("captured_at", "scripts_data")[:_SNAPSHOT_FETCH_CAP]
        )
        loads = _group_into_loads(recent_rows)
        current_rows = [
            scripts for load in loads[:_DIFF_LOADS] for scripts in load
        ]
        previous_rows = [
            scripts
            for load in loads[_DIFF_LOADS : _DIFF_LOADS * 2]
            for scripts in load
        ]
        if not previous_rows:
            # Bootstrap: this page has less than one full window of history.
            # Compare against everything except these snapshots. Because the
            # current window is the *union* of that same history, it is a
            # superset of the baseline, so nothing can look removed while the
            # window fills — only genuinely new identities surface.
            previous_rows = current_rows[len(observations):]

        # Filter both windows to only third-party analytics/marketing scripts
        # before diffing — self-hosted and utility library changes are noise.
        trackable_current = _window_scripts(current_rows, _is_trackable)
        trackable_previous = _window_scripts(previous_rows, _is_trackable)

        # --- 3. Decide what changed ---
        # The window diff contributes url_changed and attribute changes;
        # added and removed are judged against the site's inventory. See
        # "What counts as added, and what counts as removed" above.
        observed = _window_scripts([o.scripts for o in newest_first], _is_trackable)
        changes, cooldown_exempt, reactivated = _inventory_changes(
            website,
            observed,
            DiffEngine.diff(trackable_previous, trackable_current),
        )
        # Evidence only moves when a load completes, so it is weighed once
        # per bucket — on the post that opens the next one — rather than on
        # all six-plus posts every pageview makes.
        if _opens_a_load(recent_rows, observations, now):
            changes += _confirmed_removals(website, page_snapshots, _is_trackable)

        # --- 3b. WordPress plugin / theme / core changes ---
        # Fed the UNFILTERED lists on purpose: /wp-includes/ is dropped from
        # script tracking as noise, and it is the only place the core version
        # appears.
        #
        # Deliberately NOT windowed like the script diff above. Plugin and
        # theme assets are enqueued into the served HTML, so they are present
        # in the very first post of a page load rather than injected later —
        # the partial-capture problem barely touches them, and windowing
        # would delay "plugin removed", the signal worth having promptly.
        # The batch is recent_rows' first len(observations) rows, so the row
        # after them is the previous snapshot *from the same source*, which is
        # what makes this comparison like-for-like: a browser's DOM and a scan's
        # static HTML can disagree about an enqueued asset without either
        # changing. Each post is then compared with the one before it, exactly
        # as it would have been had it been processed on its own. Rows are
        # (captured_at, scripts_data) pairs, hence the second index.
        k = len(observations)
        before = recent_rows[k][1] if len(recent_rows) > k else []
        for o in observations:
            _record_wp_asset_events(website, before, o.scripts)
            before = o.scripts

        # A page nobody had loaded before. Skipped on the very first ingest
        # for a site, when every page is new by definition.
        #
        # Counted across *all* sources, unlike the diff windows above:
        # "discovered" is about the page, not about who saw it, and asking
        # the source-filtered window would announce the same page twice —
        # once when a scan first fetched it, again on its first pageview.
        page_seen_before = (
            ScriptSnapshot.objects.filter(website=website, page_url=page_url)
            .exclude(pk__in=batch_pks)
            .exists()
        )
        if not page_seen_before and (
            ScriptSnapshot.objects.filter(website=website)
            .exclude(pk__in=batch_pks)
            .exists()
        ):
            _record_site_event(
                website,
                SiteEvent.EventType.PAGE_DISCOVERED,
                f"New page found: {page_url}",
                "info",
                {"page_url": page_url},
            )

        # --- 4. Upsert Script records ---
        # This batch's scripts, not the window's: `last_seen_at` is what
        # _confirmed_removals asks "has any page seen it since?", so it must
        # move only when a script was actually observed — and to *when* it was
        # observed. Stamped with the flush time instead, a tag last seen
        # moments before it was removed would read as "seen since the absence
        # began", and the removal would never be reported.
        last_sighting = _last_sightings(newest_first, _is_trackable)
        scripts_moved = False
        for script_data in observed:
            _, scope_changed = _upsert_script(
                website, script_data, page_url,
                seen_at=last_sighting.get(normalize_script_url(script_data["src"])),
            )
            scripts_moved = scripts_moved or scope_changed

        # Collect ALL noise script PKs BEFORE any deactivation runs.
        # If we queried is_active=True after the diff-driven step below,
        # scripts already deactivated there would be missed and their
        # changes never acknowledged, leaving the status stuck at critical.
        #
        # Gated on `derived_needed` rather than run on every post.
        #
        # An observation that sees exactly what the last one saw has changed
        # nothing, and that is the overwhelming majority of them: the
        # snippet posts at DOMContentLoaded, at 2.5s, and once per DOM
        # mutation burst for 30s — six or more times per pageview, per page,
        # per visitor. The three things below are all recomputations of
        # derived state, so running them against an unchanged inventory can
        # only produce the values already stored.
        #
        # The gate is the diff's own answer plus the two other ways state
        # can move: a Script row that did not exist before, and a page
        # nobody had loaded before (which changes the denominator
        # `_update_script_scopes` divides by). `changes` is used rather than
        # `created_changes` because dedupe runs later and a deduped change
        # still means the inventory moved.
        derived_needed = (
            bool(changes) or scripts_moved or reactivated or not page_seen_before
        )

        # This loads every Script row the website has and re-classifies each
        # one in Python. It exists to retire rows stored *before* the
        # tracked-category filter reached ingest — a backfill, not a
        # per-observation concern — so on a busy site it was a full scan of
        # the whole inventory several times per visitor, for nothing.
        all_noise_pks: list = []
        if derived_needed:
            all_noise_pks = [
                s.pk
                for s in Script.objects.filter(website=website).only("pk", "src_url")
                if not _should_track_script(s.src_url, website.domain)
            ]

        # Deactivate exactly what the diff above reported as gone.
        #
        # This used to be a site-wide sweep against `trackable_current`:
        #     .filter(scope=GLOBAL, is_active=True)
        #     .exclude(normalized_url__in=current_urls)
        # `trackable_current` is one page's window; the UPDATE covered the
        # whole website. So any partial capture — the first post of a page
        # load before GTM injects, a first-ever visit, a bounce, or a
        # server-side scan that only ever parses the homepage's static HTML
        # — switched off every site-wide tag the site had. The scope gate
        # made it hit precisely the tags worth watching: a script reaches
        # GLOBAL only once it is on >=80% of pages, so the site-wide
        # marketing stack was the only kind the sweep could reach. A site
        # running GTM, GA4, Hotjar, HubSpot and WhatConverts showed one row.
        #
        # `changes` already answers "is this gone" — from
        # _confirmed_removals, where an absence has to hold across enough
        # completed loads, and on no other page, before it counts. Driving is_active
        # from it means the tab and the change log can never disagree.
        #
        # No scope filter is needed any more. The diff can only name a URL
        # that was in *this page's* previous window, so a tag that simply
        # does not run on this page is never a candidate — it was never in
        # the baseline to go missing from it.
        removed_urls = {
            c.src_url
            for c in changes
            if c.change_type == ScriptChange.ChangeType.REMOVED
        }
        # A URL swap retires the old address too; `src_url` on a
        # URL_CHANGED result is the new one.
        removed_urls |= {
            normalize_script_url(c.old_value["src"])
            for c in changes
            if c.change_type == ScriptChange.ChangeType.URL_CHANGED
            and c.old_value
            and c.old_value.get("src")
        }
        if removed_urls:
            Script.objects.filter(
                website=website,
                normalized_url__in=removed_urls,
                is_active=True,
            ).update(is_active=False)

        # Deactivate noise scripts and auto-acknowledge their changes.
        if all_noise_pks:
            Script.objects.filter(pk__in=all_noise_pks, is_active=True).update(is_active=False)
            ScriptChange.objects.filter(
                website=website,
                script_id__in=all_noise_pks,
                acknowledged_at__isnull=True,
            ).update(acknowledged_at=timezone.now())

        # --- 5. Persist ScriptChange records ---
        created_changes: list[ScriptChange] = []
        for change in changes:
            script_obj = None
            if change.src_url:
                # DiffEngine emits normalized URLs in src_url.
                script_obj = Script.objects.filter(
                    website=website, normalized_url=change.src_url
                ).first()
            # Site-wide dedupe: the diff runs per page, so one genuinely
            # new global script would otherwise log an event per page.
            dup_q = ScriptChange.objects.filter(
                website=website,
                change_type=change.change_type,
            )
            if script_obj:
                dup_q = dup_q.filter(script=script_obj)
            else:
                dup_q = dup_q.filter(description=change.description)
            # Still open, or closed recently — either way the user has
            # already been told about this one. See _CHANGE_COOLDOWN. A tag
            # returning after an acknowledged removal is fresh news.
            already_told = Q(acknowledged_at__isnull=True)
            if id(change) not in cooldown_exempt:
                already_told |= Q(created_at__gte=timezone.now() - _CHANGE_COOLDOWN)
            if dup_q.filter(already_told).exists():
                continue
            created_changes.append(ScriptChange.objects.create(
                website=website,
                script=script_obj,
                change_type=change.change_type,
                severity=change.severity,
                description=change.description,
                old_value=change.old_value,
                new_value=change.new_value,
            ))

        # --- 5b. Dispatch alert notifications for each change ---
        # Only the rows this task created. Selecting by "created since my
        # snapshot" instead swept up changes committed by overlapping ingests
        # for the same website, which had already notified for them
        # themselves — one change turned into a notification per concurrent
        # task, and the client got the same alert several times over.
        from apps.alerts.services import AlertService
        from apps.alerts.tasks import deliver_notification

        # Queued on commit, not inline. A worker is free to pick the task
        # up the instant it is published, and inside this transaction the
        # Notification row it names is not visible to anyone else yet — so
        # delivery either read nothing and dropped the alert, or, on the
        # retry path at the bottom of this function, delivered an alert
        # whose row had just been rolled back. `record_recipient_change`
        # already queued through on_commit for exactly this reason; this
        # path did not.
        for change_record in created_changes:
            notifications = AlertService.dispatch_for_change(change_record)
            for notif in notifications:
                if notif.rule and notif.rule.delivery_mode == "immediate":
                    transaction.on_commit(
                        # Bind the id now — a late-bound closure over the
                        # loop variable would queue the last notification
                        # once per notification.
                        lambda pk=str(notif.pk): deliver_notification.delay(pk)
                    )

        # --- 6. Upsert detected forms ---
        # Every post of a load reports the same forms; an identical report adds
        # nothing the first one did not, so each distinct one is written once.
        seen_forms: set[str] = set()
        for o in observations:
            for form_data in o.payload.get("forms", []):
                key = json.dumps(form_data, sort_keys=True, default=str)
                if key in seen_forms:
                    continue
                seen_forms.add(key)
                _upsert_form(website, page_url, form_data)

        # --- 7. Update scope labels ---
        # Same gate as the noise sweep, and for the same reason: this walks
        # every active script and counts the website's distinct pages across
        # the whole ScriptSnapshot table, which is the largest table in the
        # product. Scope is a function of (which pages a script is on, how
        # many pages exist) and neither moves on an observation that
        # matched the last one.
        if derived_needed:
            _update_script_scopes(website)

        # --- 7. Touch visitor activity only for browser snippet traffic ---
        # Server-side scans use this same pipeline for source-separated
        # snapshots, but they are not evidence that a real visitor loaded
        # the site and must not affect liveness or reporting freshness.
        if not server_scan:
            visited = max(o.received_at or now for o in observations)
            website.last_seen_at = visited
            website.snippet_status = Website.SnippetStatus.INSTALLED
            website.snippet_last_seen_at = visited
            update_fields = [
                "last_seen_at", "snippet_status", "snippet_last_seen_at"
            ]
            if website.snippet_first_seen_at is None:
                website.snippet_first_seen_at = visited
                update_fields.append("snippet_first_seen_at")
            website.save(update_fields=update_fields)

        # Recalculate when this observation moved something. This writes
        # both health_score and status.
        #
        # It used to run unconditionally, with the note that "noise cleanup
        # may have shifted the status even when no new trackable changes
        # occurred" — true, and now covered, because the noise sweep runs
        # under the same gate. What the unconditional version actually cost
        # was eight queries (open changes, domain info, vulnerabilities,
        # pending reviews, monitors, form errors, then two writes) plus a
        # Python pass over every open change, on every one of the six-plus
        # posts each pageview makes, holding the website's row lock while it
        # ran.
        #
        # Nothing is lost by skipping the unchanged case: every input to the
        # score is either something this task just wrote — in which case
        # `derived_needed` is true — or something another writer changed,
        # and those writers already recalculate. Acknowledging a change,
        # a monitor flipping state and the domain check all call this
        # directly, and the time-based deductions decay in the nightly
        # `websites.recalculate_all_health` sweep.
        if derived_needed:
            website.recalculate_health_score()


    _report_lock_contention(
        website.site_id, page_url,
        waited=lock_acquired - lock_requested,
        held=time.monotonic() - lock_acquired,
    )


def _opens_a_load(recent_rows: list[tuple], observations: list[Observation], now) -> bool:
    """Did any post of this batch open a new 60s load bucket for the page?

    Removal evidence is weighed once per bucket, on the post that opens it. A
    post opened its bucket when every row in that bucket is one of this
    batch's — for a single post, exactly "the newest bucket holds one row",
    which is what this used to test directly. Counted from `recent_rows`,
    which holds the page's newest rows and so this batch's.
    """
    seconds = max(int(_LOAD_BUCKET.total_seconds()), 1)

    def bucket(ts):
        return int(ts.timestamp()) // seconds

    in_rows = Counter(bucket(captured_at) for captured_at, _ in recent_rows)
    in_batch = Counter(bucket(o.received_at or now) for o in observations)
    return any(in_rows[b] == n for b, n in in_batch.items())


def _last_sightings(newest_first: list[Observation], is_trackable) -> dict:
    """Identity -> when this batch last saw it (None for an unstamped post)."""
    seen: dict = {}
    for o in newest_first:
        for script in o.scripts:
            src = (script.get("src") or "").strip()
            if not src or not is_trackable(script):
                continue
            seen.setdefault(normalize_script_url(src), o.received_at)
    return seen


# The row lock above serializes every post for a website, and each pageview
# makes six or more. Whether that queueing actually happens in production is
# the one number that decides whether a site should be put on batched ingest
# (INGEST_BATCH_SITES, apps/scripts/ingest_batch.py). Logged only past a
# threshold, so a quiet log means no contention: grep "ingest_lock" over a week
# of worker logs. Batched sites log here too, once per flush.
_LOCK_WAIT_WARN = timedelta(milliseconds=500)
_LOCK_HELD_WARN = timedelta(seconds=2)


def _report_lock_contention(site_id: str, page_url: str, *, waited: float, held: float) -> None:
    if waited < _LOCK_WAIT_WARN.total_seconds() and held < _LOCK_HELD_WARN.total_seconds():
        return
    logger.warning(
        "ingest_lock: site_id=%s page=%s waited_ms=%d held_ms=%d",
        site_id, page_url, waited * 1000, held * 1000,
    )


def _record_site_event(
    website: Website, event_type: str, summary: str, severity: str, details: dict
) -> None:
    """Create a SiteEvent unless that exact change is already recorded.

    Deduped on (website, event_type, summary) rather than a timestamp window: the
    same plugin update is enqueued on every page of the site and re-reported by
    every visitor until the previous snapshot rolls over, so a time window would
    still let duplicates through. The summary carries the slug and both version
    numbers, which makes it a natural key for "this specific change".
    """
    SiteEvent.objects.get_or_create(
        website=website,
        event_type=event_type,
        summary=summary,
        defaults={
            "severity": severity,
            "details": details,
            "category": _category_for(event_type, details),
        },
    )


# Passive events need a category for two reasons: the Change Log filters on it,
# and the passive/attributed merge query narrows by it before comparing details.
_EVENT_CATEGORIES = {
    "plugin_installed": SiteEvent.Category.PLUGINS,
    "plugin_removed": SiteEvent.Category.PLUGINS,
    "plugin_updated": SiteEvent.Category.PLUGINS,
    "theme_changed": SiteEvent.Category.THEMES,
    "core_updated": SiteEvent.Category.CORE,
    "page_discovered": SiteEvent.Category.DISCOVERY,
    "form_recipients_changed": SiteEvent.Category.FORMS,
    "seo_noindex_detected": SiteEvent.Category.SEO,
    "seo_robots_block": SiteEvent.Category.SEO,
    "seo_sitemap_missing": SiteEvent.Category.SEO,
    "seo_meta_changed": SiteEvent.Category.SEO,
}


def _category_for(event_type: str, details: dict) -> str:
    """Best category for a passively-detected event.

    `wp_assets` reports a theme change as `theme_changed` whatever the kind, so
    the details' own `kind` wins where it disagrees with the event type — a core
    update arriving as `core_updated` must not be filed under themes.
    """
    kind = str((details or {}).get("kind") or "").strip().lower()
    if kind == "plugin":
        return SiteEvent.Category.PLUGINS
    if kind == "theme":
        return SiteEvent.Category.THEMES
    if kind == "core":
        return SiteEvent.Category.CORE
    return _EVENT_CATEGORIES.get(event_type, "")


def _record_wp_asset_events(
    website: Website, raw_previous: list[dict], raw_current: list[dict]
) -> None:
    """Record WordPress plugin / theme / core changes seen in script URLs."""
    for ev in diff_assets(raw_previous, raw_current):
        _record_site_event(
            website, ev["event_type"], ev["summary"], ev["severity"], ev["details"]
        )


def _upsert_script(
    website: Website, script_data: dict, page_url: str, seen_at: datetime | None = None
) -> tuple[Script, bool]:
    """Create or update a Script record from one snippet script entry.

    Returns `(script, scope_changed)`. The caller needs the flag because the
    diff cannot supply it: the diff compares one page's window, while scope is
    a property of the whole site. A brand-new row, and a known script turning
    up on a page it had not been seen on, both move it and neither is
    necessarily an `added` change.

    `seen_at` is when the script was observed (a batched post's arrival time);
    None means now.
    """
    stamped = seen_at is not None
    seen_at = seen_at or timezone.now()
    src = script_data["src"]
    classification = ScriptClassifier.classify(src)
    domain = ScriptClassifier.extract_domain(src)
    # Re-assessed on every ingest, not just on create: a URL can start benign and
    # be swapped later, which is exactly the case worth catching.
    suspicion = analyse(src, site_domain=website.domain)

    script, created = Script.objects.get_or_create(
        website=website,
        normalized_url=normalize_script_url(src),
        defaults={
            "src_url": src,
            "src_domain": domain,
            "provider": classification.provider,
            "category": classification.category,
            "location": script_data.get("location", Script.Location.UNKNOWN),
            "is_async": script_data.get("is_async", False),
            "is_defer": script_data.get("is_defer", False),
            "is_inline": script_data.get("is_inline", False),
            "inline_hash": script_data.get("inline_hash", ""),
            "wp_plugin": script_data.get("wp_plugin", ""),
            "wp_post_id": script_data.get("wp_post_id"),
            "seen_on_pages": [page_url],
            "is_suspicious": suspicion.is_suspicious,
            "suspicion_severity": suspicion.severity,
            "suspicion_reasons": list(suspicion.reasons),
        },
    )

    # Whether this script's *scope inputs* moved. Scope is a function of how
    # many of the site's pages carry the script, so a new row and a known row
    # appearing on a page it was not on before are equally significant — and the
    # second is invisible to the diff, which only compares one page's window.
    scope_changed = created

    if created and stamped and seen_at < script.last_seen_at:
        # auto_now stamped the new row with the flush time; a batched sighting
        # happened earlier, and last_seen_at must say when.
        Script.objects.filter(pk=script.pk).update(last_seen_at=seen_at)
        script.last_seen_at = seen_at

    if not created:
        # Update mutable fields and keep seen_on_pages current
        seen = script.seen_on_pages or []
        if page_url not in seen:
            seen.append(page_url)
            scope_changed = True
        Script.objects.filter(pk=script.pk).update(
            is_active=True,
            # Set explicitly: .update() bypasses the field's auto_now, so
            # without this a script confirmed present by every page load still
            # reported the moment its row was created as when we last saw it.
            last_seen_at=seen_at,
            src_url=src,
            src_domain=domain,
            is_suspicious=suspicion.is_suspicious,
            suspicion_severity=suspicion.severity,
            suspicion_reasons=list(suspicion.reasons),
            provider=classification.provider,
            category=classification.category,
            location=script_data.get("location", script.location),
            is_async=script_data.get("is_async", script.is_async),
            is_defer=script_data.get("is_defer", script.is_defer),
            wp_plugin=script_data.get("wp_plugin", script.wp_plugin) or script.wp_plugin,
            seen_on_pages=seen,
        )

    return script, scope_changed


def _upsert_form(website, page_url: str, form_data: dict) -> None:
    """Record one observation of one form, keyed by its structural identity.

    `page_url` is threaded into both the fingerprint and the stored action so
    that a form is one row whichever source saw it. The browser reports
    `form.action`, which resolves an absent or relative attribute against the
    document; the server-side scan reports the attribute verbatim. Left
    unresolved, those are two identities for one form (see
    `resolve_form_action`).
    """
    fingerprint = DetectedForm.compute_fingerprint(form_data, page_url)
    defaults = {
        "form_id": form_data.get("form_id", ""),
        "form_name": form_data.get("form_name", ""),
        # Normalized for the same reason the fingerprint is (see
        # DetectedForm.compute_fingerprint): an action-less form reports the
        # document URL, so storing it raw made the row's action flip between
        # campaign URLs and displayed a UTM-laden action in the UI.
        "form_action": normalize_page_url(
            resolve_form_action(page_url, form_data.get("form_action", "") or "")
        ),
        "form_method": (form_data.get("form_method") or "post").lower(),
        "detection_type": form_data.get(
            "detection_type", DetectedForm.DetectionType.NATIVE
        ),
        "provider": form_data.get("provider", ""),
    }
    # An empty field list is an observation that read nothing, not a form that
    # lost its fields, so it must never overwrite one that has them — the same
    # rule `_apply_page_recipients` applies to recipients, and for the same
    # reason. Two sources reach this row now that identity is shared: the server
    # scan's regex extractor skips inputs with no `name` attribute and reads
    # nothing from a JS-rendered form, and a multi-step form mounts one step at
    # a time. Written through `defaults`, the daily scan wiped the seven fields
    # the browser had reported and the Forms tab read "Fields (0)".
    incoming_fields = form_data.get("fields") or []
    if incoming_fields:
        defaults["fields"] = incoming_fields

    form, _ = DetectedForm.objects.update_or_create(
        website=website,
        page_url=page_url,
        fingerprint=fingerprint,
        defaults=defaults,
    )
    _apply_page_recipients(form, form_data)


def _apply_page_recipients(form: DetectedForm, form_data: dict) -> None:
    """Record the destinations the snippet read out of the page markup.

    Deliberately not part of the upsert's `defaults`, for two reasons.

    A set reported by WordPress — over WP Connect, or read from the site's own
    REST API — is the form's actual configuration, while the markup is only a
    proxy for it, so an ingest must never overwrite one.
    Written through `defaults`, every pageview wiped what the WP Connect route
    had filled in (page-invisible for Elementor/CF7 forms, so the markup reads
    nothing).

    And an empty reading does not clear a stored set. A form is observed several
    times per page load, and one observation missing a `mailto:` action is not
    evidence the action is gone — the same reasoning the diff window applies to
    scripts. That protection only applies once something is on record, though:
    a brand-new row has nothing to lose, so an empty reading still normalizes
    its `recipients` from the model's bare `{}` default to the canonical
    `{"to": [], "cc": [], "bcc": []}` shape.
    """
    raw = form_data.get("recipients") or {}
    recipients = build_recipients(
        to=raw.get("to") or form_data.get("recipient_email", ""),
        cc=raw.get("cc"),
        bcc=raw.get("bcc"),
    )
    # Both of these are the form's actual configuration, read out of the site's
    # own database. The markup is only a proxy for it, and on the plugins that
    # matter it reads nothing at all — so an ingest must never overwrite either.
    if form.recipient_source in (
        DetectedForm.RecipientSource.WORDPRESS,
        DetectedForm.RecipientSource.WP_API,
    ):
        return
    if not any(recipients.values()) and any(all_recipients(form.recipients)):
        return
    if recipients == form.recipients and form.recipient_source == DetectedForm.RecipientSource.PAGE:
        return
    old_recipients = form.recipients
    old_source = form.recipient_source
    form.recipients = recipients
    form.recipient_source = DetectedForm.RecipientSource.PAGE
    form.save(update_fields=["recipients", "recipient_source", "updated_at"])
    record_recipient_change(
        form,
        old_recipients=old_recipients,
        old_source=old_source,
        new_source=DetectedForm.RecipientSource.PAGE,
    )


def _update_script_scopes(website: Website) -> None:
    """Classify each active script as GLOBAL, PAGE_SPECIFIC, or ONE_TIME.

    Rules (per PDF §9.2):
    - Seen on ≥80% of all known pages → GLOBAL
    - Seen on <80% of pages (but >1 page) → PAGE_SPECIFIC
    - Seen on exactly 1 page → ONE_TIME (flag unknown scripts for review)
    """
    total_pages = (
        ScriptSnapshot.objects.filter(website=website)
        .values("page_url")
        .distinct()
        .count()
    )
    if total_pages == 0:
        return

    scripts = Script.objects.filter(website=website, is_active=True)
    for script in scripts:
        seen_count = len(set(script.seen_on_pages or []))

        if seen_count <= 1:
            new_scope = Script.Scope.ONE_TIME
        elif total_pages == 1 or seen_count / total_pages >= 0.8:
            new_scope = Script.Scope.GLOBAL
        else:
            new_scope = Script.Scope.PAGE_SPECIFIC

        if script.scope != new_scope:
            Script.objects.filter(pk=script.pk).update(scope=new_scope)
            # Flag one-time unknown scripts for review
            if new_scope == Script.Scope.ONE_TIME and script.provider == "unknown":
                Script.objects.filter(pk=script.pk).update(
                    review_status=Script.ReviewStatus.PENDING
                )


def _update_website_status(website: Website) -> None:
    """Refresh a website's status.

    Status used to be derived here from open script-change severity alone, which
    let it disagree with `health_score` — a site scoring 42 could still read
    'active'. `Website.recalculate_health_score()` is now the single writer of
    both fields; this stays as a thin delegate because a data migration
    (scripts/0007) and several call sites reference it by name.
    """
    website.recalculate_health_score()


# Unseen on every page for this long, a script is retired from the inventory.
_STALE_SCRIPT_AGE = timedelta(days=30)


@shared_task(name="scripts.purge_old_snapshots")
def purge_old_snapshots() -> int:
    """Delete ScriptSnapshot records older than 90 days.  Chunked to avoid
    long-running transactions.  Scheduled via Celery Beat weekly.
    """
    from django.utils.timezone import timedelta

    cutoff = timezone.now() - timedelta(days=90)
    # Whole months first, once the table has been partitioned (a no-op before
    # that): DROP TABLE is instant and gives the space back. The row-level
    # loop below then only has the month straddling the cutoff left to do.
    from apps.common.partitions import drop_partitions_before

    drop_partitions_before(ScriptSnapshot._meta.db_table, cutoff)
    total_deleted = 0
    chunk_size = 500

    while True:
        ids = list(
            ScriptSnapshot.objects.filter(captured_at__lt=cutoff)
            .values_list("pk", flat=True)[:chunk_size]
        )
        if not ids:
            break
        deleted, _ = ScriptSnapshot.objects.filter(pk__in=ids).delete()
        total_deleted += deleted

    logger.info("purge_old_snapshots: removed %d snapshots", total_deleted)

    # A tag too intermittent for presence.confirmed_absences ever to call gone
    # (see MAX_ABSENT_LOADS) would otherwise read "active" forever. Retired
    # silently — there was never the evidence for an alert — and reactivated
    # silently by _inventory_changes if it turns up again.
    retired = Script.objects.filter(
        is_active=True, last_seen_at__lt=timezone.now() - _STALE_SCRIPT_AGE
    ).update(is_active=False)
    if retired:
        logger.info("purge_old_snapshots: retired %d unseen scripts", retired)
    return total_deleted


@shared_task(name="scripts.deliver_form_error_alert")
def deliver_form_error_alert(error_id: str) -> bool:
    """Alert on a stored form error, off the ingest request's critical path.

    Split out because delivery talks to ClickUp and SMTP, and `/api/ingest/
    form-errors/` is a public snippet endpoint that must answer in milliseconds.
    """
    from apps.scripts import notifications
    from apps.scripts.models import FormSubmissionError

    error = (
        FormSubmissionError.objects.filter(pk=error_id)
        .select_related("website", "website__team", "website__client")
        .first()
    )
    if error is None:
        return False
    return notifications.notify_form_error(error)


def _format_recipients(recipients: dict) -> str:
    """One line naming every destination, with copies labelled.

    A Bcc that reads identically to a To would hide the most interesting case
    this alert exists to surface.
    """
    recipients = recipients if isinstance(recipients, dict) else {}
    parts = list(recipients.get("to") or [])
    parts += [f"{e} (Cc)" for e in recipients.get("cc") or []]
    parts += [f"{e} (Bcc)" for e in recipients.get("bcc") or []]
    return ", ".join(parts) if parts else "nobody"


@shared_task(name="scripts.deliver_recipient_change_alert")
def deliver_recipient_change_alert(event_pk: str) -> bool:
    """Announce a changed form destination in the team's ClickUp channel.

    Queued by `record_recipient_change` on transaction commit, so the HTTP call
    never happens inside the ingest transaction. Returns whether a message was
    posted; `False` covers a team with no channel configured, which is the
    normal case for most teams and not a failure.
    """
    from apps.integrations import chat
    from apps.site_health.models import SiteEvent

    event = (
        SiteEvent.objects.filter(
            pk=event_pk,
            event_type=SiteEvent.EventType.FORM_RECIPIENTS_CHANGED,
        )
        .select_related("website", "website__team")
        .first()
    )
    if event is None:
        # A purge or a manual delete can race the queued task. Not an error.
        logger.debug("deliver_recipient_change_alert: event %s is gone", event_pk)
        return False

    details = event.details or {}
    # The summary already reads "<site> — form “X” <verb>"; the title is the
    # part after the site name, because build_message prefixes the site itself.
    verb = (
        "no longer delivers to anyone"
        if event.severity == SiteEvent.Severity.CRITICAL
        else "changed where it delivers"
    )
    label = details.get("form_label") or "a form"
    fields = [
        ("Form", label),
        ("Page", details.get("page_url", "")),
        ("Was", _format_recipients(details.get("old") or {})),
        ("Now", _format_recipients(details.get("new") or {})),
        (
            "Read from",
            "the site's WordPress form settings"
            if details.get("source") == "wordpress"
            else "the page markup",
        ),
    ]
    if details.get("moved_to_bcc"):
        # Still receiving mail, but no longer a visible destination.
        fields.append(("Moved to Bcc", ", ".join(details["moved_to_bcc"])))

    return chat.notify_problem(
        event.website,
        subject=f"form-recipients:{event.pk}",
        title=f"has a form that {verb}",
        fields=fields,
        emoji="📩",
    )


# Registers scripts.flush_ingest_batch and scripts.sweep_ingest_buffers. Celery
# autodiscovers `tasks` modules only, and nothing else a worker loads is
# guaranteed to import ingest_batch, so without this a worker could receive a
# flush it has never heard of and drop the batch. Imported last: ingest_batch
# reaches back into this module for _ingest_observations.
from apps.scripts import ingest_batch  # noqa: E402,F401
