"""CORS for the public ingest endpoints.

The dashboard API is correctly locked to `CORS_ALLOWED_ORIGINS`: it is
authenticated and serves one known origin. The ingest endpoints are the exact
opposite. Every client website that embeds the snippet posts to them from its
own origin, so an allowlist can never be complete — and worse, it fails
silently: a newly onboarded site reports nothing at all until somebody
remembers to edit an env var and redeploy. That is what happened to
a live client site, whose snippet POSTs were rejected at the preflight with
"No 'Access-Control-Allow-Origin' header is present".

`Access-Control-Allow-Origin: *` here is a description of the trust model, not
a loosening of it. These endpoints are `AllowAny` by design and carry no
cookies, no session and no Authorization header: a request is authorised by
the `site_id` in its body and bounded by `IngestThrottle`. Because the header
is a literal `*`, browsers refuse to send credentials with these requests at
all, so the permissive value cannot be leveraged to read an authenticated
response.

Deliberately a middleware rather than `CORS_ALLOW_ALL_ORIGINS` +
`CORS_URLS_REGEX`: that pair would relax the policy for the whole app or, if
scoped, strip CORS from the dashboard API entirely — which breaks local
development, where the frontend runs on a different origin (localhost:3000)
than the API. Keeping the two policies in separate layers means neither can
quietly widen the other.
"""
from __future__ import annotations

from django.http import HttpResponse

# Public, unauthenticated endpoints reached cross-origin from client websites.
# `/api/s.js` is a plain <script> include that needs no CORS, but fetching it
# with fetch()/XHR is a legitimate way to verify installation, so it is included.
PUBLIC_PREFIXES = (
    "/api/ingest/",
    "/api/php-errors/",
    "/api/s.js",
)

ALLOWED_METHODS = "POST, GET, OPTIONS"
ALLOWED_HEADERS = "Content-Type"
PREFLIGHT_MAX_AGE = "86400"  # 24h — these endpoints' policy never varies.


def is_public_ingest_path(path: str) -> bool:
    """True when `path` is one of the public, cross-origin ingest endpoints."""
    return path.startswith(PUBLIC_PREFIXES)


class PublicIngestCorsMiddleware:
    """Answer preflights and allow any origin on the public ingest endpoints.

    Placed ahead of `CorsMiddleware` in the stack so that on the response path
    (which runs outermost-last) these headers are the final word, and so a
    preflight is answered before CSRF or CommonMiddleware sees it.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not is_public_ingest_path(request.path):
            return self.get_response(request)

        if request.method == "OPTIONS":
            # Preflight: answer directly. DRF would return a 200 with metadata,
            # which works but is a needless view dispatch on every client page
            # load that posts JSON.
            response = HttpResponse(status=204)
        else:
            response = self.get_response(request)

        response["Access-Control-Allow-Origin"] = "*"
        response["Access-Control-Allow-Methods"] = ALLOWED_METHODS
        response["Access-Control-Allow-Headers"] = ALLOWED_HEADERS
        response["Access-Control-Max-Age"] = PREFLIGHT_MAX_AGE
        # No Access-Control-Allow-Credentials: with a literal "*" origin it is
        # invalid, and these endpoints must never accept credentials.
        return response
