"""WebSocket transport: authenticated topic subscriptions with Redis fan-out.

Wire protocol (JSON text frames)
--------------------------------
Client -> server::

    {"action": "subscribe",   "topics": ["devices", "alerts"]}
    {"action": "unsubscribe", "topics": ["alerts"]}
    {"action": "ping"}

Server -> client::

    {"type": "ready",       "topics": [...], "tenant_id": "...", "userId": "..."}
    {"type": "event",       "topic": "devices", "event": "device.status_changed",
     "data": {...}, "ts": "2026-01-01T00:00:00+00:00"}
    {"type": "pong",        "ts": "..."}
    {"type": "error",       "code": "unauthenticated", "message": "..."}

Cross-process fan-out uses the Redis channel ``ofme:ws`` so that events produced by
Celery workers reach browsers connected to any API replica.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.api.deps import Principal, principal_from_token
from app.core.config import settings
from app.core.events import DomainEvent, event_bus
from app.core.exceptions import AuthenticationError
from app.core.logging import get_logger
from app.db.session import async_session_factory

log = get_logger("ofme.ws")

router = APIRouter()

REDIS_CHANNEL = "ofme:ws"
ALLOWED_TOPICS = {
    "fleet",
    "devices",
    "alerts",
    "metrics",
    "deployments",
    "policies",
    "tunnels",
    "backups",
    "compliance",
    "audit",
    "jobs",
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(slots=True, eq=False)
class Connection:
    websocket: WebSocket
    principal: Principal
    topics: set[str] = field(default_factory=lambda: {"fleet"})
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def tenant_id(self) -> uuid.UUID | None:
        return self.principal.tenant_id

    async def send(self, payload: dict[str, Any]) -> None:
        async with self.send_lock:
            await self.websocket.send_text(json.dumps(payload, default=str))

    async def send_event(self, topic: str, event: str, data: dict[str, Any]) -> None:
        await self.send({"type": "event", "topic": topic, "event": event, "data": data, "ts": _now()})


class WebSocketHub:
    def __init__(self) -> None:
        self._connections: dict[str, Connection] = {}
        self._redis: Any | None = None
        self._listener: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------ lifecycle
    async def connect(self, connection: Connection) -> str:
        connection_id = uuid.uuid4().hex
        self._connections[connection_id] = connection
        log.info(
            "ws.connected",
            connection_id=connection_id,
            user=connection.principal.username,
            tenant=str(connection.tenant_id),
        )
        return connection_id

    async def disconnect(self, connection_id: str) -> None:
        connection = self._connections.pop(connection_id, None)
        if connection is not None:
            log.info("ws.disconnected", connection_id=connection_id)

    @property
    def connection_count(self) -> int:
        return len(self._connections)

    # ------------------------------------------------------------------ redis bus
    async def start(self) -> None:
        if self._listener and not self._listener.done():
            return
        try:
            from redis.asyncio import Redis

            self._redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
            await self._redis.ping()
        except Exception as exc:  # noqa: BLE001 - degraded mode without Redis
            log.warning("ws.redis_unavailable", error=str(exc))
            self._redis = None
            return
        self._listener = asyncio.create_task(self._listen(), name="ofme-ws-redis")
        log.info("ws.redis_listener_started", channel=REDIS_CHANNEL)

    async def stop(self) -> None:
        if self._listener:
            self._listener.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._listener
            self._listener = None
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None

    async def _listen(self) -> None:
        assert self._redis is not None
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(REDIS_CHANNEL)
        try:
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                try:
                    envelope = json.loads(message["data"])
                except (TypeError, ValueError):
                    continue
                await self._local_broadcast(
                    tenant=str(envelope.get("tenant_id") or ""),
                    topic=str(envelope.get("topic") or "fleet"),
                    event=str(envelope.get("event") or "message"),
                    data=envelope.get("data") or {},
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - reconnect handled by supervisor
            log.warning("ws.redis_listener_error", error=str(exc))
        finally:
            await pubsub.unsubscribe(REDIS_CHANNEL)
            await pubsub.aclose()

    async def publish(self, *, tenant_id: str | None, topic: str, event: str, data: dict[str, Any]) -> None:
        envelope = {
            "tenant_id": tenant_id,
            "topic": topic,
            "event": event,
            "data": data,
            "ts": _now(),
        }
        if self._redis is not None:
            try:
                await self._redis.publish(REDIS_CHANNEL, json.dumps(envelope, default=str))
                return
            except Exception as exc:  # noqa: BLE001 - fall back to in-process delivery
                log.warning("ws.redis_publish_failed", error=str(exc))
        await self._local_broadcast(tenant=tenant_id or "", topic=topic, event=event, data=data)

    # ------------------------------------------------------------------ delivery
    async def _local_broadcast(self, *, tenant: str, topic: str, event: str, data: dict[str, Any]) -> None:
        targets = [
            connection
            for connection in self._connections.values()
            if topic in connection.topics
            and (connection.principal.is_superadmin or (tenant and str(connection.tenant_id) == tenant))
        ]
        if not targets:
            return
        results = await asyncio.gather(
            *(connection.send_event(topic, event, data) for connection in targets),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, Exception):
                log.debug("ws.send_failed", error=str(result))

    async def send_to_user(self, user_id: uuid.UUID, topic: str, event: str, data: dict[str, Any]) -> None:
        for connection in self._connections.values():
            if connection.principal.user_id == user_id:
                with contextlib.suppress(Exception):  # stale socket
                    await connection.send_event(topic, event, data)


hub = WebSocketHub()


# --------------------------------------------------------------------------- domain event bridge
TOPIC_BY_AGGREGATE = {
    "Device": "devices",
    "Alert": "alerts",
    "Policy": "deployments",
    "VpnTunnel": "tunnels",
    "ComplianceReport": "compliance",
    "Backup": "backups",
}


async def forward_domain_event(event: DomainEvent) -> None:
    topic = TOPIC_BY_AGGREGATE.get(event.aggregate_type, "fleet")
    await hub.publish(
        tenant_id=event.tenant_id,
        topic=topic,
        event=event.event_type,
        data={
            "aggregate_type": event.aggregate_type,
            "aggregate_id": event.aggregate_id,
            "event_id": event.event_id,
            "occurred_at": event.occurred_at.isoformat(),
            **event.payload,
        },
    )


def wire_event_forwarding() -> None:
    event_bus.subscribe_all(forward_domain_event)


# --------------------------------------------------------------------------- endpoint
async def _authenticate(token: str) -> Principal:
    async with async_session_factory() as session:
        return await principal_from_token(session, token)


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(None, description="Legacy fallback; prefer cookie-based auth"),
) -> None:
    """WebSocket endpoint with secure token authentication.

    Authentication priority:
    1. HttpOnly ``ofme_access_token`` cookie (browser default, no token in URL)
    2. ``ofme-auth`` Sec-WebSocket-Protocol subprotocol (non-browser clients)
    3. Legacy ``?token=`` query parameter (backward compatibility only)

    Tokens are never sent in the URL for browser clients, preventing exposure
    in browser history, proxy logs and server access logs.
    """
    # Primary: HttpOnly cookie (browser sends automatically)
    auth_token = websocket.cookies.get("ofme_access_token")

    # Secondary: subprotocol header for non-browser clients
    if not auth_token:
        subprotocols = websocket.headers.get("sec-websocket-protocol", "")
        for proto in subprotocols.split(","):
            proto = proto.strip()
            if proto.startswith("ofme-auth."):
                auth_token = proto[len("ofme-auth."):]
                break

    # Tertiary: legacy query parameter
    if not auth_token and token:
        auth_token = token

    if not auth_token:
        await websocket.accept()
        await websocket.send_text(
            json.dumps({"type": "error", "code": "unauthenticated", "message": "Missing auth token"})
        )
        await websocket.close(code=4401)
        return

    try:
        principal = await _authenticate(auth_token)
    except AuthenticationError as exc:
        await websocket.accept()
        await websocket.send_text(
            json.dumps({"type": "error", "code": "unauthenticated", "message": str(exc)})
        )
        await websocket.close(code=4401)
        return

    await websocket.accept()
    connection = Connection(websocket=websocket, principal=principal)
    connection_id = await hub.connect(connection)
    await connection.send(
        {
            "type": "ready",
            "topics": sorted(connection.topics),
            "available_topics": sorted(ALLOWED_TOPICS),
            "tenant_id": str(principal.tenant_id) if principal.tenant_id else None,
            "userId": str(principal.user_id) if principal.user_id else None,
            "server_time": _now(),
        }
    )

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                message = json.loads(raw)
            except ValueError:
                await connection.send({"type": "error", "code": "bad_json", "message": "Invalid JSON frame"})
                continue

            action = str(message.get("action", "")).lower()
            if action == "ping":
                await connection.send({"type": "pong", "ts": _now()})
            elif action in {"subscribe", "unsubscribe"}:
                topics = {str(topic) for topic in message.get("topics", [])}
                unknown = topics - ALLOWED_TOPICS
                if unknown:
                    await connection.send(
                        {
                            "type": "error",
                            "code": "unknown_topic",
                            "message": f"Unknown topics: {', '.join(sorted(unknown))}",
                        }
                    )
                    continue
                if action == "subscribe":
                    connection.topics |= topics
                else:
                    connection.topics -= topics
                await connection.send({"type": "subscribed", "topics": sorted(connection.topics)})
            else:
                await connection.send({"type": "error", "code": "unknown_action", "message": action})
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001 - close cleanly on transport errors
        log.debug("ws.connection_error", error=str(exc))
    finally:
        await hub.disconnect(connection_id)
