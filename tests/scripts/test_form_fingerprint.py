"""Fingerprint stability — volatile fields (nonces, honeypots) must not
change a form's identity between page loads."""

from apps.scripts.models import DetectedForm


# No id and no name: an anonymous form, where the field set is all that tells
# one form on a page from another (see TestFingerprintFieldChurn for why an
# identified form deliberately ignores its fields).
BASE = {
    "detection_type": "native",
    "form_id": "",
    "form_name": "",
    "form_action": "/submit",
}


def _fp(fields):
    return DetectedForm.compute_fingerprint({**BASE, "fields": fields})


class TestFingerprintStability:
    def test_rotating_wpnonce_ignored(self):
        a = _fp([{"name": "email"}, {"name": "_wpnonce_a1b2"}])
        b = _fp([{"name": "email"}, {"name": "_wpnonce_c3d4"}])
        assert a == b

    def test_wpcf7_internal_fields_ignored(self):
        a = _fp([{"name": "email"}, {"name": "_wpcf7_unit_tag"}])
        b = _fp([{"name": "email"}])
        assert a == b

    def test_honeypot_and_hexname_fields_ignored(self):
        a = _fp([{"name": "email"}, {"name": "hp-field"}, {"name": "a1b2c3d4e5f60718"}])
        b = _fp([{"name": "email"}])
        assert a == b

    def test_recaptcha_token_field_ignored(self):
        a = _fp([{"name": "email"}, {"name": "g-recaptcha-response"}])
        b = _fp([{"name": "email"}])
        assert a == b

    def test_genuinely_different_forms_still_differ(self):
        a = _fp([{"name": "email"}])
        b = _fp([{"name": "email"}, {"name": "phone"}])
        assert a != b

    def test_real_field_named_like_word_nonce_prefix_not_overmatched(self):
        # "message" must never be filtered; sanity check normal fields survive
        a = _fp([{"name": "message"}])
        b = _fp([])
        assert a != b


class TestFingerprintFieldChurn:
    """A form that carries an id or a name keeps it across every observation;
    the fields it happens to have rendered do not.

    The snippet posts several times per page load and once more at submit time,
    and a multi-step form mounts only the fields of the step it is showing. With
    the field set in the hash, every step minted its own row: the Forms tab
    listed `multiStepForm` twice on one path — the page-load steps at 0 submits
    and the final step holding all the conversions, because a submit whose
    fingerprint matches nothing stored creates a row of its own.
    """

    def _fp(self, **over):
        return DetectedForm.compute_fingerprint({
            "detection_type": "native",
            "form_id": "multiStepForm",
            "form_name": "",
            "form_action": "https://acme-agency.com/",
            "fields": [{"name": "name"}, {"name": "email"}],
            **over,
        })

    def test_step_two_fields_do_not_mint_a_second_form(self):
        assert self._fp() == self._fp(fields=[{"name": "company"}, {"name": "budget"}])

    def test_late_rendered_field_does_not_mint_a_second_form(self):
        assert self._fp() == self._fp(
            fields=[{"name": "name"}, {"name": "email"}, {"name": "phone"}]
        )

    def test_form_with_only_a_name_is_also_identified(self):
        named = {"form_id": "", "form_name": "quoteForm"}
        assert self._fp(**named) == self._fp(**named, fields=[{"name": "later"}])

    def test_different_identifiers_still_differ(self):
        assert self._fp() != self._fp(form_id="newsletterForm")

    def test_anonymous_forms_are_still_told_apart_by_their_fields(self):
        anon = {"form_id": "", "form_name": ""}
        assert self._fp(**anon, fields=[{"name": "email"}]) != self._fp(
            **anon, fields=[{"name": "email"}, {"name": "cv"}]
        )

    def test_identified_form_never_collides_with_an_anonymous_one(self):
        # The fields segment is emptied, not dropped, so an identifier can't be
        # confused with a field name shifted into its place.
        assert self._fp(form_id="email", fields=[]) != self._fp(
            form_id="", form_name="", fields=[{"name": "email"}]
        )


def _fp_action(action):
    return DetectedForm.compute_fingerprint({
        "detection_type": "native",
        "form_id": "multiStepForm",
        "form_name": "",
        "form_action": action,
        "fields": [{"name": "email"}],
    })


class TestFingerprintActionStability:
    """A form with no `action` attribute reports the document URL.

    `form.action` in the browser resolves to the current page URL when the
    attribute is absent — so the same form arrives with a different action for
    every campaign, ad and referral URL. Left in the hash, one form minted a
    fresh row per URL variant: the Forms tab showed the same form several times
    and split its submission count across the copies.
    """

    def test_utm_params_do_not_change_identity(self):
        assert _fp_action("https://acme-agency.com/") == _fp_action(
            "https://acme-agency.com/?utm_source=newsletter&gclid=abc"
        )

    def test_fragment_and_trailing_slash_do_not_change_identity(self):
        assert _fp_action("https://acme-agency.com/") == _fp_action(
            "https://acme-agency.com#quote-form"
        )

    def test_www_prefix_does_not_change_identity(self):
        assert _fp_action("https://acme-agency.com/contact-us") == _fp_action(
            "https://www.acme-agency.com/contact-us/"
        )

    def test_genuinely_different_actions_still_differ(self):
        assert _fp_action("https://acme-agency.com/a") != _fp_action(
            "https://acme-agency.com/b"
        )

    def test_relative_action_is_left_alone(self):
        # Not a URL we can normalize — must survive as its own identity.
        assert _fp_action("/submit") != _fp_action("/other")
        assert _fp_action("/submit") == _fp_action("/submit")
