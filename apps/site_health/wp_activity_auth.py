"""Authentication for the WP Connect activity push.

Deliberately NOT the pattern used by `PhpErrorIngestView`, which binds on
`Origin`/`Referer`. A server-side PHP POST sends neither header, and that check
is written `if origin:` — so it passes vacuously. Tolerable for PHP warnings;
not for a payload carrying usernames, email addresses and IPs.

The per-site `wp_sso_secret` already exists on both ends, so signing the body
costs nothing new. The replay window matches MalCare's `bvTime` guard.
"""
from __future__ import annotations

import hashlib
import hmac
import time

REPLAY_WINDOW_SECONDS = 300


def verify_signature(
    secret: str,
    timestamp: str,
    raw_body: bytes,
    signature: str,
    now: int | None = None,
) -> bool:
    """True if `signature` is a valid HMAC for this body and is not stale.

    The window is two-sided: a timestamp far in the future is as suspect as one
    far in the past, and clock skew on the client's server is real, so the
    tolerance is symmetric rather than past-only.
    """
    if not secret or not signature:
        return False
    try:
        sent_at = int(timestamp)
    except (TypeError, ValueError):
        return False

    current = int(time.time()) if now is None else now
    if abs(current - sent_at) > REPLAY_WINDOW_SECONDS:
        return False

    message = timestamp.encode() + b"." + raw_body
    expected = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.strip().lower())
