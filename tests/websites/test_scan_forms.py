"""Server-side scan must surface forms, not just scripts.

The scan endpoint fetches the homepage server-side; before this, its payload
carried only scripts, so a freshly added <form> stayed invisible until a
real browser loaded the page with the passive snippet. The extraction mirrors
the snippet's native-form descriptor shape so the row it writes matches what
the submission counter looks up.
"""

from unittest.mock import Mock, patch

import pytest

from apps.websites.views import _extract_forms


class TestExtractForms:
    def test_native_form_descriptor(self):
        html = """
        <form id="contact" name="contact-form" action="/submit/" method="post">
          <label for="your-name">Your name</label>
          <input type="text" id="your-name" name="your-name" required>
          <input type="email" name="your-email" placeholder="Email">
          <input type="hidden" name="_wpcf7" value="123">
          <input type="submit" value="Send">
        </form>
        """
        forms = _extract_forms(html)

        assert len(forms) == 1
        form = forms[0]
        assert form["form_id"] == "contact"
        assert form["form_name"] == "contact-form"
        assert form["form_action"] == "/submit/"
        assert form["form_method"] == "post"
        assert form["detection_type"] == "native"
        assert form["provider"] == ""

        names = [(f["name"], f["type"]) for f in form["fields"]]
        assert names == [("your-name", "text"), ("your-email", "email")]

        your_name = form["fields"][0]
        assert your_name["label"] == "Your name"
        assert your_name["required"] is True
        assert form["fields"][1]["label"] == "Email"
        assert form["fields"][1]["required"] is False

    def test_textarea_and_select_types(self):
        html = """
        <form action="/x">
          <textarea name="message"></textarea>
          <select name="subject"><option>1</option></select>
        </form>
        """
        forms = _extract_forms(html)

        assert [(f["name"], f["type"]) for f in forms[0]["fields"]] == [
            ("message", "textarea"),
            ("subject", "select"),
        ]

    def test_actionless_form_defaults_to_post(self):
        forms = _extract_forms('<form><input name="q"></form>')
        assert forms[0]["form_action"] == ""
        assert forms[0]["form_method"] == "post"

    def test_unclosed_form_does_not_swallow_the_page(self):
        # A stray <form> with no </form> must not make a later page's inputs
        # fields of it — and must not blow up the extractor.
        html = "<form id='broken'>" + "<input name='a'>" + "x" * 10000 + "</body></html>"
        forms = _extract_forms(html)

        assert len(forms) == 1
        assert [f["name"] for f in forms[0]["fields"]] == ["a"]

    def test_anonymous_fields_are_kept(self):
        forms = _extract_forms('<form><input type="text"></form>')
        assert forms[0]["fields"] == []

    def test_mailto_action_yields_recipient_email(self):
        forms = _extract_forms(
            '<form action="mailto:info@example.com?subject=hello">'
            '<input type="text" name="q">'
            "</form>"
        )
        assert forms[0]["recipients"]["to"] == ["info@example.com"]

    def test_hidden_input_value_yields_recipient_email(self):
        forms = _extract_forms(
            '<form action="/submit/">'
            '<input type="text" name="name">'
            '<input type="hidden" name="recipient" value="Sales@Example.com">'
            '<input type="submit" value="Send">'
            "</form>"
        )
        assert forms[0]["recipients"]["to"] == ["sales@example.com"]
        # The hidden config field stays out of the visible field list.
        assert [(f["name"], f["type"]) for f in forms[0]["fields"]] == [("name", "text")]

    def test_visitor_email_field_is_not_a_recipient(self):
        forms = _extract_forms(
            '<form action="/submit/">'
            '<input type="email" name="your-email" value="visitor@example.com">'
            "</form>"
        )
        assert forms[0]["recipients"] == {"to": [], "cc": [], "bcc": []}

    def test_malformed_hidden_value_yields_no_recipient(self):
        forms = _extract_forms(
            '<form action="/submit/">'
            '<input type="hidden" name="recipient" value="not-an-email">'
            "</form>"
        )
        assert forms[0]["recipients"] == {"to": [], "cc": [], "bcc": []}

    def test_form_without_recipient_defaults_empty(self):
        forms = _extract_forms('<form action="/submit/"><input name="q"></form>')
        assert forms[0]["recipients"] == {"to": [], "cc": [], "bcc": []}

    def test_mailto_action_yields_to_cc_and_bcc(self):
        html = (
            '<form action="mailto:a@example.com,b@example.com'
            '?cc=c@example.com&amp;bcc=d@example.com">'
            '<input name="name"><button type="submit">Go</button></form>'
        )
        forms = _extract_forms(html)
        assert forms[0]["recipients"] == {
            "to": ["a@example.com", "b@example.com"],
            "cc": ["c@example.com"],
            "bcc": ["d@example.com"],
        }

    def test_a_mailto_without_a_query_still_yields_to(self):
        html = (
            '<form action="mailto:info@example.com">'
            '<input name="name"><button type="submit">Go</button></form>'
        )
        forms = _extract_forms(html)
        assert forms[0]["recipients"]["to"] == ["info@example.com"]

    def test_a_hidden_field_merely_containing_cc_is_not_a_cc(self):
        """success_url, account_email, occupation all contain "cc" as a
        substring — a bare `"cc" in name` test misfiles them as a Cc address.
        Only ^cc$ / _cc$ / "carbon" (mirroring snippet.js's CC_NAME) qualify."""
        html = (
            '<form action="/submit/">'
            '<input type="hidden" name="account_email" value="owner@example.com">'
            '<input name="q">'
            "</form>"
        )
        forms = _extract_forms(html)
        assert forms[0]["recipients"] == {
            "to": ["owner@example.com"], "cc": [], "bcc": [],
        }

    def test_a_mailto_to_and_a_hidden_recipient_field_are_unioned(self):
        """Regression: `to=mailto_to or hidden_to` discarded the hidden value
        entirely whenever a mailto: action was present, while the snippet
        unions the two. Both writers feed the same recipient_source="page"
        row, so the disagreement read as a same-source change and posted a
        false ClickUp alert that flipped back and forth between a Scan and a
        real pageview on any form with both a mailto: action and an unrelated
        hidden recipient field."""
        html = (
            '<form action="mailto:sales@example.com">'
            '<input type="hidden" name="admin_email" value="boss@example.com">'
            '<input name="q">'
            "</form>"
        )
        forms = _extract_forms(html)
        assert forms[0]["recipients"]["to"] == [
            "sales@example.com", "boss@example.com",
        ]

    def test_a_non_recipient_hidden_field_is_a_fallback_not_a_to(self):
        """A hidden field whose name says nothing about being a destination
        must not out-rank a mailto: To by unioning in — it is only used when
        nothing else supplies one (see test_a_hidden_field_merely_containing_
        cc_is_not_a_cc for that empty-mailto case)."""
        html = (
            '<form action="mailto:sales@example.com">'
            '<input type="hidden" name="form_step" value="unrelated@example.com">'
            '<input name="q">'
            "</form>"
        )
        forms = _extract_forms(html)
        assert forms[0]["recipients"]["to"] == ["sales@example.com"]

    def test_a_non_email_hidden_field_does_not_lock_out_the_fallback(self):
        """The fallback slot is claimed by the first hidden field that isn't
        Cc/Bcc/To-named — but only if it's actually shaped like an address.
        Bucketing before checking email-shape (as an earlier version of this
        function did) let a `_wpnonce` or CSRF token claim that one slot
        ahead of a later hidden field that is a genuine unnamed recipient
        address, permanently losing it — no downstream normalization gets it
        back once the slot is taken. snippet.js's detectRecipients() skips a
        non-email hidden value before it can claim any bucket, fallback
        included; this mirrors that ordering."""
        html = (
            '<form action="/submit/">'
            '<input type="hidden" name="_wpnonce" value="abc123def456">'
            '<input type="hidden" name="visitor_email" value="jane@example.com">'
            '<input name="q">'
            "</form>"
        )
        forms = _extract_forms(html)
        assert forms[0]["recipients"]["to"] == ["jane@example.com"]


