"""The {to, cc, bcc} recipient shape: parsing, canonicalising, comparing."""

import pytest

from apps.scripts.recipients import (
    MAX_RECIPIENTS_PER_KIND,
    all_recipients,
    build_recipients,
    normalize_recipient_list,
    primary_recipient,
    recipients_equal,
)


class TestNormalizeRecipientList:
    def test_a_single_address(self):
        assert normalize_recipient_list("info@site.com") == ["info@site.com"]

    def test_a_comma_separated_list(self):
        """The reason this module exists.

        normalize_recipient_email rejects a comma-joined value outright, so an
        Elementor "To" holding two addresses stored nothing at all.
        """
        assert normalize_recipient_list("sales@site.com, dev@site.com") == [
            "sales@site.com",
            "dev@site.com",
        ]

    def test_semicolons_also_separate(self):
        assert normalize_recipient_list("a@site.com; b@site.com") == [
            "a@site.com",
            "b@site.com",
        ]

    def test_addresses_are_normalized_individually(self):
        assert normalize_recipient_list(" Info@Site.COM , Sales <sales@site.com>") == [
            "info@site.com",
            "sales@site.com",
        ]

    def test_duplicates_collapse_keeping_first_position(self):
        assert normalize_recipient_list("b@site.com, a@site.com, b@site.com") == [
            "b@site.com",
            "a@site.com",
        ]

    def test_junk_entries_are_dropped_not_fatal(self):
        assert normalize_recipient_list("good@site.com, not-an-email, [your-email]") == [
            "good@site.com"
        ]

    def test_a_list_input_is_accepted(self):
        """WordPress reports a JSON array; the page reports a string."""
        assert normalize_recipient_list(["A@site.com", "b@site.com"]) == [
            "a@site.com",
            "b@site.com",
        ]

    @pytest.mark.parametrize("value", ["", None, [], "   ", ",,;"])
    def test_nothing_yields_nothing(self, value):
        assert normalize_recipient_list(value) == []

    def test_a_runaway_list_is_capped(self):
        many = ", ".join(f"a{i}@site.com" for i in range(MAX_RECIPIENTS_PER_KIND + 10))
        assert len(normalize_recipient_list(many)) == MAX_RECIPIENTS_PER_KIND


class TestBuildRecipients:
    def test_all_three_keys_are_always_present(self):
        assert build_recipients(to="a@site.com") == {
            "to": ["a@site.com"],
            "cc": [],
            "bcc": [],
        }

    def test_empty_input_is_the_empty_shape(self):
        assert build_recipients() == {"to": [], "cc": [], "bcc": []}
        assert build_recipients(to="", cc=None, bcc=[]) == {"to": [], "cc": [], "bcc": []}

    def test_an_address_in_to_is_not_repeated_in_cc(self):
        """Elementor lets you put the same address in both; showing it twice
        reads as two destinations."""
        built = build_recipients(to="a@site.com", cc="a@site.com, b@site.com")
        assert built == {"to": ["a@site.com"], "cc": ["b@site.com"], "bcc": []}

    def test_bcc_is_deduped_against_both_to_and_cc(self):
        built = build_recipients(
            to="a@site.com", cc="b@site.com", bcc="a@site.com, b@site.com, c@site.com"
        )
        assert built["bcc"] == ["c@site.com"]

    def test_cc_without_a_to_is_still_recorded(self):
        """A form can be configured to Cc only. Dropping it would report the
        form as having no destination at all."""
        assert build_recipients(cc="watch@site.com")["cc"] == ["watch@site.com"]


class TestComparison:
    def test_the_same_set_in_a_different_order_is_equal(self):
        """Plugins reorder their own notification lists; that is not a change."""
        a = build_recipients(to="a@site.com, b@site.com")
        b = build_recipients(to="b@site.com, a@site.com")
        assert recipients_equal(a, b)

    def test_a_different_address_is_not_equal(self):
        assert not recipients_equal(
            build_recipients(to="a@site.com"), build_recipients(to="c@site.com")
        )

    def test_moving_an_address_from_to_to_cc_is_a_change(self):
        """It stops being a destination and becomes a copy — worth telling the
        team about."""
        assert not recipients_equal(
            build_recipients(to="a@site.com"), build_recipients(cc="a@site.com")
        )

    def test_an_added_bcc_is_a_change(self):
        assert not recipients_equal(
            build_recipients(to="a@site.com"),
            build_recipients(to="a@site.com", bcc="silent@site.com"),
        )

    def test_a_legacy_dict_missing_keys_compares_as_empty(self):
        """Rows written before this shape existed, and hand-edited data."""
        assert recipients_equal({}, {"to": [], "cc": [], "bcc": []})
        assert recipients_equal({"to": []}, {"to": [], "cc": [], "bcc": []})
        assert not recipients_equal({"to": ["a@site.com"]}, {"to": [], "cc": [], "bcc": []})


class TestAccessors:
    def test_all_recipients_flattens_in_to_cc_bcc_order(self):
        built = build_recipients(to="a@site.com", cc="b@site.com", bcc="c@site.com")
        assert all_recipients(built) == ["a@site.com", "b@site.com", "c@site.com"]

    def test_primary_is_the_first_to(self):
        assert primary_recipient(build_recipients(to="a@site.com, b@site.com")) == "a@site.com"

    def test_primary_falls_back_to_the_first_cc(self):
        assert primary_recipient(build_recipients(cc="b@site.com")) == "b@site.com"

    def test_primary_of_nothing_is_the_empty_string(self):
        assert primary_recipient({"to": [], "cc": [], "bcc": []}) == ""
        assert primary_recipient({}) == ""

    def test_build_recipients_returns_distinct_objects(self):
        """Each call returns a new dict, safe to mutate without affecting others."""
        result1 = build_recipients()
        result2 = build_recipients()
        # Different objects in memory
        assert result1 is not result2
        # But same content
        assert result1 == result2 == {"to": [], "cc": [], "bcc": []}

    def test_mutating_a_build_recipients_result_does_not_affect_a_later_call(self):
        """Callers can safely mutate build_recipients() results: there is no
        shared empty-shape object underneath for a mutation to corrupt."""
        result = build_recipients()
        result["to"].append("test@site.com")
        # A fresh call still returns the empty shape, unaffected.
        assert build_recipients() == {"to": [], "cc": [], "bcc": []}
        assert result != {"to": [], "cc": [], "bcc": []}

    def test_mutating_one_result_does_not_affect_another(self):
        """Different results are truly independent."""
        result1 = build_recipients(to="a@site.com")
        result2 = build_recipients()
        result1["cc"].append("added@site.com")
        # result2 is unaffected
        assert result2 == {"to": [], "cc": [], "bcc": []}
        assert result1 != result2
