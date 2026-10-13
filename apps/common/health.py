"""Liveness and readiness for the API container.

The platform sells monitoring and had none of its own. There was no health
endpoint, no container healthcheck on api, celery or beat, and the only
self-observation was an optional outbound heartbeat ping from a beat task — so
"the API is up but cannot reach Postgres" and "the API is serving fine" looked
identical from outside, and `depends_on` had nothing to wait for.

Two endpoints, because they answer different questions and confusing them is how
a restart loop starts:

``/api/health/`` — **liveness**. Is this process running? It touches nothing
external. A dependency being down must never make an orchestrator kill the
container, because killing it does not fix Postgres and a flapping API makes
the outage worse.

``/api/ready/`` — **readiness**. Can this process actually serve? It checks
Postgres and Redis. This is the one a load balancer or a deploy gate should
read.

Both are unauthenticated and deliberately terse: they name which dependency
failed, never why. A stack trace on a public endpoint is a gift to whoever is
probing it, and the detail belongs in the logs, which the operator has.
"""

from __future__ import annotations

import logging

from django.db import connection
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger(__name__)


class HealthView(APIView):
    """GET /api/health/ — the process is alive. Never touches a dependency."""

    permission_classes = []
    authentication_classes = []
    throttle_classes = []

    def get(self, request):
        return Response({"status": "ok"})


class ReadyView(APIView):
    """GET /api/ready/ — the process can serve requests.

    503 when a dependency is unreachable, with a per-dependency breakdown so the
    answer is actionable without opening a shell.
    """

    permission_classes = []
    authentication_classes = []
    throttle_classes = []

    def get(self, request):
        checks = {
            "database": self._check_database(),
            "cache": self._check_cache(),
        }
        ok = all(checks.values())
        return Response(
            {"status": "ok" if ok else "degraded", "checks": checks},
            status=status.HTTP_200_OK if ok else status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    @staticmethod
    def _check_database() -> bool:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            return True
        except Exception:
            logger.exception("readiness: database check failed")
            return False

    @staticmethod
    def _check_cache() -> bool:
        """Round-trip a value rather than just connecting.

        A Redis that accepts connections and refuses writes — which is exactly
        what `maxmemory-policy noeviction` does when the instance is full — is
        the failure worth catching here, and a bare PING reports it healthy.
        """
        from django.core.cache import cache

        try:
            cache.set("healthcheck", "1", timeout=10)
            return cache.get("healthcheck") == "1"
        except Exception:
            logger.exception("readiness: cache check failed")
            return False