@pytest.mark.django_db
class TestScanQueuesForms:
    def _patch_fetch(self, html):
        """The shared outbound client's result, not a `requests` response.

        `scan` used to call `requests.get` directly, skipping the per-host
        budget, the cooldown and the SSRF guard that `outbound` re-applies on
        every redirect hop. Patching `outbound.fetch` keeps that fixed: a
        rewrite that reaches for `requests` again stops being covered here.
        """
        from apps.common.outbound import FetchResult

        return FetchResult(
            status_code=200,
            body=html,
            headers={},
            elapsed_ms=12,
            final_url="https://example.com/",
        )

    def _scan(self, auth_client, website, html):
        resp = self._patch_fetch(html)
        ingest_mock = Mock()
        with patch("apps.websites.views.outbound.fetch", return_value=resp), \
             patch("apps.scripts.tasks.process_ingest_payload", ingest_mock), \
             patch("apps.site_health.tasks.run_security_scan"), \
             patch("apps.site_health.tasks.run_seo_check"):
            response = auth_client.post(f"/api/v1/websites/{website.id}/scan/")
        return response, ingest_mock

    def _website(self, team):
        from apps.websites.models import Website

        # `snippet_status` must be INSTALLED or the endpoint answers 409 before
        # it fetches anything. That gate was added to `scan` well after these
        # tests were written and the fixture was never updated, so all three
        # have been failing since — invisibly, because nothing runs the suite.
        return Website.objects.create(
            team=team,
            name="Example",
            domain="example.com",
            snippet_status=Website.SnippetStatus.INSTALLED,
        )

    def test_scan_payload_includes_forms(self, auth_client, team):
        website = self._website(team)
        html = """
        <html><body>
          <script src="https://cdn.example.com/app.js"></script>
          <form id="contact" action="/submit/" method="post">
            <input type="text" name="name" required>
            <input type="submit" value="Send">
          </form>
        </body></html>
        """
        response, ingest_mock = self._scan(auth_client, website, html)

        assert response.status_code == 200, response.data
        assert response.data["count"] == 1
        assert response.data["forms"] == 1

        ingest_mock.delay.assert_called_once()
        payload = ingest_mock.delay.call_args[0][1]
        assert len(payload["scripts"]) == 1
        assert len(payload["forms"]) == 1
        assert payload["forms"][0]["form_id"] == "contact"
        assert payload["forms"][0]["form_action"] == "/submit/"
        assert payload["forms"][0]["detection_type"] == "native"

    def test_scan_with_forms_but_no_scripts_still_queues(self, auth_client, team):
        website = self._website(team)
        html = """
        <html><body>
          <form action="/submit/"><input type="text" name="email"></form>
        </body></html>
        """
        response, ingest_mock = self._scan(auth_client, website, html)

        assert response.status_code == 200, response.data
        assert response.data["count"] == 0
        assert response.data["forms"] == 1
        ingest_mock.delay.assert_called_once()
        assert ingest_mock.delay.call_args[0][1]["forms"][0]["form_id"] == ""

    def test_scan_with_neither_returns_early(self, auth_client, team):
        website = self._website(team)
        response, ingest_mock = self._scan(
            auth_client, website, "<html><body><p>No forms here</p></body></html>"
        )

        assert response.status_code == 200
        assert response.data["count"] == 0
        assert response.data["forms"] == 0
        ingest_mock.delay.assert_not_called()
