
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

    def test_detached_script_is_not_a_move(self):
        # The snippet reports location "unknown" when a tag sits in neither head
        # nor body — i.e. it was detached from the DOM, which GTM, Meta Pixel,
        # Hotjar, Clarity and HubSpot all do after loading. Rescans then flip
        # between "head" and "unknown", which used to mint an endless stream of
        # MEDIUM "moved from head to unknown" changes. Absence of information is
        # not a change.
        for before, after in (("head", "unknown"), ("unknown", "head"), ("body", "unknown")):
            prev = [self._script(self.GTM, location=before)]
            curr = [self._script(self.GTM, location=after)]
            moved = [
                c for c in DiffEngine.diff(prev, curr)
                if c.change_type == ScriptChange.ChangeType.MOVED
            ]
            assert moved == [], f"{before} -> {after} should not report a move"

    def test_real_move_still_detected_alongside_unknown_suppression(self):
        prev = [self._script(self.GTM, location="head")]
        curr = [self._script(self.GTM, location="body")]
        changes = DiffEngine.diff(prev, curr)
        assert [c.change_type for c in changes] == [ScriptChange.ChangeType.MOVED]

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

    def test_unknown_widget_version_swap_collapses_to_single_update(self):
        """A versioned third-party widget (same host) should read as one calm
        'updated' event, not a high Added + medium Removed pair."""
        # Deliberately an unclassified host: a recognised provider names itself
        # in the description instead of quoting the URL, which is a different
        # path than the one under test here.
        prev = [self._script("https://widgets.some-unknown-saas.io/loader-abc123.js")]
        curr = [self._script("https://widgets.some-unknown-saas.io/loader-def456.js")]
        changes = DiffEngine.diff(prev, curr)
        assert len(changes) == 1
        assert changes[0].change_type == ScriptChange.ChangeType.URL_CHANGED
        assert changes[0].severity == ScriptChange.Severity.MEDIUM
        assert "some-unknown-saas.io" in changes[0].description

    def test_unknown_add_and_unrelated_remove_not_collapsed(self):
        """Different hosts must NOT collapse — a genuine add and remove stay separate."""
        prev = [self._script("https://old-tracker.xyz/a.js")]
        curr = [self._script("https://new-tracker.xyz/b.js")]
        changes = DiffEngine.diff(prev, curr)
        types = {c.change_type for c in changes}
        assert ScriptChange.ChangeType.ADDED in types
        assert ScriptChange.ChangeType.REMOVED in types


class TestNormalizedDiffing:
    """ver bumps and cache-buster rotation must not fake add/remove events."""

    def test_ver_bump_produces_no_changes(self):
        prev = [{"src": "https://example-cdn.com/widget.js?ver=1.0", "location": "head",
                 "is_async": False, "is_defer": False, "is_inline": False}]
        curr = [{"src": "https://example-cdn.com/widget.js?ver=2.0", "location": "head",
                 "is_async": False, "is_defer": False, "is_inline": False}]
        assert DiffEngine.diff(prev, curr) == []

    def test_container_id_swap_is_an_add_and_a_remove_not_a_move(self):
        """A different container id is a different tag, not a moved one.

        This used to assert a single `url_changed`, and that expectation was the
        bug. On a tag host the engine cannot tell "this container was replaced"
        apart from "one of the four tags this site runs went away and a
        different one arrived" — both are one id out, one id in, on the same
        loader path. A live site running four GA4 properties and three Google
        Ads tags had the second case reported as the first: a high-severity
        "Google Analytics 4 URL changed" describing two unrelated tags, which
        also retired the survivor's row as though it had been superseded.

        So `normalize.is_identity_host` hosts are kept out of swap pairing
        entirely. An add plus a remove is the honest reading, and it keeps each
        tag's history attached to the tag it belongs to.
        """
        prev = [{"src": "https://www.googletagmanager.com/gtag/js?id=GTM-AAA", "location": "head",
                 "is_async": True, "is_defer": False, "is_inline": False}]
        curr = [{"src": "https://www.googletagmanager.com/gtag/js?id=GTM-BBB", "location": "head",
                 "is_async": True, "is_defer": False, "is_inline": False}]
        changes = DiffEngine.diff(prev, curr)
        assert {c.change_type for c in changes} == {
            ScriptChange.ChangeType.ADDED, ScriptChange.ChangeType.REMOVED
        }
        assert not any(c.change_type == "url_changed" for c in changes)

    def test_volatile_param_duplicates_collapse(self):
        curr = [
            {"src": "https://example-cdn.com/widget.js?ver=1.0", "location": "head",
             "is_async": False, "is_defer": False, "is_inline": False},
            {"src": "https://example-cdn.com/widget.js?ver=2.0", "location": "head",
             "is_async": False, "is_defer": False, "is_inline": False},
        ]
        changes = DiffEngine.diff([], curr)
        assert len(changes) == 1
        assert changes[0].change_type == "added"

    def test_change_result_carries_normalized_url(self):
        curr = [{"src": "https://example-cdn.com/widget.js?ver=1.0", "location": "head",
                 "is_async": False, "is_defer": False, "is_inline": False}]
        changes = DiffEngine.diff([], curr)
        assert changes[0].src_url == "https://example-cdn.com/widget.js"
