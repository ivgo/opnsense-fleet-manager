"""Domain value objects: immutable, self-validating primitives shared by services."""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")
PORT_SPEC_RE = re.compile(r"^\d{1,5}(-\d{1,5})?$")


@dataclass(frozen=True, slots=True)
class Cidr:
    value: str

    def __post_init__(self) -> None:
        try:
            ipaddress.ip_network(self.value, strict=False)
        except ValueError as exc:
            raise ValueError(f"Invalid CIDR: {self.value}") from exc

    @property
    def network(self) -> ipaddress._BaseNetwork:  # type: ignore[name-defined]
        return ipaddress.ip_network(self.value, strict=False)

    def contains(self, address: str) -> bool:
        try:
            return ipaddress.ip_address(address) in self.network
        except ValueError:
            return False

    def overlaps(self, other: Cidr) -> bool:
        return self.network.overlaps(other.network)


@dataclass(frozen=True, slots=True)
class MacAddress:
    value: str

    def __post_init__(self) -> None:
        if not MAC_RE.match(self.value):
            raise ValueError(f"Invalid MAC address: {self.value}")
        object.__setattr__(self, "value", self.value.upper())

    @property
    def oui(self) -> str:
        return self.value[:8]


@dataclass(frozen=True, slots=True)
class PortRange:
    start: int
    end: int

    def __post_init__(self) -> None:
        if not (0 < self.start <= 65535 and 0 < self.end <= 65535):
            raise ValueError("Port must be within 1..65535")
        if self.end < self.start:
            raise ValueError("Port range end must be >= start")

    @classmethod
    def parse(cls, spec: str) -> PortRange:
        spec = spec.strip()
        if not PORT_SPEC_RE.match(spec):
            raise ValueError(f"Invalid port specification: {spec}")
        if "-" in spec:
            start, _, end = spec.partition("-")
            return cls(int(start), int(end))
        return cls(int(spec), int(spec))

    def contains(self, port: int) -> bool:
        return self.start <= port <= self.end

    def __str__(self) -> str:
        return str(self.start) if self.start == self.end else f"{self.start}-{self.end}"


@dataclass(frozen=True, slots=True)
class PortSet:
    ranges: tuple[PortRange, ...]

    @classmethod
    def parse(cls, spec: str | None) -> PortSet:
        if spec in {None, "", "any"}:
            return cls(())
        return cls(tuple(PortRange.parse(part) for part in spec.split(",") if part.strip()))

    @property
    def is_any(self) -> bool:
        return not self.ranges

    def contains(self, port: int) -> bool:
        return self.is_any or any(item.contains(port) for item in self.ranges)

    def overlaps(self, other: PortSet) -> bool:
        if self.is_any or other.is_any:
            return True
        return any(a.start <= b.end and b.start <= a.end for a in self.ranges for b in other.ranges)

    def __iter__(self) -> Iterator[PortRange]:
        return iter(self.ranges)


@dataclass(frozen=True, slots=True)
class AddressSpec:
    """A firewall address: ``any``, alias name, CIDR or host address."""

    value: str

    @property
    def is_any(self) -> bool:
        return self.value in {"", "any"}

    @property
    def is_alias(self) -> bool:
        return bool(re.fullmatch(r"[A-Za-z0-9_]+", self.value)) and not self.is_any

    def networks(self) -> list[ipaddress._BaseNetwork]:  # type: ignore[name-defined]
        if self.is_any:
            return [
                ipaddress.ip_network("0.0.0.0/0"),
                ipaddress.ip_network("::/0"),
            ]
        candidates: list[str] = []
        if "/" in self.value:
            candidates.append(self.value)
        else:
            try:
                address = ipaddress.ip_address(self.value)
            except ValueError:
                return []
            candidates.append(f"{address}/{32 if address.version == 4 else 128}")
        result = []
        for candidate in candidates:
            try:
                result.append(ipaddress.ip_network(candidate, strict=False))
            except ValueError:
                continue
        return result

    def overlaps(self, other: AddressSpec) -> bool:
        if self.is_any or other.is_any:
            return True
        left, right = self.networks(), other.networks()
        return any(a.version == b.version and a.overlaps(b) for a in left for b in right)


@dataclass(frozen=True, slots=True)
class SubnetPlan:
    """Deterministic /31 point-to-point allocation for SD-WAN tunnel addressing."""

    base: Cidr
    prefix: int = 31

    def allocate(self, index: int) -> tuple[str, str]:
        network = self.base.network
        subnets = network.subnets(new_prefix=self.prefix)
        for position, subnet in enumerate(subnets):
            if position == index:
                hosts = list(subnet.hosts())
                if len(hosts) >= 2:
                    return str(hosts[0]), str(hosts[1])
                return str(subnet.network_address), str(subnet.broadcast_address)
        raise IndexError(f"Subnet index {index} exceeds pool capacity")


@dataclass(frozen=True, slots=True)
class Severity:
    """Ordered severity used by alerts, findings and prioritisation."""

    value: str

    _ORDER = {"info": 0, "low": 1, "medium": 2, "warning": 3, "high": 4, "critical": 5}

    def rank(self) -> int:
        return self._ORDER.get(self.value.lower(), 0)

    def __lt__(self, other: Severity) -> bool:
        return self.rank() < other.rank()

    @classmethod
    def highest(cls, values: Iterable[str]) -> str:
        return max(values, key=lambda v: cls._ORDER.get(v.lower(), 0), default="info")
