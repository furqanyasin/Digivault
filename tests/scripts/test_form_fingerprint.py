"""Fingerprint stability — volatile fields (nonces, honeypots) must not
change a form's identity between page loads."""

from apps.scripts.models import DetectedForm


BASE = {
    "detection_type": "native",
    "form_id": "wpcf7-f12",
    "form_name": "contact",
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
        assert _fp_action("https://digilatics.com/") == _fp_action(
            "https://digilatics.com/?utm_source=newsletter&gclid=abc"
        )

    def test_fragment_and_trailing_slash_do_not_change_identity(self):
        assert _fp_action("https://digilatics.com/") == _fp_action(
            "https://digilatics.com#quote-form"
        )

    def test_www_prefix_does_not_change_identity(self):
        assert _fp_action("https://digilatics.com/contact-us") == _fp_action(
            "https://www.digilatics.com/contact-us/"
        )

    def test_genuinely_different_actions_still_differ(self):
        assert _fp_action("https://digilatics.com/a") != _fp_action(
            "https://digilatics.com/b"
        )

    def test_relative_action_is_left_alone(self):
        # Not a URL we can normalize — must survive as its own identity.
        assert _fp_action("/submit") != _fp_action("/other")
        assert _fp_action("/submit") == _fp_action("/submit")
