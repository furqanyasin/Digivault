"""The two halves of the form-error filter must agree.

A failure message is screened twice: once in the browser by `FAILURE_RE` in
apps/scripts/snippet.js, so a page's ordinary validation chatter never leaves
the visitor's machine, and once on the server by
`IMPORTANT_FORM_ERROR_KEYWORDS`, so a hand-rolled POST to the public endpoint
cannot store arbitrary text.

A phrase only one side knows about is a failure nobody hears about — the
snippet sends it and the server drops it, or the snippet never sends it at all.
The two lists live in different languages and cannot share code, so this test is
what keeps them honest.
"""

import re
from pathlib import Path

import pytest

from apps.scripts.form_errors import is_important_form_error

SNIPPET = Path(__file__).resolve().parents[2] / "apps" / "scripts" / "snippet.js"

# Verbatim status text from the plugins Digivault actually meets, each one a
# *delivery* failure the agency has to act on.
DELIVERY_FAILURES = [
    # Contact Form 7
    "There was an error trying to send your message. Please try again later.",
    # Elementor Forms
    "Your submission failed because of a server error.",
    # WPForms
    "Something went wrong while performing this action. Please try again later.",
    # Forminator
    "Error: Your message was not sent. Try again later.",
    # Ninja Forms
    "There was an error submitting your form.",
    # Generic mail-layer failures
    "Mail failed: SMTP connect() failed",
    "Request failed with status 503",
    "Unable to send your message at this time.",
]

# Text about the visitor's own input. Alerting on any of these would page a
# developer every time somebody mistyped an email address.
VALIDATION_NOISE = [
    "This field is required.",
    "Please fill in the required fields.",
    "Please enter a valid email address.",
    "The captcha was not solved correctly.",
    # Gravity Forms' validation summary — note it contains "your submission",
    # which is why the stored phrase is the narrower "submission failed".
    "There was a problem with your submission. Errors have been highlighted below.",
    "Your message has been sent. Thank you!",
]


@pytest.fixture(scope="module")
def snippet_failure_re():
    """`FAILURE_RE` lifted out of the snippet, as a Python pattern.

    Read from the file rather than copied here: a copy is a third list to keep
    in step, and would pass while the shipped snippet disagreed.
    """
    source = SNIPPET.read_text(encoding="utf-8")
    match = re.search(r"var FAILURE_RE = /\((.+?)\)/i;", source)
    assert match, "FAILURE_RE not found in snippet.js — did its shape change?"
    return re.compile(match.group(1), re.IGNORECASE)


@pytest.mark.parametrize("message", DELIVERY_FAILURES)
def test_both_sides_keep_a_delivery_failure(message, snippet_failure_re):
    assert snippet_failure_re.search(message), "the snippet would not send this"
    assert is_important_form_error(message), "the server would not store this"


@pytest.mark.parametrize("message", VALIDATION_NOISE)
def test_both_sides_drop_validation_noise(message, snippet_failure_re):
    assert not snippet_failure_re.search(message), "the snippet would send this"
    assert not is_important_form_error(message), "the server would store this"
