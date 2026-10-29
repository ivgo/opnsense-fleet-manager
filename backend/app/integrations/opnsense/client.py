"""Typed asynchronous client for the OPNsense REST API.

Endpoint availability differs between OPNsense releases; the client is written
defensively: optional endpoints degrade to ``None`` instead of failing a whole
telemetry cycle. All errors are normalised to :class:`UpstreamError`.
"""

from __future__ import annotations

import base64
import ssl
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import settings
from app.core.exceptions import UpstreamError
from app.core.logging import get_logger
from app.services.traffic import normalise_counters

log = get_logger("ofme.opnsense")


@dataclass(slots=True)
class OpnsenseCredentials:
    base_url: str
    api_key: str
    api_secret: str
    verify_tls: bool = True
    timeout: float = 20.0


@dataclass(slots=True)
class HealthSnapshot:
    reachable: bool
    firmware_version: str | None = None
    hostname: str | None = None
    uptime_seconds: int | None = None
    cpu_pct: float | None = None
    memory_pct: float | None = None
    disk_pct: float | None = None
    load_1m: float | None = None
    sessions: int | None = None
    vpn_up: int = 0
    vpn_total: int = 0
    gateways_up: int = 0
    gateways_total: int = 0
    carp_status: str | None = None
    interfaces: list[dict[str, Any]] = field(default_factory=list)
    traffic: dict[str, Any] | None = None
    error: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def as_heartbeat(self) -> dict[str, Any]:
        return {
            "firmware_version": self.firmware_version,
            "hostname": self.hostname,
            "uptime_seconds": self.uptime_seconds,
            "cpu_pct": self.cpu_pct,
            "memory_pct": self.memory_pct,
            "disk_pct": self.disk_pct,
            "load_1m": self.load_1m,
            "sessions": self.sessions,
            "vpn_up": self.vpn_up,
            "vpn_total": self.vpn_total,
            "gateways_up": self.gateways_up,
            "gateways_total": self.gateways_total,
            "carp_status": self.carp_status,
            "interfaces": self.interfaces,
            "traffic": self.traffic,
        }


def _number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    text = str(value).strip().rstrip("%")
    try:
        return float(text)
    except ValueError:
        return None


