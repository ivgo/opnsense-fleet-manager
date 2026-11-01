"""IPsec Phase 1 and Phase 2 configuration tables.

The initial revision materialises the schema from ORM metadata, so a fresh
database already has these tables. Every statement is therefore idempotent: the
migration upgrades an existing installation without failing on a new one.

Revision ID: 0007_ipsec
Revises: 0006_maintenance_reports
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0007_ipsec"
down_revision: str | None = "0006_maintenance_reports"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ipsec_phase1 (
            id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            device_id UUID REFERENCES devices(id) ON DELETE CASCADE,
            name VARCHAR(255) NOT NULL,
            description TEXT,
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            iketype VARCHAR(16) NOT NULL DEFAULT 'ikev2',
            interface VARCHAR(32) NOT NULL DEFAULT 'wan',
            remote_gateway VARCHAR(255) NOT NULL,
            local_gateway VARCHAR(255),
            authentication_method VARCHAR(32) NOT NULL DEFAULT 'pre_shared_key',
            pre_shared_key TEXT,
            my_identifier VARCHAR(255),
            peer_identifier VARCHAR(255),
            encryption JSONB NOT NULL DEFAULT '[]'::jsonb,
            hash JSONB NOT NULL DEFAULT '[]'::jsonb,
            dh_group VARCHAR(16) NOT NULL DEFAULT '14',
            lifetime INTEGER NOT NULL DEFAULT 28800,
            dpd_delay INTEGER NOT NULL DEFAULT 10,
            dpd_maxfail INTEGER NOT NULL DEFAULT 5,
            nat_traversal VARCHAR(8) NOT NULL DEFAULT 'force',
            version INTEGER NOT NULL DEFAULT 1,
            created_by UUID REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            deleted_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_ipsec_phase1_device_name "
        "ON ipsec_phase1 (device_id, name) WHERE deleted_at IS NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_ipsec_phase1_tenant_device "
        "ON ipsec_phase1 (tenant_id, device_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_ipsec_phase1_deleted_at "
        "ON ipsec_phase1 (deleted_at)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ipsec_phase2 (
            id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            device_id UUID REFERENCES devices(id) ON DELETE CASCADE,
            phase1_id UUID NOT NULL REFERENCES ipsec_phase1(id) ON DELETE CASCADE,
            name VARCHAR(255) NOT NULL,
            description TEXT,
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            mode VARCHAR(16) NOT NULL DEFAULT 'tunnel',
            protocol VARCHAR(8) NOT NULL DEFAULT 'esp',
            local_net VARCHAR(255) NOT NULL,
            remote_net VARCHAR(255) NOT NULL,
            encryption JSONB NOT NULL DEFAULT '[]'::jsonb,
            hash JSONB NOT NULL DEFAULT '[]'::jsonb,
            pfs_group VARCHAR(16) NOT NULL DEFAULT '14',
            lifetime INTEGER NOT NULL DEFAULT 3600,
            version INTEGER NOT NULL DEFAULT 1,
            created_by UUID REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            deleted_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_ipsec_phase2_device_phase1_name "
        "ON ipsec_phase2 (device_id, phase1_id, name) WHERE deleted_at IS NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_ipsec_phase2_tenant_device "
        "ON ipsec_phase2 (tenant_id, device_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_ipsec_phase2_deleted_at "
        "ON ipsec_phase2 (deleted_at)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ipsec_phase2")
    op.execute("DROP TABLE IF EXISTS ipsec_phase1")