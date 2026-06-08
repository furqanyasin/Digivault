"""WebSocket consumer for real-time in-app alert delivery.

Connection flow:
  1. Client supplies a JWT access token, preferring header-based auth:
       - Sec-WebSocket-Protocol: bearer, <token>   (browser-friendly)
       - Authorization: Bearer <token>             (non-browser clients)
       - ?token=<token>                            (legacy fallback; may leak in logs)
  2. Consumer validates the token with SimpleJWT.
  3. On success: joins team-scoped channel group and sends a hello frame
     (echoing the "bearer" subprotocol when header auth was used).
  4. On failure: closes immediately with code 4001 (auth error).

Push flow (server → client):
  The Celery deliver_notification task calls push_notification() which sends
  to the Redis channel layer group for the team.  The consumer broadcasts it
  to all open WebSocket connections for that team.
"""

from __future__ import annotations

import json
import logging

from channels.generic.websocket import AsyncWebsocketConsumer
from django.contrib.auth.models import AnonymousUser

logger = logging.getLogger(__name__)


def _team_group_name(team_id) -> str:
    return f"alerts_team_{team_id}"


class AlertConsumer(AsyncWebsocketConsumer):
    """One connection per browser tab.  Messages flow server → client only."""

    async def connect(self):
        token_str, subprotocol = self._extract_token(self.scope)
        user, team = await self._authenticate(token_str)
        if user is None or team is None:
            await self.close(code=4001)
            return

        self.user = user
        self.team = team
        self.group_name = _team_group_name(team.pk)

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        # Echo the negotiated subprotocol when the client authenticated via header.
        if subprotocol:
            await self.accept(subprotocol=subprotocol)
        else:
            await self.accept()
        await self.send(text_data=json.dumps({"type": "connection_established"}))

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        # Client → server messages are not expected; silently ignore.
        pass

    # ------------------------------------------------------------------
    # Channel layer message handlers
    # ------------------------------------------------------------------

    async def alert_notification(self, event):
        """Receive a push from the channel layer and forward to WebSocket."""
        await self.send(text_data=json.dumps(event["payload"]))

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    async def _authenticate(self, token_str: str | None):
        """Validate a JWT token. Returns (user, team) or (None, None).

        Runs DB queries via sync_to_async so as not to block the event loop.
        """
        from channels.db import database_sync_to_async

        if not token_str:
            return None, None
        return await database_sync_to_async(self._validate_token)(token_str)

    @classmethod
    def _extract_token(cls, scope) -> tuple[str | None, str | None]:
        """Resolve the JWT, preferring header-based auth over the query string.

        Order:
          1. Sec-WebSocket-Protocol subprotocol: ["bearer", "<token>"]
             (browser-friendly — browsers can't set arbitrary WS headers).
             Returns the token + the "bearer" subprotocol to echo on accept.
          2. Authorization: Bearer <token> header (non-browser clients).
          3. ?token=<token> query string (legacy fallback; may leak in logs).

        Returns (token, subprotocol_to_echo). subprotocol is None unless #1 used.
        """
        # 1. Subprotocol
        subprotocols = scope.get("subprotocols") or []
        if len(subprotocols) >= 2 and subprotocols[0].lower() == "bearer":
            return subprotocols[1], "bearer"

        # 2. Authorization header
        for name, value in scope.get("headers", []) or []:
            if name == b"authorization":
                decoded = value.decode()
                if decoded.lower().startswith("bearer "):
                    return decoded[7:].strip(), None

        # 3. Query string (legacy)
        token = cls._parse_token(scope.get("query_string", b"").decode())
        return token, None

    @staticmethod
    def _parse_token(query_string: str) -> str | None:
        for part in query_string.split("&"):
            if part.startswith("token="):
                return part[len("token="):]
        return None

    @staticmethod
    def _validate_token(token_str: str):
        """Synchronous JWT validation — called via database_sync_to_async."""
        try:
            from rest_framework_simplejwt.tokens import AccessToken
            from apps.accounts.models import User

            token = AccessToken(token_str)
            user = User.objects.select_related("active_team").get(pk=token["user_id"])
            team = user.active_team
            if team is None:
                return None, None
            return user, team
        except Exception:
            return None, None


# ------------------------------------------------------------------
# Push helper — called from Celery tasks
# ------------------------------------------------------------------

def push_notification(notification) -> None:
    """Push a notification payload to the team's WebSocket group.

    This is a synchronous function — the Celery task calls it after saving
    the Notification record.  It uses get_channel_layer() + async_to_sync
    so it can be called from non-async code.
    """
    from asgiref.sync import async_to_sync
    from channels.layers import get_channel_layer

    layer = get_channel_layer()
    if layer is None:
        logger.warning("push_notification: channel layer not configured")
        return

    payload = {
        "id": str(notification.pk),
        "channel": notification.channel,
        "website": {
            "id": str(notification.website_id),
            "name": notification.website.name,
            "domain": notification.website.domain,
        },
        "delivery_status": notification.delivery_status,
        "read": notification.read,
        "created_at": notification.created_at.isoformat(),
    }

    if notification.script_change:
        change = notification.script_change
        payload["script_change"] = {
            "id": str(change.pk),
            "change_type": change.change_type,
            "severity": change.severity,
            "description": change.description,
        }

    group_name = _team_group_name(notification.team_id)
    try:
        async_to_sync(layer.group_send)(
            group_name,
            {"type": "alert.notification", "payload": payload},
        )
    except Exception as exc:
        logger.exception("push_notification: failed to push to %s — %s", group_name, exc)
