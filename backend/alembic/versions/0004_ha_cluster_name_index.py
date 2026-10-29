"""Allow reusing the name of a soft-deleted CARP cluster.

``ha_clusters`` is soft-deletable, but revision ``0003`` created a plain unique
constraint on ``(tenant_id, name)``. A soft-deleted row therefore kept blocking
the name forever. Replace the constraint with the project-wide partial unique
index pattern (``WHERE deleted_at IS NULL``), matching ``dhcp_scopes`` and other
soft-deletable tables.

Revision ID: 0004_ha_cluster_name_index
Revises: 0003_ha_vpn_rollback
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0004_ha_cluster_name_index"
down_revision: str | None = "0003_ha_vpn_rollback"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE ha_clusters DROP CONSTRAINT IF EXISTS uq_ha_clusters_tenant_name")
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_ha_clusters_tenant_name
        ON ha_clusters (tenant_id, name)
        WHERE deleted_at IS NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_ha_clusters_tenant_name")
    op.execute(
        """
        ALTER TABLE ha_clusters
        ADD CONSTRAINT uq_ha_clusters_tenant_name UNIQUE (tenant_id, name)
        """
    )
