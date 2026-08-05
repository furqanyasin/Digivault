"""Passive WordPress plugin / theme / core change detection.

WordPress enqueues front-end assets from predictable paths and stamps each with
the version of whatever shipped it:

    /wp-content/plugins/<slug>/js/app.js?ver=3.4.1     → plugin "slug" v3.4.1
    /wp-content/themes/<slug>/main.js?ver=1.8.0        → theme  "slug" v1.8.0
    /wp-includes/js/jquery/jquery.min.js?ver=6.7.1     → WP core        v6.7.1

So install, removal and update are all derivable from script URLs the snippet
already reports — no WordPress-side plugin, no extra collection.

`diff_assets` is pure: it takes two raw snapshot script lists and returns event
dicts. Note it is deliberately fed the *unfiltered* payloads, unlike the script
diff, because `/wp-includes/` is filtered out of script tracking as noise and is
the only place the core version appears.

Two honest limits, both inherent to passive detection rather than bugs:

* A plugin that enqueues no front-end JavaScript is invisible here. SEO, backup,
  security and admin-only plugins commonly fall in that group.
* `?ver=` is set by whoever enqueued the asset. Most plugins pass their own
  version, but some pass the core version, a build hash or nothing at all, in
  which case an update to that plugin cannot be seen.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlsplit

PLUGIN = "plugin"
THEME = "theme"
CORE = "core"

_PLUGIN_RE = re.compile(r"/wp-content/(?:mu-)?plugins/([^/]+)/", re.IGNORECASE)
_THEME_RE = re.compile(r"/wp-content/themes/([^/]+)/", re.IGNORECASE)
_CORE_RE = re.compile(r"/wp-(?:includes|admin)/", re.IGNORECASE)

# A version we can meaningfully compare. Build hashes and cache-busting
# timestamps change on every deploy without the plugin changing, so they would
# manufacture an "updated" event per page load.
_VERSION_RE = re.compile(r"^[0-9]+(?:\.[0-9a-z]+)*$", re.IGNORECASE)


def classify(url: str) -> tuple[str, str] | None:
    """Return (kind, slug) for a WordPress asset URL, or None if it isn't one.

    Core has no slug of its own, so it is reported as ("core", "wordpress") —
    a single identity, since every /wp-includes/ asset carries the same version.
    """
    if not url:
        return None
    m = _PLUGIN_RE.search(url)
    if m:
        return PLUGIN, m.group(1).lower()
    m = _THEME_RE.search(url)
    if m:
        return THEME, m.group(1).lower()
    if _CORE_RE.search(url):
        return CORE, "wordpress"
    return None


def version_of(url: str) -> str:
    """Return the `ver` query value when it looks like a real version number."""
    if not url:
        return ""
    try:
        query = urlsplit(url).query
    except ValueError:
        return ""
    for key, value in parse_qsl(query, keep_blank_values=True):
        if key.lower() == "ver" and _VERSION_RE.match(value or ""):
            return value
    return ""


def _index(scripts: list[dict]) -> dict[tuple[str, str], str]:
    """Map (kind, slug) → best version seen across that asset's scripts."""
    found: dict[tuple[str, str], str] = {}
    for s in scripts or []:
        url = (s.get("src") or "").strip()
        key = classify(url)
        if key is None:
            continue
        # First non-empty version wins; a plugin shipping several files may stamp
        # only some of them, and "" must not overwrite a known version.
        if found.get(key):
            continue
        found[key] = version_of(url)
    return found


# Event shapes returned to the caller, which owns SiteEvent creation. Keeping
# this module free of model imports is what lets it stay a pure function.
def _event(event_type: str, summary: str, severity: str, **details) -> dict:
    return {
        "event_type": event_type,
        "summary": summary,
        "severity": severity,
        "details": details,
    }


def diff_assets(previous: list[dict], current: list[dict], label: str = "") -> list[dict]:
    """Compare two raw snapshot script lists and describe what changed.

    `label` prefixes summaries with the site name so a digest email reads on its
    own. Returns [] when `previous` is empty: the first snapshot for a page would
    otherwise report every plugin on the site as newly installed.
    """
    if not previous:
        return []

    before, after = _index(previous), _index(current)
    events: list[dict] = []

    prefix = f"{label} " if label else ""

    for key in sorted(after.keys() - before.keys()):
        kind, slug = key
        if kind == CORE:
            continue  # core appearing is a detection artefact, not an install
        events.append(
            _event(
                "plugin_installed" if kind == PLUGIN else "theme_changed",
                f"{prefix}{kind} added: {slug}" + (f" v{after[key]}" if after[key] else ""),
                "info",
                kind=kind, slug=slug, version=after[key],
            )
        )

    for key in sorted(before.keys() - after.keys()):
        kind, slug = key
        if kind == CORE:
            continue
        events.append(
            _event(
                "plugin_removed" if kind == PLUGIN else "theme_changed",
                f"{prefix}{kind} removed: {slug}",
                # A plugin vanishing can silently drop tracking or a form, so it
                # is worth more attention than an install.
                "warning",
                kind=kind, slug=slug, version=before[key],
            )
        )

    for key in sorted(before.keys() & after.keys()):
        old, new = before[key], after[key]
        # Both sides must be known: "" -> "3.4.1" means the asset started
        # stamping a version, not that anything was upgraded.
        if not old or not new or old == new:
            continue
        kind, slug = key
        event_type = {
            PLUGIN: "plugin_updated",
            THEME: "theme_changed",
            CORE: "core_updated",
        }[kind]
        what = "WordPress core" if kind == CORE else f"{kind} {slug}"
        events.append(
            _event(
                event_type,
                f"{prefix}{what} updated from v{old} to v{new}",
                "info",
                kind=kind, slug=slug, old_version=old, new_version=new,
            )
        )

    return events
