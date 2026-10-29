"""Request and response models for CARP high-availability clusters."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import HaNodeRole
from app.schemas.common import TimestampedModel


class HaNodeCreate(BaseModel):
    device_id: uuid.UUID
    role: HaNodeRole = HaNodeRole.SECONDARY
    advskew: int = Field(100, ge=0, le=254)


class HaNodeOut(TimestampedModel):
    device_id: uuid.UUID
    role: HaNodeRole
    advskew: int
    status: str
    vip_uuid: str | None
    last_seen_at: datetime | None
    details: dict


class HaClusterCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    description: str | None = None
    site_id: uuid.UUID | None = None
    virtual_ip: str = Field(min_length=3, max_length=64)
    interface: str = Field("lan", min_length=1, max_length=32)
    vhid: int = Field(1, ge=1, le=255)
    advbase: int = Field(1, ge=1, le=255)
    password: str | None = Field(None, min_length=1, max_length=128)
    enabled: bool = True
    nodes: list[HaNodeCreate] = Field(default_factory=list)


class HaClusterUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=255)
    description: str | None = None
    site_id: uuid.UUID | None = None
    virtual_ip: str | None = Field(None, min_length=3, max_length=64)
    interface: str | None = Field(None, min_length=1, max_length=32)
    vhid: int | None = Field(None, ge=1, le=255)
    advbase: int | None = Field(None, ge=1, le=255)
    password: str | None = Field(None, min_length=1, max_length=128)
    enabled: bool | None = None


class HaClusterOut(TimestampedModel):
    name: str
    description: str | None
    site_id: uuid.UUID | None
    virtual_ip: str
    interface: str
    vhid: int
    advbase: int
    enabled: bool
    sync_status: str
    last_sync_at: datetime | None
    nodes: list[HaNodeOut]


class HaFailoverResult(BaseModel):
    cluster_id: uuid.UUID
    promoted_device_id: uuid.UUID
    demoted_device_id: uuid.UUID
    applied: bool
    nodes: list[HaNodeOut]
