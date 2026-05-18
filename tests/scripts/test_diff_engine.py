import pytest

from apps.scripts.diff_engine import DiffEngine
from apps.scripts.models import ScriptChange


class TestDiffEngine:
    GTM = "https://www.googletagmanager.com/gtm.js?id=GTM-XXX"
    GA4 = "https://www.googletagmanager.com/gtag/js?id=G-XXX"
    PIXEL = "https://connect.facebook.net/en_US/fbevents.js"
    UNKNOWN = "https://sketchy-tracker.xyz/evil.js"
    HOTJAR = "https://static.hotjar.com/c/hotjar-12345.js"

    def _script(self, src, location="head", **kwargs):
        return {"src": src, "location": location, "is_async": False, "is_defer": False,
                "is_inline": False, "inline_hash": "", **kwargs}

    def test_no_changes_returns_empty(self):
        scripts = [self._script(self.GTM), self._script(self.GA4)]
        assert DiffEngine.diff(scripts, scripts) == []

    def test_added_known_script_is_medium(self):
        prev = [self._script(self.GTM)]
        curr = [self._script(self.GTM), self._script(self.HOTJAR)]
        changes = DiffEngine.diff(prev, curr)
        assert len(changes) == 1
        assert changes[0].change_type == ScriptChange.ChangeType.ADDED
        assert changes[0].severity == ScriptChange.Severity.MEDIUM

    def test_added_unknown_script_is_high(self):
        prev = [self._script(self.GTM)]
        curr = [self._script(self.GTM), self._script(self.UNKNOWN)]
        changes = DiffEngine.diff(prev, curr)
        added = [c for c in changes if c.change_type == ScriptChange.ChangeType.ADDED]
        assert len(added) == 1
        assert added[0].severity == ScriptChange.Severity.HIGH

    def test_removed_critical_script_is_high(self):
        prev = [self._script(self.GTM), self._script(self.GA4)]
        curr = [self._script(self.GTM)]  # GA4 removed
        changes = DiffEngine.diff(prev, curr)
        assert len(changes) == 1
        assert changes[0].change_type == ScriptChange.ChangeType.REMOVED
        assert changes[0].severity == ScriptChange.Severity.HIGH

    def test_removed_non_critical_script_is_medium(self):
        prev = [self._script(self.GTM), self._script(self.HOTJAR)]
        curr = [self._script(self.GTM)]  # Hotjar removed
        changes = DiffEngine.diff(prev, curr)
        removed = [c for c in changes if c.change_type == ScriptChange.ChangeType.REMOVED]
        assert removed[0].severity == ScriptChange.Severity.MEDIUM

    def test_moved_script_detected(self):
        prev = [self._script(self.GTM, location="head")]
        curr = [self._script(self.GTM, location="footer")]
        changes = DiffEngine.diff(prev, curr)
        assert len(changes) == 1
        assert changes[0].change_type == ScriptChange.ChangeType.MOVED

    def test_inline_content_change_detected(self):
        prev = [self._script("", location="body", is_inline=True, inline_hash="aaa")]
        curr = [self._script("", location="body", is_inline=True, inline_hash="bbb")]
        # Both have empty src so they won't trigger add/remove; the inline change
        # applies to matching srcs — with empty src they'd both be keyed the same
        # but empty src is filtered out; test with a real src instead:
        src = "https://example.com/inline-placeholder"
        prev2 = [self._script(src, is_inline=True, inline_hash="aaa")]
        curr2 = [self._script(src, is_inline=True, inline_hash="bbb")]
        changes = DiffEngine.diff(prev2, curr2)
        assert any(c.change_type == ScriptChange.ChangeType.INLINE_CHANGED for c in changes)

    def test_empty_previous_all_added(self):
        curr = [self._script(self.GTM), self._script(self.GA4), self._script(self.PIXEL)]
        changes = DiffEngine.diff([], curr)
        assert len(changes) == 3
        assert all(c.change_type == ScriptChange.ChangeType.ADDED for c in changes)

    def test_empty_current_all_removed(self):
        prev = [self._script(self.GTM), self._script(self.GA4)]
        changes = DiffEngine.diff(prev, [])
        assert len(changes) == 2
        assert all(c.change_type == ScriptChange.ChangeType.REMOVED for c in changes)
