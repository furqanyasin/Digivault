"""The one place that answers "what is this request's client address?".

uvicorn resolves it, not the app. Its ProxyHeadersMiddleware runs with
``--forwarded-allow-ips`` set to the private ranges nginx and Docker connect
from (see the compose files), so it walks ``X-Forwarded-For`` from the right and
stops at the first address that is not ours: the one nginx appended, which is
the peer that actually connected. By the time Django sees the request that
answer is in ``REMOTE_ADDR``.

What this replaced: three copies of a helper that read ``X-Forwarded-For``
again and took its *leftmost* entry, while uvicorn ran with
``--forwarded-allow-ips='*'``, which also takes the leftmost. nginx's
``$proxy_add_x_forwarded_for`` appends to whatever the client sent, so the
leftmost entry is whatever the client chose to write. Every audit-log IP was
client-supplied, and DRF's throttles keyed on the raw header (``NUM_PROXIES``
unset), so a new value per request was a fresh rate-limit bucket per request,
on the extension's password-only sign-in among others.

Never parse ``X-Forwarded-For`` in application code. If the address is wrong,
the fix belongs in nginx or in ``--forwarded-allow-ips``.
"""

from __future__ import annotations


def client_ip(request) -> str | None:
    """The client address as resolved by the ASGI server's proxy handling."""
    return request.META.get("REMOTE_ADDR") or None
