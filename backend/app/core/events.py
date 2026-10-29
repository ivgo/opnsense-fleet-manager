"""In-process asynchronous domain event bus.

Handlers are registered at startup. The bus is deliberately transport-agnostic so
that it can be swapped for Kafka/NATS without touching domain code.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, TypeVar

from app.core.logging import get_logger

log = get_logger("ofme.events")


@dataclass(frozen=True, slots=True)
class DomainEvent:
    event_type: str
    aggregate_type: str
    aggregate_id: str
    tenant_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def as_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "aggregate_type": self.aggregate_type,
            "aggregate_id": self.aggregate_id,
            "tenant_id": self.tenant_id,
            "payload": self.payload,
            "occurred_at": self.occurred_at.isoformat(),
        }


Handler = Callable[[DomainEvent], Awaitable[None]]
E = TypeVar("E", bound=DomainEvent)


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = defaultdict(list)
        self._wildcard: list[Handler] = []

    def subscribe(self, event_type: str, handler: Handler) -> None:
        self._handlers[event_type].append(handler)
        log.debug("event.subscribed", event_type=event_type, handler=handler.__qualname__)

    def subscribe_all(self, handler: Handler) -> None:
        self._wildcard.append(handler)

    async def publish(self, event: DomainEvent) -> None:
        handlers = [*self._handlers.get(event.event_type, []), *self._wildcard]
        if not handlers:
            return
        results = await asyncio.gather(*(self._safe(h, event) for h in handlers), return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                log.exception("event.handler_failed", event_type=event.event_type, error=str(result))

    async def publish_many(self, events: list[DomainEvent]) -> None:
        for event in events:
            await self.publish(event)

    @staticmethod
    async def _safe(handler: Handler, event: DomainEvent) -> None:
        await handler(event)


event_bus = EventBus()


# --------------------------------------------------------------------------- catalog
class DeviceRegistered(DomainEvent):
    def __init__(self, device_id: str, tenant_id: str, name: str, serial_number: str | None = None) -> None:
        super().__init__(
            event_type="device.registered",
            aggregate_type="Device",
            aggregate_id=device_id,
            tenant_id=tenant_id,
            payload={"name": name, "serial_number": serial_number},
        )


class DeviceStatusChanged(DomainEvent):
    def __init__(self, device_id: str, tenant_id: str, status: str, previous: str | None = None) -> None:
        super().__init__(
            event_type="device.status_changed",
            aggregate_type="Device",
            aggregate_id=device_id,
            tenant_id=tenant_id,
            payload={"status": status, "previous": previous},
        )


class PolicyDeployed(DomainEvent):
    def __init__(
        self, policy_id: str, deployment_id: str, tenant_id: str, environment: str, status: str
    ) -> None:
        super().__init__(
            event_type="policy.deployed",
            aggregate_type="Policy",
            aggregate_id=policy_id,
            tenant_id=tenant_id,
            payload={"deployment_id": deployment_id, "environment": environment, "status": status},
        )


class DriftDetected(DomainEvent):
    def __init__(self, device_id: str, tenant_id: str, policy_id: str, differences: int) -> None:
        super().__init__(
            event_type="compliance.drift_detected",
            aggregate_type="Device",
            aggregate_id=device_id,
            tenant_id=tenant_id,
            payload={"policy_id": policy_id, "differences": differences},
        )


class AlertRaised(DomainEvent):
    def __init__(
        self, alert_id: str, tenant_id: str, severity: str, title: str, device_id: str | None = None
    ) -> None:
        super().__init__(
            event_type="monitoring.alert_raised",
            aggregate_type="Alert",
            aggregate_id=alert_id,
            tenant_id=tenant_id,
            payload={"severity": severity, "title": title, "device_id": device_id},
        )


class TunnelStateChanged(DomainEvent):
    def __init__(self, tunnel_id: str, tenant_id: str, status: str, topology_id: str) -> None:
        super().__init__(
            event_type="sdwan.tunnel_state_changed",
            aggregate_type="VpnTunnel",
            aggregate_id=tunnel_id,
            tenant_id=tenant_id,
            payload={"status": status, "topology_id": topology_id},
        )
