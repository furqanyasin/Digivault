import hashlib
import hmac

from apps.site_health.wp_activity_auth import REPLAY_WINDOW_SECONDS, verify_signature

SECRET = "s" * 32
BODY = b'{"events":[]}'


def sign(secret: str, timestamp: str, body: bytes) -> str:
    msg = timestamp.encode() + b"." + body
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


def test_valid_signature_accepted():
    assert verify_signature(SECRET, "1000", BODY, sign(SECRET, "1000", BODY), now=1000)


def test_wrong_secret_rejected():
    assert not verify_signature(SECRET, "1000", BODY, sign("other", "1000", BODY), now=1000)


def test_tampered_body_rejected():
    sig = sign(SECRET, "1000", BODY)
    assert not verify_signature(SECRET, "1000", b'{"events":[1]}', sig, now=1000)


def test_timestamp_outside_window_rejected():
    stale = 1000 - REPLAY_WINDOW_SECONDS - 1
    sig = sign(SECRET, str(stale), BODY)
    assert not verify_signature(SECRET, str(stale), BODY, sig, now=1000)


def test_timestamp_at_window_edge_accepted():
    edge = 1000 - REPLAY_WINDOW_SECONDS
    sig = sign(SECRET, str(edge), BODY)
    assert verify_signature(SECRET, str(edge), BODY, sig, now=1000)


def test_future_timestamp_outside_window_rejected():
    future = 1000 + REPLAY_WINDOW_SECONDS + 1
    sig = sign(SECRET, str(future), BODY)
    assert not verify_signature(SECRET, str(future), BODY, sig, now=1000)


def test_empty_secret_rejected():
    assert not verify_signature("", "1000", BODY, sign("", "1000", BODY), now=1000)


def test_non_numeric_timestamp_rejected():
    assert not verify_signature(SECRET, "abc", BODY, sign(SECRET, "abc", BODY), now=1000)


def test_signature_comparison_is_case_insensitive():
    sig = sign(SECRET, "1000", BODY).upper()
    assert verify_signature(SECRET, "1000", BODY, sig, now=1000)
