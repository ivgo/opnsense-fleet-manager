"""Maintenance windows (quiet hours) and generated PDF reports.

The initial revision materialises the schema from ORM metadata, so a fresh
database already has these tables. Every statement is therefore idempotent: the
migration upgrades an existing installation without failing on a new one.

Revision ID: 0006_maintenance_reports
Revises: 0005_traffic_counters
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0006_maintenance_reports"
down_revision: str | None = "0005_traffic_counters"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS maintenance_windows (
            id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            name VARCHAR(255) NOT NULL,
            description TEXT,
            starts_at TIMESTAMPTZ NOT NULL,
            ends_at TIMESTAMPTZ NOT NULL,
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            target_type VARCHAR(16) NOT NULL DEFAULT 'fleet',
            target_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
            silence_alerts BOOLEAN NOT NULL DEFAULT TRUE,
            silence_notifications BOOLEAN NOT NULL DEFAULT TRUE,
            created_by UUID REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_maintenance_windows_tenant_id "
        "ON maintenance_windows (tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_maintenance_windows_tenant_window "
        "ON maintenance_windows (tenant_id, starts_at, ends_at)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS reports (
            id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            name VARCHAR(255) NOT NULL,
            kind VARCHAR(16) NOT NULL DEFAULT 'fleet',
            status VARCHAR(16) NOT NULL DEFAULT 'pending',
            period_start TIMESTAMPTZ NOT NULL,
            period_end TIMESTAMPTZ NOT NULL,
            params JSONB NOT NULL DEFAULT '{}'::jsonb,
            storage_key VARCHAR(512),
            size_bytes INTEGER,
            checksum_sha256 VARCHAR(64),
            error TEXT,
            generated_at TIMESTAMPTZ,
            created_by UUID REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_reports_tenant_id ON reports (tenant_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_reports_tenant_created "
        "ON reports (tenant_id, created_at)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS reports")
    op.execute("DROP TABLE IF EXISTS maintenance_windows")