class OpnsenseClient:
    def __init__(self, credentials: OpnsenseCredentials) -> None:
        self.credentials = credentials
        # Use OPNsense native API key header authentication (preferred over Basic Auth)
        # See: https://docs.opnsense.org/development/api.html#authentication
        self._headers = {
            "Authorization": f"Bearer {credentials.api_key}",
            "X-OPNsense-API-Key": credentials.api_key,
            "X-OPNsense-API-Secret": credentials.api_secret,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "OFME/1.0",
        }
        verify: bool | ssl.SSLContext = credentials.verify_tls
        if credentials.verify_tls is False:
            verify = ssl.create_default_context()
            verify.check_hostname = False
            verify.verify_mode = ssl.CERT_NONE
        self._client = httpx.AsyncClient(
            base_url=credentials.base_url.rstrip("/"),
            headers=self._headers,
            timeout=credentials.timeout,
            verify=verify,
            follow_redirects=True,
        )

    async def __aenter__(self) -> OpnsenseClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------ transport
    @retry(
        retry=retry_if_exception_type((httpx.TransportError, httpx.TimeoutException)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, max=4),
        reraise=True,
    )
    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = await self._client.request(method, path, **kwargs)
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            raise UpstreamError(f"OPNsense unreachable at {self.credentials.base_url}: {exc}") from exc

        if response.status_code >= 400:
            raise UpstreamError(
                f"OPNsense API {method} {path} returned {response.status_code}",
                details=response.text[:1000],
            )
        if not response.content:
            return {}
        try:
            payload = response.json()
        except ValueError as exc:
            raise UpstreamError(f"OPNsense returned non-JSON payload for {path}") from exc
        return payload if isinstance(payload, dict) else {"data": payload}

    async def _optional(self, method: str, path: str, **kwargs: Any) -> dict[str, Any] | None:
        try:
            return await self._request(method, path, **kwargs)
        except UpstreamError as exc:
            log.debug("opnsense.optional_endpoint_failed", path=path, error=str(exc))
            return None

    # ------------------------------------------------------------------ system
    async def firmware_status(self) -> dict[str, Any] | None:
        return await self._optional("GET", "/api/core/firmware/status")

    async def firmware_info(self) -> dict[str, Any] | None:
        return await self._optional("GET", "/api/core/firmware/info")

    async def system_status(self) -> dict[str, Any] | None:
        return await self._optional("GET", "/api/core/system/status")

    async def system_resources(self) -> dict[str, Any] | None:
        return await self._optional("GET", "/api/diagnostics/system/system_resources")

    async def system_disk(self) -> dict[str, Any] | None:
        return await self._optional("GET", "/api/diagnostics/system/system_disk")

    async def interfaces(self) -> dict[str, Any] | None:
        return await self._optional("GET", "/api/interfaces/overview/interfacesInfo")

    async def interface_traffic(self) -> dict[str, Any] | None:
        """Cumulative byte counters per configured interface (wan, lan, opt…)."""
        return await self._optional("GET", "/api/diagnostics/traffic/interface")

    async def gateways(self) -> dict[str, Any] | None:
        return await self._optional("GET", "/api/routes/gateway/status")

    async def carp_status(self) -> dict[str, Any] | None:
        return await self._optional("GET", "/api/diagnostics/interface/getVipStatus")

    async def pf_states(self) -> dict[str, Any] | None:
        return await self._optional("GET", "/api/diagnostics/firewall/state_size")

    # ------------------------------------------------------------------ VPN
    async def wireguard_servers(self) -> dict[str, Any] | None:
        return await self._optional("GET", "/api/wireguard/server/searchServer")

    async def wireguard_clients(self) -> dict[str, Any] | None:
        return await self._optional("GET", "/api/wireguard/client/searchClient")

    async def ipsec_sessions(self) -> dict[str, Any] | None:
        return await self._optional("GET", "/api/ipsec/sessions/searchSessions")

    async def search_ipsec_tunnels(self) -> dict[str, Any]:
        return await self._request("GET", "/api/ipsec/tunnel/search")

    async def add_ipsec_tunnel(self, tunnel: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/api/ipsec/tunnel/add", json={"tunnel": tunnel})

    async def set_ipsec_tunnel(self, uuid: str, tunnel: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", f"/api/ipsec/tunnel/set/{uuid}", json={"tunnel": tunnel})

    async def delete_ipsec_tunnel(self, uuid: str) -> dict[str, Any]:
        return await self._request("POST", f"/api/ipsec/tunnel/del/{uuid}")

    async def apply_ipsec(self) -> dict[str, Any]:
        return await self._request("POST", "/api/ipsec/service/reconfigure")

    async def search_ipsec_phase1(self) -> dict[str, Any]:
        return await self._request("GET", "/api/ipsec/phase1/search")

    async def add_ipsec_phase1(self, phase1: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/api/ipsec/phase1/add", json={"phase1": phase1})

    async def set_ipsec_phase1(self, uuid: str, phase1: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", f"/api/ipsec/phase1/set/{uuid}", json={"phase1": phase1})

    async def delete_ipsec_phase1(self, uuid: str) -> dict[str, Any]:
        return await self._request("POST", f"/api/ipsec/phase1/del/{uuid}")

    async def search_ipsec_phase2(self) -> dict[str, Any]:
        return await self._request("GET", "/api/ipsec/phase2/search")

    async def add_ipsec_phase2(self, phase2: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/api/ipsec/phase2/add", json={"phase2": phase2})

    async def set_ipsec_phase2(self, uuid: str, phase2: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", f"/api/ipsec/phase2/set/{uuid}", json={"phase2": phase2})

    async def delete_ipsec_phase2(self, uuid: str) -> dict[str, Any]:
        return await self._request("POST", f"/api/ipsec/phase2/del/{uuid}")

    async def apply_ipsec_phase1(self) -> dict[str, Any]:
        return await self._request("POST", "/api/ipsec/phase1/apply")

    async def openvpn_sessions(self) -> dict[str, Any] | None:
        return await self._optional("GET", "/api/openvpn/instances/search")

    async def openvpn_clients(self) -> dict[str, Any] | None:
        return await self._optional("GET", "/api/openvpn/client/searchClient")

    async def search_dhcp_leases(self) -> dict[str, Any]:
        kea = await self._optional("GET", "/api/kea/leases/search")
        if kea is not None:
            return kea
        return await self._request("GET", "/api/dhcp/leases/search")

    async def search_dhcp_relays(self) -> dict[str, Any]:
        return await self._request("GET", "/api/dhcp/relay/search")

    async def search_dhcp_v4_leases(self) -> dict[str, Any]:
        return await self._request("GET", "/api/dhcpv4/leases/search")

    async def search_dhcp_v6_leases(self) -> dict[str, Any]:
        return await self._request("GET", "/api/dhcpv6/leases/search")

    # ------------------------------------------------------------------ DHCP (Kea)
    async def search_kea_subnets(self) -> dict[str, Any]:
        return await self._request("GET", "/api/kea/dhcpv4/searchSubnet")

    async def add_kea_subnet(self, subnet: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/api/kea/dhcpv4/addSubnet", json={"subnet4": subnet})

    async def set_kea_subnet(self, uuid: str, subnet: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", f"/api/kea/dhcpv4/setSubnet/{uuid}", json={"subnet4": subnet})

    async def delete_kea_subnet(self, uuid: str) -> dict[str, Any]:
        return await self._request("POST", f"/api/kea/dhcpv4/delSubnet/{uuid}")

    async def search_kea_reservations(self) -> dict[str, Any]:
        return await self._request("GET", "/api/kea/dhcpv4/searchReservation")

    async def add_kea_reservation(self, reservation: dict[str, Any]) -> dict[str, Any]:
        return await self._request(
            "POST", "/api/kea/dhcpv4/addReservation", json={"reservation": reservation}
        )

    async def set_kea_reservation(self, uuid: str, reservation: dict[str, Any]) -> dict[str, Any]:
        return await self._request(
            "POST", f"/api/kea/dhcpv4/setReservation/{uuid}", json={"reservation": reservation}
        )

    async def delete_kea_reservation(self, uuid: str) -> dict[str, Any]:
        return await self._request("POST", f"/api/kea/dhcpv4/delReservation/{uuid}")

    async def apply_kea(self) -> dict[str, Any]:
        return await self._request("POST", "/api/kea/service/reconfigure")

    # ------------------------------------------------------------------ DNS (Unbound)
    async def search_unbound_host_overrides(self) -> dict[str, Any]:
        return await self._request("GET", "/api/unbound/settings/searchHostOverride")

    async def add_unbound_host_override(self, host: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/api/unbound/settings/addHostOverride", json={"host": host})

    async def set_unbound_host_override(self, uuid: str, host: dict[str, Any]) -> dict[str, Any]:
        return await self._request(
            "POST", f"/api/unbound/settings/setHostOverride/{uuid}", json={"host": host}
        )

    async def delete_unbound_host_override(self, uuid: str) -> dict[str, Any]:
        return await self._request("POST", f"/api/unbound/settings/delHostOverride/{uuid}")

    async def search_unbound_host_aliases(self) -> dict[str, Any]:
        return await self._request("GET", "/api/unbound/settings/searchHostAlias")

    async def add_unbound_host_alias(self, alias: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/api/unbound/settings/addHostAlias", json={"alias": alias})

    async def set_unbound_host_alias(self, uuid: str, alias: dict[str, Any]) -> dict[str, Any]:
        return await self._request(
            "POST", f"/api/unbound/settings/setHostAlias/{uuid}", json={"alias": alias}
        )

    async def delete_unbound_host_alias(self, uuid: str) -> dict[str, Any]:
        return await self._request("POST", f"/api/unbound/settings/delHostAlias/{uuid}")

    async def apply_unbound(self) -> dict[str, Any]:
        return await self._request("POST", "/api/unbound/service/reconfigure")

    async def search_dns_records(self) -> dict[str, Any]:
        return await self._request("GET", "/api/unbound/settings/searchHostOverride")

    async def search_dns_overrides(self) -> dict[str, Any]:
        return await self._request("GET", "/api/unbound/settings/searchHostOverride")

    async def search_vlans(self) -> dict[str, Any]:
        return await self._request("GET", "/api/interfaces/vlan_settings/searchItem")

    async def search_interfaces(self) -> dict[str, Any]:
        return await self._request("GET", "/api/interfaces/assignment/searchItem")

    async def search_wireguard_servers(self) -> dict[str, Any]:
        return await self._request("GET", "/api/wireguard/server/searchServer")

    async def search_wireguard_clients(self) -> dict[str, Any]:
        return await self._request("GET", "/api/wireguard/client/searchClient")

    async def add_wireguard_server(self, server: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/api/wireguard/server/add", json={"server": server})

    async def set_wireguard_server(self, uuid: str, server: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", f"/api/wireguard/server/set/{uuid}", json={"server": server})

    async def delete_wireguard_server(self, uuid: str) -> dict[str, Any]:
        return await self._request("POST", f"/api/wireguard/server/del/{uuid}")

    async def add_wireguard_client(self, client: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/api/wireguard/client/add", json={"client": client})

    async def set_wireguard_client(self, uuid: str, client: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", f"/api/wireguard/client/set/{uuid}", json={"client": client})

    async def delete_wireguard_client(self, uuid: str) -> dict[str, Any]:
        return await self._request("POST", f"/api/wireguard/client/del/{uuid}")

    async def apply_wireguard(self) -> dict[str, Any]:
        return await self._request("POST", "/api/wireguard/service/reconfigure")

    async def search_openvpn_instances(self) -> dict[str, Any]:
        return await self._request("GET", "/api/openvpn/instances/search")

    async def search_openvpn_clients(self) -> dict[str, Any]:
        return await self._request("GET", "/api/openvpn/client/searchClient")

    async def add_openvpn_instance(self, instance: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/api/openvpn/instances/add", json={"instance": instance})

    async def set_openvpn_instance(self, uuid: str, instance: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", f"/api/openvpn/instances/set/{uuid}", json={"instance": instance})

    async def delete_openvpn_instance(self, uuid: str) -> dict[str, Any]:
        return await self._request("POST", f"/api/openvpn/instances/del/{uuid}")

    async def apply_openvpn(self) -> dict[str, Any]:
        return await self._request("POST", "/api/openvpn/service/reconfigure")

    async def add_vlan(self, vlan: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/api/interfaces/vlan_settings/addItem", json={"vlan": vlan})

    async def set_vlan(self, uuid: str, vlan: dict[str, Any]) -> dict[str, Any]:
        return await self._request(
            "POST", f"/api/interfaces/vlan_settings/setItem/{uuid}", json={"vlan": vlan}
        )

    async def delete_vlan(self, uuid: str) -> dict[str, Any]:
        return await self._request("POST", f"/api/interfaces/vlan_settings/delItem/{uuid}")

    async def apply_interfaces(self) -> dict[str, Any]:
        return await self._request("POST", "/api/interfaces/vlan_settings/reconfigure")

    # ------------------------------------------------------------------ firewall
    async def search_rules(self) -> dict[str, Any]:
        return await self._request("GET", "/api/firewall/filter/searchRule")

    async def add_rule(self, rule: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/api/firewall/filter/addRule", json={"rule": rule})

    async def set_rule(self, uuid: str, rule: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", f"/api/firewall/filter/setRule/{uuid}", json={"rule": rule})

    async def delete_rule(self, uuid: str) -> dict[str, Any]:
        return await self._request("POST", f"/api/firewall/filter/delRule/{uuid}")

    async def apply_rules(self) -> dict[str, Any]:
        return await self._request("POST", "/api/firewall/filter/apply")

    async def search_aliases(self) -> dict[str, Any]:
        return await self._request("GET", "/api/firewall/alias/get")

    async def set_alias(self, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/api/firewall/alias/set", json={"alias": {name: payload}})

    async def reconfigure_aliases(self) -> dict[str, Any]:
        return await self._request("POST", "/api/firewall/alias/reconfigure")

    async def add_to_alias(self, alias_name: str, address: str) -> dict[str, Any]:
        """Add an address (MAC or IP) to a firewall alias."""
        existing = await self.search_aliases()
        alias_uuid = None
        alias_content = None

        for key, value in existing.items():
            if isinstance(value, dict) and value.get("name") == alias_name:
                alias_uuid = key
                alias_content = value
                break

        if not alias_uuid:
            return await self.set_alias(
                alias_name,
                {
                    "name": alias_name,
                    "type": "mac",
                    "counters": "false",
                    "content": address,
                    "description": f"Client blocked by OFME inventory - {address}",
                },
            )

        current_content = alias_content.get("content", "")
        if address not in current_content:
            new_content = f"{current_content}\n{address}" if current_content else address
            return await self.set_alias(
                alias_name,
                {
                    "name": alias_name,
                    "type": "mac",
                    "counters": "false",
                    "content": new_content.strip(),
                    "description": alias_content.get("description", f"Client blocked by OFME inventory"),
                },
            )

        return {"status": "ok", "message": f"Address {address} already in alias {alias_name}"}

    async def remove_from_alias(self, alias_name: str, address: str) -> dict[str, Any]:
        """Remove an address from a firewall alias."""
        existing = await self.search_aliases()
        alias_uuid = None
        alias_content = None

        for key, value in existing.items():
            if isinstance(value, dict) and value.get("name") == alias_name:
                alias_uuid = key
                alias_content = value
                break

        if not alias_uuid:
            return {"status": "ok", "message": f"Alias {alias_name} not found"}

        current_content = alias_content.get("content", "")
        new_content = "\n".join(line for line in current_content.split("\n") if line.strip() != address)

        return await self.set_alias(
            alias_name,
            {
                "name": alias_name,
                "type": "mac",
                "counters": "false",
                "content": new_content.strip(),
                "description": alias_content.get("description", f"Client blocked by OFME inventory"),
            },
        )

    async def apply_firewall_rules(self) -> dict[str, Any]:
        """Apply firewall changes (aliases and rules)."""
        await self.reconfigure_aliases()
        return await self.apply_rules()

    async def search_nat(self, kind: str = "d_nat") -> dict[str, Any]:
        return await self._request("GET", f"/api/firewall/{kind}/searchRule")

    async def add_nat_rule(self, kind: str, rule: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", f"/api/firewall/{kind}/addRule", json={"rule": rule})

    async def set_nat_rule(self, kind: str, uuid: str, rule: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", f"/api/firewall/{kind}/setRule/{uuid}", json={"rule": rule})

    async def delete_nat_rule(self, kind: str, uuid: str) -> dict[str, Any]:
        return await self._request("POST", f"/api/firewall/{kind}/delRule/{uuid}")

    async def apply_nat(self, kind: str) -> dict[str, Any]:
        return await self._request("POST", f"/api/firewall/{kind}/apply")

    # ------------------------------------------------------------------ trust store
    async def add_ca(self, ca: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/api/trust/ca/add", json={"ca": ca})

    async def search_cas(self) -> dict[str, Any]:
        return await self._request("GET", "/api/trust/ca/search")

    async def delete_ca(self, uuid: str) -> dict[str, Any]:
        return await self._request("POST", f"/api/trust/ca/del/{uuid}")

    async def add_certificate(self, cert: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/api/trust/cert/add", json={"cert": cert})

    async def search_certificates(self) -> dict[str, Any]:
        return await self._request("GET", "/api/trust/cert/search")

    async def delete_certificate(self, uuid: str) -> dict[str, Any]:
        return await self._request("POST", f"/api/trust/cert/del/{uuid}")

    # ------------------------------------------------------------------ CARP / VIP
    async def search_vips(self) -> dict[str, Any]:
        return await self._request("GET", "/api/interfaces/vip_settings/searchItem")

    async def set_vip(self, uuid: str, vip: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", f"/api/interfaces/vip_settings/setItem/{uuid}", json={"vip": vip})

    async def apply_vips(self) -> dict[str, Any]:
        return await self._request("POST", "/api/interfaces/vip_settings/reconfigure")

    # ------------------------------------------------------------------ config
    async def download_config(self) -> bytes:
        response = await self._client.post("/api/core/backup/download/this", json={"backuparea": "config"})
        if response.status_code >= 400:
            raise UpstreamError(f"Configuration download failed with {response.status_code}")
        return response.content

    async def upload_config(self, payload: bytes) -> dict[str, Any]:
        files = {"xml": ("config.xml", payload, "application/xml")}
        try:
            response = await self._client.post(
                "/api/core/backup/restore", files=files, headers={"Content-Type": None}
            )
        except httpx.HTTPError as exc:
            raise UpstreamError(f"Configuration restore failed: {exc}") from exc
        if response.status_code >= 400:
            raise UpstreamError(f"Configuration restore failed with {response.status_code}")
        return response.json() if response.content else {}

    async def reboot(self) -> dict[str, Any]:
        return await self._request("POST", "/api/core/system/reboot")

    async def upgrade_firmware(self, package: str | None = None) -> dict[str, Any]:
        payload = {"upgrade": package} if package else {}
        return await self._request("POST", "/api/core/firmware/update", json=payload)

    # ------------------------------------------------------------------ generic
    async def api_get(self, path: str, **params: Any) -> dict[str, Any]:
        """Escape hatch for plugin endpoints (os-fleet-agent, wireguard, etc.)."""
        return await self._request("GET", path, params=params or None)

    async def api_post(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self._request("POST", path, json=payload or {})

    async def api_delete(self, path: str) -> dict[str, Any]:
        return await self._request("POST", path)

    # ------------------------------------------------------------------ composite
    async def healthcheck(self) -> HealthSnapshot:
        snapshot = HealthSnapshot(reachable=False)
        try:
            firmware = await self.firmware_status()
            resources = await self.system_resources()
            disk = await self.system_disk()
            interfaces = await self.interfaces()
            traffic = await self.interface_traffic()
            gateways = await self.gateways()
            carp = await self.carp_status()
            wg_servers = await self.wireguard_servers()
            wg_clients = await self.wireguard_clients()
            ipsec = await self.ipsec_sessions()
        except UpstreamError as exc:
            snapshot.error = str(exc)
            return snapshot

        snapshot.reachable = True
        snapshot.traffic = normalise_counters(traffic)
        if firmware:
            product = firmware.get("product", {}) if isinstance(firmware, dict) else {}
            snapshot.firmware_version = (
                firmware.get("product_version") or product.get("product_version") or firmware.get("version")
            )
            snapshot.hostname = firmware.get("hostname") or product.get("hostname")

        if resources:
            snapshot.memory_pct = (
                _number(resources.get("memory", {}).get("used_pct"))
                if isinstance(resources.get("memory"), dict)
                else _number(resources.get("memory_used_pct"))
            )
            cpu = resources.get("cpu") or resources.get("cpu_usage")
            snapshot.cpu_pct = _number(cpu)
            snapshot.load_1m = _number(
                resources.get("load", {}).get("1min")
                if isinstance(resources.get("load"), dict)
                else resources.get("load_1m")
            )
            if snapshot.cpu_pct is None and snapshot.load_1m is not None:
                snapshot.cpu_pct = min(snapshot.load_1m / 4.0 * 100.0, 100.0)

        if disk:
            used = disk.get("used_pct") or disk.get("used_percent")
            if used is None and isinstance(disk.get("root"), dict):
                used = disk["root"].get("used_pct")
            snapshot.disk_pct = _number(used)

        if interfaces:
            rows = interfaces.get("rows") or interfaces.get("interfaces") or []
            for row in rows if isinstance(rows, list) else []:
                if not isinstance(row, dict):
                    continue
                snapshot.interfaces.append(
                    {
                        "name": row.get("identifier") or row.get("device") or row.get("name"),
                        "description": row.get("description"),
                        "status": row.get("status"),
                        "ipv4": row.get("ipv4") or row.get("addr4"),
                        "mac": row.get("macaddr") or row.get("mac"),
                    }
                )

        if gateways:
            rows = gateways.get("rows") or gateways.get("items") or []
            total = 0
            up = 0
            for row in rows if isinstance(rows, list) else []:
                total += 1
                if str(row.get("status", "")).lower() in {"online", "up", "none"}:
                    up += 1
            snapshot.gateways_total = total
            snapshot.gateways_up = up

        if carp:
            status = carp.get("status") or carp.get("carp") or carp.get("mode")
            snapshot.carp_status = str(status).lower() if status else "disabled"

        vpn_total = 0
        vpn_up = 0
        for payload, key in ((wg_servers, "rows"), (wg_clients, "rows"), (ipsec, "rows")):
            if not isinstance(payload, dict):
                continue
            rows = payload.get(key) or payload.get("sessions") or []
            for row in rows if isinstance(rows, list) else []:
                vpn_total += 1
                state = str(row.get("status", row.get("state", ""))).lower()
                if state in {"up", "connected", "installed", "1", "true"}:
                    vpn_up += 1
        snapshot.vpn_total = vpn_total
        snapshot.vpn_up = vpn_up
        snapshot.raw = {
            "firmware": firmware or {},
            "resources": resources or {},
            "gateways": gateways or {},
            "carp": carp or {},
        }
        return snapshot


def client_for(
    base_url: str,
    api_key: str,
    api_secret: str,
    *,
    verify_tls: bool | None = None,
    timeout: float | None = None,
) -> OpnsenseClient:
    return OpnsenseClient(
        OpnsenseCredentials(
            base_url=base_url,
            api_key=api_key,
            api_secret=api_secret,
            verify_tls=settings.OPNsense_VERIFY_TLS if verify_tls is None else verify_tls,
            timeout=timeout or settings.OPNsense_TIMEOUT_SECONDS,
        )
    )


def utcnow() -> datetime:
    return datetime.now(UTC)
