from google.protobuf import timestamp_pb2 as _timestamp_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class DeviceInfo(_message.Message):
    __slots__ = ("id", "tenant_id", "name", "hostname", "description", "status", "connection_status", "firmware_version", "agent_version", "model", "serial_number", "ip_address", "site_id", "group_id", "is_ha", "ha_role", "tags", "last_seen_at", "created_at", "updated_at")
    ID_FIELD_NUMBER: _ClassVar[int]
    TENANT_ID_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    HOSTNAME_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    CONNECTION_STATUS_FIELD_NUMBER: _ClassVar[int]
    FIRMWARE_VERSION_FIELD_NUMBER: _ClassVar[int]
    AGENT_VERSION_FIELD_NUMBER: _ClassVar[int]
    MODEL_FIELD_NUMBER: _ClassVar[int]
    SERIAL_NUMBER_FIELD_NUMBER: _ClassVar[int]
    IP_ADDRESS_FIELD_NUMBER: _ClassVar[int]
    SITE_ID_FIELD_NUMBER: _ClassVar[int]
    GROUP_ID_FIELD_NUMBER: _ClassVar[int]
    IS_HA_FIELD_NUMBER: _ClassVar[int]
    HA_ROLE_FIELD_NUMBER: _ClassVar[int]
    TAGS_FIELD_NUMBER: _ClassVar[int]
    LAST_SEEN_AT_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    UPDATED_AT_FIELD_NUMBER: _ClassVar[int]
    id: str
    tenant_id: str
    name: str
    hostname: str
    description: str
    status: str
    connection_status: str
    firmware_version: str
    agent_version: str
    model: str
    serial_number: str
    ip_address: str
    site_id: str
    group_id: str
    is_ha: bool
    ha_role: str
    tags: _containers.RepeatedScalarFieldContainer[str]
    last_seen_at: _timestamp_pb2.Timestamp
    created_at: _timestamp_pb2.Timestamp
    updated_at: _timestamp_pb2.Timestamp
    def __init__(self, id: _Optional[str] = ..., tenant_id: _Optional[str] = ..., name: _Optional[str] = ..., hostname: _Optional[str] = ..., description: _Optional[str] = ..., status: _Optional[str] = ..., connection_status: _Optional[str] = ..., firmware_version: _Optional[str] = ..., agent_version: _Optional[str] = ..., model: _Optional[str] = ..., serial_number: _Optional[str] = ..., ip_address: _Optional[str] = ..., site_id: _Optional[str] = ..., group_id: _Optional[str] = ..., is_ha: bool = ..., ha_role: _Optional[str] = ..., tags: _Optional[_Iterable[str]] = ..., last_seen_at: _Optional[_Union[_timestamp_pb2.Timestamp, _Mapping]] = ..., created_at: _Optional[_Union[_timestamp_pb2.Timestamp, _Mapping]] = ..., updated_at: _Optional[_Union[_timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class GetDeviceRequest(_message.Message):
    __slots__ = ("tenant_id", "device_id")
    TENANT_ID_FIELD_NUMBER: _ClassVar[int]
    DEVICE_ID_FIELD_NUMBER: _ClassVar[int]
    tenant_id: str
    device_id: str
    def __init__(self, tenant_id: _Optional[str] = ..., device_id: _Optional[str] = ...) -> None: ...

class ListDevicesRequest(_message.Message):
    __slots__ = ("tenant_id", "page", "size", "status", "search")
    TENANT_ID_FIELD_NUMBER: _ClassVar[int]
    PAGE_FIELD_NUMBER: _ClassVar[int]
    SIZE_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    SEARCH_FIELD_NUMBER: _ClassVar[int]
    tenant_id: str
    page: int
    size: int
    status: str
    search: str
    def __init__(self, tenant_id: _Optional[str] = ..., page: _Optional[int] = ..., size: _Optional[int] = ..., status: _Optional[str] = ..., search: _Optional[str] = ...) -> None: ...

class ListDevicesResponse(_message.Message):
    __slots__ = ("devices", "page", "size", "total", "pages")
    DEVICES_FIELD_NUMBER: _ClassVar[int]
    PAGE_FIELD_NUMBER: _ClassVar[int]
    SIZE_FIELD_NUMBER: _ClassVar[int]
    TOTAL_FIELD_NUMBER: _ClassVar[int]
    PAGES_FIELD_NUMBER: _ClassVar[int]
    devices: _containers.RepeatedCompositeFieldContainer[DeviceInfo]
    page: int
    size: int
    total: int
    pages: int
    def __init__(self, devices: _Optional[_Iterable[_Union[DeviceInfo, _Mapping]]] = ..., page: _Optional[int] = ..., size: _Optional[int] = ..., total: _Optional[int] = ..., pages: _Optional[int] = ...) -> None: ...

class GetFleetSummaryRequest(_message.Message):
    __slots__ = ("tenant_id",)
    TENANT_ID_FIELD_NUMBER: _ClassVar[int]
    tenant_id: str
    def __init__(self, tenant_id: _Optional[str] = ...) -> None: ...

class FleetSummary(_message.Message):
    __slots__ = ("total", "online", "offline", "error", "maintenance", "unregistered", "registered", "ha_devices", "drift_findings", "generated_at")
    TOTAL_FIELD_NUMBER: _ClassVar[int]
    ONLINE_FIELD_NUMBER: _ClassVar[int]
    OFFLINE_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    MAINTENANCE_FIELD_NUMBER: _ClassVar[int]
    UNREGISTERED_FIELD_NUMBER: _ClassVar[int]
    REGISTERED_FIELD_NUMBER: _ClassVar[int]
    HA_DEVICES_FIELD_NUMBER: _ClassVar[int]
    DRIFT_FINDINGS_FIELD_NUMBER: _ClassVar[int]
    GENERATED_AT_FIELD_NUMBER: _ClassVar[int]
    total: int
    online: int
    offline: int
    error: int
    maintenance: int
    unregistered: int
    registered: int
    ha_devices: int
    drift_findings: int
    generated_at: _timestamp_pb2.Timestamp
    def __init__(self, total: _Optional[int] = ..., online: _Optional[int] = ..., offline: _Optional[int] = ..., error: _Optional[int] = ..., maintenance: _Optional[int] = ..., unregistered: _Optional[int] = ..., registered: _Optional[int] = ..., ha_devices: _Optional[int] = ..., drift_findings: _Optional[int] = ..., generated_at: _Optional[_Union[_timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...
