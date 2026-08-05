"""Follow-up suggestions — what the assistant offers after each answer.

The widget used to show its quick questions only on the welcome message, so the
second turn onwards left you staring at an empty box with no idea what the
assistant understood. Every reply now carries its own next steps.

Two rules matter more than the exact wording. A suggestion must never repeat the
question just answered — that is the dead end this exists to remove — and it must
be a phrase `detect_intent` actually recognises, or the chip leads to "I'm not
sure what you're asking".
"""
import pytest

from apps.chat.followups import MAX_SUGGESTIONS, suggest
from apps.chat.intents import detect_intent


def test_every_intent_type_gets_at_least_one_suggestion():
    """A reply with no next step is the dead end we are removing."""
    types = [
        "help", "summary", "website_status", "not_found", "scripts_list",
        "unknown_scripts", "no_unknowns", "alerts_list", "no_alerts",
        "forms_list", "websites_list", "monitors_list", "monitors_down",
        "monitors_all_up", "changes_list", "clients_list", "client_detail",
        "onboard_instructions", "already_onboarded", "empty", "error", "fallback",
    ]
    for t in types:
        assert suggest({"type": t, "data": None}), f"{t} offers no next step"


def test_suggestions_are_capped_so_they_fit_the_widget():
    for t in ["summary", "website_status", "fallback", "help"]:
        assert len(suggest({"type": t, "data": None})) <= MAX_SUGGESTIONS


def test_no_duplicate_suggestions():
    for t in ["summary", "website_status", "alerts_list"]:
        chips = suggest({"type": t, "data": {"domain": "example.com"}})
        assert len(chips) == len(set(chips))


class TestSuggestionsNeverLoopBackOnThemselves:
    def test_an_alerts_answer_does_not_offer_alerts_again(self):
        chips = suggest({"type": "alerts_list", "data": None})
        assert not any("alert" in c.lower() for c in chips)

    def test_a_summary_answer_does_not_offer_a_summary(self):
        chips = suggest({"type": "summary", "data": None})
        assert not any("summary" in c.lower() for c in chips)

    def test_a_monitors_down_answer_does_not_offer_monitors_down(self):
        chips = suggest({"type": "monitors_down", "data": None})
        assert not any("down" in c.lower() for c in chips)

    def test_an_unknown_scripts_answer_does_not_offer_unknown_scripts(self):
        chips = suggest({"type": "unknown_scripts", "data": None})
        assert not any("unknown" in c.lower() for c in chips)

    def test_a_clients_answer_does_not_offer_the_client_list_again(self):
        chips = suggest({"type": "clients_list", "data": None})
        assert not any(c.lower() == "list my clients" for c in chips)


class TestContextualSuggestions:
    def test_a_website_answer_offers_that_website_by_name(self):
        chips = suggest({"type": "website_status", "data": {"domain": "example.com"}})
        assert any("example.com" in c for c in chips)

    def test_a_website_answer_without_a_domain_still_suggests_something(self):
        assert suggest({"type": "website_status", "data": {}})

    def test_a_site_with_pending_changes_is_pointed_at_them(self):
        chips = suggest({
            "type": "website_status",
            "data": {"domain": "example.com", "pending_changes": 4},
        })
        assert any("change" in c.lower() for c in chips)

    def test_a_not_found_answer_offers_onboarding_that_exact_domain(self):
        chips = suggest({"type": "not_found", "data": {"query": "newsite.com"}})
        assert any(c.lower().startswith("onboard newsite.com") for c in chips)

    def test_a_not_found_answer_without_a_query_does_not_say_onboard_none(self):
        chips = suggest({"type": "not_found", "data": {}})
        assert not any("none" in c.lower() for c in chips)


class TestSuggestionsAreUnderstoodByTheParser:
    """A chip that produces "I'm not sure what you're asking" is worse than none."""

    @pytest.mark.parametrize("intent_type,data", [
        ("help", None),
        ("summary", None),
        ("website_status", {"domain": "example.com", "pending_changes": 2}),
        ("not_found", {"query": "newsite.com"}),
        ("scripts_list", None),
        ("unknown_scripts", None),
        ("no_unknowns", None),
        ("alerts_list", None),
        ("no_alerts", None),
        ("forms_list", None),
        ("websites_list", None),
        ("monitors_list", None),
        ("monitors_down", None),
        ("monitors_all_up", None),
        ("changes_list", None),
        ("clients_list", None),
        ("client_detail", None),
        ("onboard_instructions", None),
        ("already_onboarded", None),
        ("empty", None),
        ("error", None),
        ("fallback", None),
    ])
    def test_each_suggestion_maps_to_a_real_intent(self, intent_type, data):
        for chip in suggest({"type": intent_type, "data": data}):
            intent, _ = detect_intent(chip)
            assert intent != "fallback", f"{chip!r} is not understood by detect_intent"


class TestProcessMessageAttachesThem:
    def test_a_reply_carries_its_suggestions(self, db, team):
        from apps.chat.intents import process_message

        result = process_message(team, "help")

        assert result["suggestions"]
        assert isinstance(result["suggestions"], list)

    def test_an_unparseable_message_still_offers_a_way_forward(self, db, team):
        from apps.chat.intents import process_message

        result = process_message(team, "asdkjhasd qwe")

        assert result["type"] == "fallback"
        assert result["suggestions"]


class TestTheShapeTheWidgetReads:
    """`reply` and `suggestions` must sit at the top level of the response.

    The /api/chat proxy already unwraps the DRF envelope, and the payload has its
    own `data` key holding the intent's details (domain, counts). Reaching for
    `.data` in the widget would therefore return that object and silently lose
    the reply — so this pins where each field lives.
    """

    @pytest.fixture
    def api(self, db):
        from rest_framework.test import APIClient

        from apps.accounts.models import User
        from apps.accounts.services import TeamService
        from apps.websites.models import Website

        user = User.objects.create_user(email="shape@x.io", password="SecurePass1!")
        team = TeamService.create(name="Shape Co", owner=user)
        user.active_team = team
        user.save()
        Website.objects.create(team=team, name="Example", domain="example.com")

        client = APIClient()
        token = client.post(
            "/api/v1/auth/token/",
            {"email": user.email, "password": "SecurePass1!"},
            format="json",
        ).data["access"]
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        return client

    @pytest.mark.parametrize(
        "message", ["help", "summary", "example.com", "any alerts?", "asdkjh qwe"]
    )
    def test_reply_and_suggestions_are_top_level(self, api, message):
        resp = api.post("/api/v1/chat/", {"message": message}, format="json")

        assert resp.status_code == 200
        assert "reply" in resp.data
        assert resp.data["suggestions"], f"{message!r} dead-ends the conversation"

    def test_a_site_lookup_keeps_reply_beside_its_data(self, api):
        """The one case where a naive `.data` unwrap would break."""
        resp = api.post("/api/v1/chat/", {"message": "example.com"}, format="json")

        assert resp.data["type"] == "website_status"
        assert "example.com" in resp.data["reply"]
        # data is the intent's detail payload, a sibling of reply — not a wrapper.
        assert resp.data["data"]["domain"] == "example.com"
        assert any("example.com" in s for s in resp.data["suggestions"])


def test_an_unknown_type_falls_back_rather_than_crashing():
    """A new intent added later must not break the widget."""
    assert suggest({"type": "some_future_type", "data": None})


def test_a_missing_type_is_handled():
    assert suggest({}) == suggest({"type": "unrecognised"})
