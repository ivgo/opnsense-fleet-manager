"""Inventory service: ingest client data and manage firewall blocking."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.inventory import ClientDevice, ClientSource, ClientStatus
from app.repositories import UnitOfWork

log = get_logger("ofme.inventory")


class InventoryIngestService:
    """Ingest client device data from ARP/DHCP/LLDP telemetry."""

    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.uow = UnitOfWork(session, tenant_id)

    async def ingest(
        self,
        device_id: uuid.UUID,
        arp_data: list[dict] | None = None,
        dhcp_data: list[dict] | None = None,
        lldp_data: list[dict] | None = None,
    ) -> int:
        """Ingest client device data from multiple sources.

        Returns count of active clients.
        """
        clients: list[dict] = []

        # Parse ARP table
        if arp_data:
            for entry in arp_data:
                mac = entry.get("mac") or entry.get("hardware")
                ip = entry.get("ip") or entry.get("address")
                if mac and ip:
                    clients.append(
                        {
                            "mac_address": mac.upper().replace("-", ":"),
                            "ip_address": ip,
                            "source": ClientSource.ARP,
                            "hostname": entry.get("hostname"),
                        }
                    )

        # Parse DHCP leases
        if dhcp_data:
            for lease in dhcp_data:
                mac = lease.get("mac") or lease.get("hardware_ethernet")
                ip = lease.get("ip") or lease.get("lease_address")
                if mac and ip:
                    clients.append(
                        {
                            "mac_address": mac.upper().replace("-", ":"),
                            "ip_address": ip,
                            "source": ClientSource.DHCP,
                            "hostname": lease.get("hostname") or lease.get("client_name"),
                        }
                    )

        # Parse LLDP neighbors
        if lldp_data:
            for neighbor in lldp_data:
                mac = neighbor.get("mac") or neighbor.get("chassis_mac")
                if mac:
                    clients.append(
                        {
                            "mac_address": mac.upper().replace("-", ":"),
                            "ip_address": neighbor.get("management_ip"),
                            "source": ClientSource.LLDP,
                            "hostname": neighbor.get("chassis_name") or neighbor.get("port_description"),
                            "vendor": neighbor.get("vendor"),
                        }
                    )

        if not clients:
            return 0

        # Deduplicate by MAC (keep most recent source priority: LLDP > DHCP > ARP)
        seen: dict[str, dict] = {}
        for client in clients:
            mac = client["mac_address"]
            if mac not in seen or self._source_priority(client["source"]) > self._source_priority(seen[mac]["source"]):
                seen[mac] = client

        # Upsert each unique client
        now = datetime.now(UTC)
        count = 0
        for mac, data in seen.items():
            stmt = select(ClientDevice).where(
                ClientDevice.tenant_id == self.tenant_id,
                ClientDevice.mac_address == mac,
            )
            existing = (await self.session.execute(stmt)).scalars().first()

            if existing:
                existing.last_seen = now
                existing.ip_address = data["ip_address"]
                existing.hostname = data.get("hostname")
                existing.device_id = device_id
                if existing.status == ClientStatus.ACTIVE:
                    count += 1
            else:
                vendor = data.get("vendor") or self._oui_lookup(mac)
                new_client = ClientDevice(
                    tenant_id=self.tenant_id,
                    device_id=device_id,
                    mac_address=mac,
                    ip_address=data["ip_address"],
                    hostname=data.get("hostname"),
                    vendor=vendor,
                    source=data["source"],
                    status=ClientStatus.ACTIVE,
                    first_seen=now,
                    last_seen=now,
                )
                self.session.add(new_client)
                count += 1

        return count

    @staticmethod
    def _source_priority(source: ClientSource) -> int:
        """Higher priority sources overwrite lower ones."""
        priorities = {ClientSource.ARP: 1, ClientSource.DHCP: 2, ClientSource.LLDP: 3}
        return priorities.get(source, 0)

    @staticmethod
    def _oui_lookup(mac: str) -> str | None:
        """Quick OUI lookup from MAC prefix."""
        oui_map = {
            "00:00:00": "Xerox",
            "00:00:5E": "IANA",
            "00:0C:29": "VMware",
            "00:15:5D": "Microsoft Hyper-V",
            "00:1A:2B": "QEMU",
            "00:50:56": "VMware",
            "08:00:27": "VirtualBox",
            "52:54:00": "QEMU/KVM",
        }
        prefix = mac.upper().replace("-", ":")[:8]
        return oui_map.get(prefix)


class InventoryService:
    """Manage client inventory and firewall blocking."""

    BLOCKED_ALIAS_NAME = "BLOCKED_CLIENTS"

    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.uow = UnitOfWork(session, tenant_id)

    async def block_client(self, mac: str, reason: str | None = None) -> bool:
        """Block a client by adding to firewall alias."""
        mac_normalized = mac.upper().replace("-", ":")

        stmt = select(ClientDevice).where(
            ClientDevice.tenant_id == self.tenant_id,
            ClientDevice.mac_address == mac_normalized,
        )
        client = (await self.session.execute(stmt)).scalars().first()

        if not client:
            log.warning(f"Attempted to block unknown client {mac_normalized}")
            return False

        client.status = ClientStatus.BLOCKED
        client.paused_until = None

        # Add to firewall alias via OPNsense API
        device = await self.uow.devices.get(client.device_id)
        if device and device.api_url:
            try:
                from app.integrations.opnsense.client import OpnsenseClient

                client_instance = OpnsenseClient(
                    device.api_url,
                    device.api_key,
                    device.api_secret,
                    verify_tls=False,
                )
                await client_instance.add_to_alias(self.BLOCKED_ALIAS_NAME, client.mac_address)
                await client_instance.apply_firewall_rules()
                log.info(f"Blocked client {mac_normalized} on device {device.name}")
            except Exception as e:
                log.error(f"Failed to block client {mac_normalized}: {e}")
                return False

        return True

    async def pause_client(self, mac: str, minutes: int, reason: str | None = None) -> bool:
        """Pause a client for N minutes (temporary block)."""
        mac_normalized = mac.upper().replace("-", ":")
        paused_until = datetime.now(UTC) + timedelta(minutes=minutes)

        stmt = select(ClientDevice).where(
            ClientDevice.tenant_id == self.tenant_id,
            ClientDevice.mac_address == mac_normalized,
        )
        client = (await self.session.execute(stmt)).scalars().first()

        if not client:
            log.warning(f"Attempted to pause unknown client {mac_normalized}")
            return False

        client.status = ClientStatus.PAUSED
        client.paused_until = paused_until

        # Add to firewall alias
        device = await self.uow.devices.get(client.device_id)
        if device and device.api_url:
            try:
                from app.integrations.opnsense.client import OpnsenseClient

                client_instance = OpnsenseClient(
                    device.api_url,
                    device.api_key,
                    device.api_secret,
                    verify_tls=False,
                )
                await client_instance.add_to_alias(self.BLOCKED_ALIAS_NAME, client.mac_address)
                await client_instance.apply_firewall_rules()
                log.info(f"Paused client {mac_normalized} for {minutes} minutes")
            except Exception as e:
                log.error(f"Failed to pause client {mac_normalized}: {e}")
                return False

        return True

    async def unblock_client(self, mac: str) -> bool:
        """Unblock a client by removing from firewall alias."""
        mac_normalized = mac.upper().replace("-", ":")

        stmt = select(ClientDevice).where(
            ClientDevice.tenant_id == self.tenant_id,
            ClientDevice.mac_address == mac_normalized,
        )
        client = (await self.session.execute(stmt)).scalars().first()

        if not client:
            log.warning(f"Attempted to unblock unknown client {mac_normalized}")
            return False

        client.status = ClientStatus.ACTIVE
        client.paused_until = None

        # Remove from firewall alias
        device = await self.uow.devices.get(client.device_id)
        if device and device.api_url:
            try:
                from app.integrations.opnsense.client import OpnsenseClient

                client_instance = OpnsenseClient(
                    device.api_url,
                    device.api_key,
                    device.api_secret,
                    verify_tls=False,
                )
                await client_instance.remove_from_alias(self.BLOCKED_ALIAS_NAME, client.mac_address)
                await client_instance.apply_firewall_rules()
                log.info(f"Unblocked client {mac_normalized} on device {device.name}")
            except Exception as e:
                log.error(f"Failed to unblock client {mac_normalized}: {e}")
                return False

        return True

    async def get_active_count(self) -> int:
        """Get count of active clients."""
        stmt = select(ClientDevice).where(
            ClientDevice.tenant_id == self.tenant_id,
            ClientDevice.status == ClientStatus.ACTIVE,
        )
        return int((await self.session.execute(stmt)).scalars().count())