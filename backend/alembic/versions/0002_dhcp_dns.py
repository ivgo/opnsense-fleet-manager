"""DHCP scopes/reservations and authoritative DNS records.

``0001_initial`` builds the schema from the ORM metadata, so a fresh database
already contains these tables. This revision therefore uses ``checkfirst=True``
and only creates what is missing on databases that were initialised before the
DHCP/DNS aggregates existed.

Revision ID: 0002_dhcp_dns
Revises: 0001_initial
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.models.config import DhcpReservation, DhcpScope, DnsRecord

revision: str = "0002_dhcp_dns"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    # Parents before children: dhcp_scopes -> dhcp_reservations.
    for table in (DhcpScope.__table__, DhcpReservation.__table__, DnsRecord.__table__):
        table.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table in (DnsRecord.__table__, DhcpReservation.__table__, DhcpScope.__table__):
        table.drop(bind=bind, checkfirst=True)
