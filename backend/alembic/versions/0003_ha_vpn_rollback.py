"""HA clusters, VPN credentials, deployment snapshots and notification delivery.

Adds the schema needed to close the remaining core features:

* ``policy_deployments.snapshot`` - materialised desired state for real rollback;
* ``notifications.delivery`` / ``delivered_at`` - per-channel delivery tracking;
* ``vpn_tunnels.peer_public_key`` and tunnel addresses - distinct WireGuard keys;
* ``wireguard_keys``, ``openvpn_cas``, ``openvpn_certificates`` - VPN identity;
* ``ha_clusters``, ``ha_nodes`` - CARP configuration and status.

``0001_initial`` builds the schema from ORM metadata, so a fresh database already
has all of it. Every statement is therefore guarded and only changes databases
created before this revision.

Revision ID: 0003_ha_vpn_rollback
Revises: 0002_dhcp_dns
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.models.ha import HaCluster, HaNode
from app.models.sdwan import OpenVpnCa, OpenVpnCertificate, WireGuardKey

revision: str = "0003_ha_vpn_rollback"
down_revision: str | None = "0002_dhcp_dns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS: tuple[tuple[str, str], ...] = (
    ("policy_deployments", "snapshot JSONB NOT NULL DEFAULT '{}'::jsonb"),
    ("notifications", "delivery JSONB NOT NULL DEFAULT '{}'::jsonb"),
    ("notifications", "delivered_at TIMESTAMPTZ"),
    ("vpn_tunnels", "peer_public_key VARCHAR(128)"),
    ("vpn_tunnels", "tunnel_address_local VARCHAR(64)"),
    ("vpn_tunnels", "tunnel_address_remote VARCHAR(64)"),
)


def upgrade() -> None:
    bind = op.get_bind()
    for table, column in _COLUMNS:
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column}")
    for table in (
        WireGuardKey.__table__,
        OpenVpnCa.__table__,
        OpenVpnCertificate.__table__,
        HaCluster.__table__,
        HaNode.__table__,
    ):
        table.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table in (
        HaNode.__table__,
        HaCluster.__table__,
        OpenVpnCertificate.__table__,
        OpenVpnCa.__table__,
        WireGuardKey.__table__,
    ):
        table.drop(bind=bind, checkfirst=True)
    for table, column in reversed(_COLUMNS):
        name = column.split()[0]
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {name}")
