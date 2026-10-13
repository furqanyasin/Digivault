"""Diff Engine — detects script changes between two snapshots.

Compares a previous and current list of script data dicts and returns a list
of ChangeResult objects.  Pure logic; no database access.  The Celery task
owns persistence.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from apps.scripts.classifier import ScriptClassifier
from apps.scripts.models import ScriptChange
from apps.scripts.normalize import (
    identity_label,
    is_identity_host,
    normalize_script_url,
)


@dataclass(frozen=True)
class ChangeResult:
    change_type: str
    severity: str
    description: str
    old_value: dict | None = None
    new_value: dict | None = None
    src_url: str = ""
    provider: str = "unknown"


class DiffEngine:
    """Stateless diff engine.

    Usage::

        changes = DiffEngine.diff(previous_scripts, current_scripts)
    """

    _CT = ScriptChange.ChangeType
    _SEV = ScriptChange.Severity

    @classmethod
    def diff(
        cls,
        previous: list[dict],
        current: list[dict],
    ) -> list[ChangeResult]:
        """Compare two lists of script dicts.  Each dict must have at minimum:
            - src (str): full source URL
            - location (str): head | body | footer | dynamic
            - async (bool)
            - defer (bool)
            - inline (bool)
            - inline_hash (str, optional)
            - wp_plugin (str, optional)
        """
        # Keyed on normalized URLs so cache-buster rotation (?ver=, ?nonce=)
        # never registers as an add/remove. Values keep the raw script dicts.
        prev_map: dict[str, dict] = {
            normalize_script_url(s["src"]): s for s in previous if s.get("src")
        }
        curr_map: dict[str, dict] = {
            normalize_script_url(s["src"]): s for s in current if s.get("src")
        }

        prev_urls = set(prev_map)
        curr_urls = set(curr_map)

        results: list[ChangeResult] = []

        removed_urls = prev_urls - curr_urls
        added_urls = curr_urls - prev_urls

        # URL_CHANGED: exactly one URL removed and one added for the same source.
        # Grouping by "source" collapses a version swap into a single, calm
        # "updated" event instead of a scary Added + Removed pair.
        #
        # What counts as "the same source" is the whole difficulty. Grouping by
        # provider alone — the original rule — assumed one provider means one
        # script, and on a real site it does not: a single client runs four GA4
        # properties, three Google Ads conversion tags and three Meta pixels,
        # every one of which answered to one provider name. Any one of them
        # dropping out of a window while another arrived satisfied the 1-to-1
        # test below, and the pair was reported as "Google Analytics 4 URL
        # changed" — an event describing two unrelated tags, at high severity,
        # which also retired the survivor's row as though it had been replaced.
        def _group_key(url: str):
            # On a tag host every surviving identifier is deliberate (see
            # normalize._IDENTITY_PARAMS), so two normalized URLs that differ at
            # all are two different tags. None keeps them out of swap pairing
            # entirely: a container that really is replaced reports as an add
            # plus a remove, which is honest, rather than as a move that
            # silently reassigns one tag's history to another.
            if is_identity_host(url):
                return None
            r = ScriptClassifier.classify(url)
            raw = "https:" + url if url.startswith("//") else url
            parts = urlsplit(raw)
            host = parts.netloc.lower().removeprefix("www.")
            if not host:
                return None
            if r.is_known:
                # Same vendor and same file, different querystring: a genuine
                # swap. Same vendor and a *different* file is a different
                # integration — LinkedIn serves insight.min.js and
                # insight.old.min.js side by side, and HubSpot's six products
                # all share one family name.
                return ("known", r.provider, host, parts.path)
            # Unknown third parties still group by host, so self-updating
            # widgets that version their filenames (e.g. leadconnectorhq) keep
            # collapsing into one calm "updated" event.
            return ("host", host)

        removed_by_key: dict[tuple, list[str]] = {}
        for url in removed_urls:
            key = _group_key(url)
            if key:
                removed_by_key.setdefault(key, []).append(url)

        added_by_key: dict[tuple, list[str]] = {}
        for url in added_urls:
            key = _group_key(url)
            if key:
                added_by_key.setdefault(key, []).append(url)

        url_changed_skips: set[str] = set()
        for key in set(removed_by_key) & set(added_by_key):
            old_list = removed_by_key[key]
            new_list = added_by_key[key]
            # Only treat as an update when there is a 1-to-1 swap
            if len(old_list) == 1 and len(new_list) == 1:
                old_url, new_url = old_list[0], new_list[0]
                url_changed_skips.add(old_url)
                url_changed_skips.add(new_url)
                if key[0] == "known":
                    provider = key[1]
                    is_critical = cls._is_critical(provider)
                    severity = cls._SEV.HIGH if is_critical else cls._SEV.MEDIUM
                    description = f"{cls._label(new_url, provider)} URL changed"
                else:
                    provider = "unknown"
                    severity = cls._SEV.MEDIUM
                    description = f"Script updated on {key[1]}"
                results.append(ChangeResult(
                    change_type=cls._CT.URL_CHANGED,
                    severity=severity,
                    description=description,
                    old_value=prev_map[old_url],
                    new_value=curr_map[new_url],
                    src_url=new_url,
                    provider=provider,
                ))

        # Removed scripts (excluding URL-changed ones)
        for url in removed_urls - url_changed_skips:
            results.append(cls._build_removed(url, prev_map[url]))

        # Added scripts (excluding URL-changed ones)
        for url in added_urls - url_changed_skips:
            results.append(cls._build_added(url, curr_map[url]))

        # Changed scripts (same URL, different attributes)
        for url in prev_urls & curr_urls:
            change = cls._build_changed(url, prev_map[url], curr_map[url])
            if change:
                results.append(change)

        return results

    # ------------------------------------------------------------------
    # Private builders
    # ------------------------------------------------------------------

    @classmethod
    def _label(cls, url: str, provider: str) -> str:
        """Provider name qualified by the tag id, when the URL carries one.

        "Google Analytics 4" logged three times is indistinguishable from one
        event repeating three times; "Google Analytics 4 (G-VEFCZRQMG4)" beside
        "Google Ads (AW-925662148)" reads as what it is.
        """
        tag_id = identity_label(url)
        return f"{provider} ({tag_id})" if tag_id else provider

    @classmethod
    def _build_removed(cls, url: str, script: dict) -> ChangeResult:
        result = ScriptClassifier.classify(url)
        is_critical = cls._is_critical(result.provider)
        severity = cls._SEV.HIGH if is_critical else cls._SEV.MEDIUM
        label = cls._label(url, result.provider)
        description = (
            f"Critical script removed: {label}"
            if is_critical
            else f"Script removed: {label or url[:80]}"
        )
        return ChangeResult(
            change_type=cls._CT.REMOVED,
            severity=severity,
            description=description,
            old_value=script,
            new_value=None,
            src_url=url,
            provider=result.provider,
        )

    @classmethod
    def _build_added(cls, url: str, script: dict) -> ChangeResult:
        result = ScriptClassifier.classify(url)
        if not result.is_known:
            severity = cls._SEV.HIGH
            description = f"Unknown script detected: {url[:120]}"
        else:
            severity = cls._SEV.MEDIUM
            description = f"New script added: {cls._label(url, result.provider)}"
        return ChangeResult(
            change_type=cls._CT.ADDED,
            severity=severity,
            description=description,
            old_value=None,
            new_value=script,
            src_url=url,
            provider=result.provider,
        )

    @classmethod
    def _build_changed(
        cls, url: str, prev: dict, curr: dict
    ) -> ChangeResult | None:
        result = ScriptClassifier.classify(url)

        # Location change.
        #
        # "unknown" is not a location — the snippet emits it when the tag is in
        # neither document.head nor document.body, i.e. it has been detached
        # from the DOM. GTM, Meta Pixel, Hotjar, Clarity and HubSpot all do that
        # after loading, and the snippet rescans on a delay and a MutationObserver,
        # so one scan saw "head" and the next saw the detached node. Comparing the
        # two produced a MEDIUM "moved from head to unknown" on one page load and
        # "moved from unknown to head" on the next, forever. Absence of
        # information is not a change, so only compare two known locations.
        prev_loc, curr_loc = prev.get("location"), curr.get("location")
        # Blacklist the sentinel rather than whitelisting known locations, so a
        # genuinely new location value stays diffable instead of being silently
        # dropped by a stale allowlist.
        unknown = {None, "", "unknown"}
        if prev_loc != curr_loc and prev_loc not in unknown and curr_loc not in unknown:
            return ChangeResult(
                change_type=cls._CT.MOVED,
                severity=cls._SEV.MEDIUM,
                description=(
                    f"{cls._label(url, result.provider) or 'Script'} "
                    f"moved from {prev_loc} to {curr_loc}"
                ),
                old_value={"location": prev_loc},
                new_value={"location": curr_loc},
                src_url=url,
                provider=result.provider,
            )

        # WordPress plugin source changed
        if prev.get("wp_plugin") and prev.get("wp_plugin") != curr.get("wp_plugin"):
            return ChangeResult(
                change_type=cls._CT.PLUGIN_CHANGED,
                severity=cls._SEV.LOW,
                description=(
                    f"{cls._label(url, result.provider)} plugin source changed from "
                    f"'{prev['wp_plugin']}' to '{curr.get('wp_plugin', 'unknown')}'"
                ),
                old_value={"wp_plugin": prev.get("wp_plugin")},
                new_value={"wp_plugin": curr.get("wp_plugin")},
                src_url=url,
                provider=result.provider,
            )

        # Inline content changed (hash mismatch)
        if (
            (prev.get("is_inline") or prev.get("inline"))
            and (curr.get("is_inline") or curr.get("inline"))
            and prev.get("inline_hash") != curr.get("inline_hash")
        ):
            return ChangeResult(
                change_type=cls._CT.INLINE_CHANGED,
                severity=cls._SEV.MEDIUM,
                description="Inline script content changed",
                old_value={"inline_hash": prev.get("inline_hash")},
                new_value={"inline_hash": curr.get("inline_hash")},
                src_url=url,
                provider=result.provider,
            )

        return None

    @classmethod
    def _is_critical(cls, provider: str) -> bool:
        return ScriptClassifier.is_critical_provider(provider)
