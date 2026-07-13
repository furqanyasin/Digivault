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
