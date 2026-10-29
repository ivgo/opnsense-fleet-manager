"""Inventory models for client devices discovered via ARP/DHCP/LLDP.

These models are independent of the existing Device model – they represent *endpoint* devices that are not managed OPNsense firewalls but are observed on the network.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import Column, DateTime, Enum as SAEnum, String, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base


class ClientSource(str, Enum):
    ARP = "arp"
    DHCP = "dhcp"
    LLDP = "lldp"


class ClientStatus(str, Enum):
    ACTIVE = "active"
    BLOCKED = "blocked"
    PAUSED = "paused"


class ClientDevice(Base):
    __tablename__ = "client_devices"
    __table_args__ = (
        Index("ix_client_devices_mac", "mac_address", unique=True),
        Index("ix_client_devices_tenant_source", "tenant_id", "source"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    device_id = Column(UUID(as_uuid=True), ForeignKey("devices.id"), nullable=True, index=True)

    mac_address = Column(String(17), nullable=False)  # AA:BB:CC:DD:EE:FF
    ip_address = Column(String, nullable=True)
    hostname = Column(String, nullable=True)
    vendor = Column(String, nullable=True)

    source = Column(SAEnum(ClientSource), nullable=False)
    status = Column(SAEnum(ClientStatus), nullable=False, default=ClientStatus.ACTIVE)
    paused_until = Column(DateTime, nullable=True)

    first_seen = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_seen = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<ClientDevice {self.mac_address} ({self.ip_address}) status={self.status}>"
