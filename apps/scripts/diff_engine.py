"""Diff Engine — detects script changes between two snapshots.

Compares a previous and current list of script data dicts and returns a list
of ChangeResult objects.  Pure logic; no database access.  The Celery task
owns persistence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from apps.scripts.classifier import ScriptClassifier
from apps.scripts.models import ScriptChange


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

    # Providers whose removal is always high-severity
    _CRITICAL_PROVIDERS = {
        "Google Analytics 4",
        "Google Universal Analytics",
        "Google Tag Manager",
        "Meta Pixel",
        "WhatConverts",
        "CallRail",
        "Stripe",
        "PayPal",
    }

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
        prev_map: dict[str, dict] = {s["src"]: s for s in previous if s.get("src")}
        curr_map: dict[str, dict] = {s["src"]: s for s in current if s.get("src")}

        prev_urls = set(prev_map)
        curr_urls = set(curr_map)

        results: list[ChangeResult] = []

        removed_urls = prev_urls - curr_urls
        added_urls = curr_urls - prev_urls

        # URL_CHANGED: same known provider, exactly one URL removed and one added.
        # Group removed/added by provider so a GTM container-ID swap shows as
        # URL_CHANGED rather than REMOVED + ADDED.
        removed_by_provider: dict[str, list[str]] = {}
        for url in removed_urls:
            r = ScriptClassifier.classify(url)
            if r.is_known:
                removed_by_provider.setdefault(r.provider, []).append(url)

        added_by_provider: dict[str, list[str]] = {}
        for url in added_urls:
            r = ScriptClassifier.classify(url)
            if r.is_known:
                added_by_provider.setdefault(r.provider, []).append(url)

        url_changed_skips: set[str] = set()
        for provider in set(removed_by_provider) & set(added_by_provider):
            old_list = removed_by_provider[provider]
            new_list = added_by_provider[provider]
            # Only treat as URL change when there is a 1-to-1 swap
            if len(old_list) == 1 and len(new_list) == 1:
                old_url, new_url = old_list[0], new_list[0]
                url_changed_skips.add(old_url)
                url_changed_skips.add(new_url)
                is_critical = cls._is_critical(provider)
                results.append(ChangeResult(
                    change_type=cls._CT.URL_CHANGED,
                    severity=cls._SEV.HIGH if is_critical else cls._SEV.MEDIUM,
                    description=f"{provider} URL changed",
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
    def _build_removed(cls, url: str, script: dict) -> ChangeResult:
        result = ScriptClassifier.classify(url)
        is_critical = cls._is_critical(result.provider)
        severity = cls._SEV.HIGH if is_critical else cls._SEV.MEDIUM
        description = (
            f"Critical script removed: {result.provider}"
            if is_critical
            else f"Script removed: {result.provider or url[:80]}"
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
            description = f"New script added: {result.provider}"
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

        # Location change
        if prev.get("location") != curr.get("location"):
            return ChangeResult(
                change_type=cls._CT.MOVED,
                severity=cls._SEV.MEDIUM,
                description=(
                    f"{result.provider or 'Script'} moved from "
                    f"{prev.get('location')} to {curr.get('location')}"
                ),
                old_value={"location": prev.get("location")},
                new_value={"location": curr.get("location")},
                src_url=url,
                provider=result.provider,
            )

        # WordPress plugin source changed
        if prev.get("wp_plugin") and prev.get("wp_plugin") != curr.get("wp_plugin"):
            return ChangeResult(
                change_type=cls._CT.PLUGIN_CHANGED,
                severity=cls._SEV.LOW,
                description=(
                    f"{result.provider} plugin source changed from "
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
        return provider in cls._CRITICAL_PROVIDERS
