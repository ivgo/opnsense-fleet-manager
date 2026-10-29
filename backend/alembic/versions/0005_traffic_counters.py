"""Store cumulative interface counters so traffic rates can be derived.

The platform writes one ``traffic`` metric per interface and direction on every
heartbeat. Deriving a rate needs the previous counters and the time they were
sampled, so both are kept on the per-device telemetry snapshot.

Revision ID: 0005_traffic_counters
Revises: 0004_ha_cluster_name_index
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0005_traffic_counters"
down_revision: str | None = "0004_ha_cluster_name_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE device_telemetry_snapshots ADD COLUMN IF NOT EXISTS traffic JSONB")
    op.execute(
        "ALTER TABLE device_telemetry_snapshots ADD COLUMN IF NOT EXISTS traffic_at TIMESTAMPTZ"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE device_telemetry_snapshots DROP COLUMN IF EXISTS traffic_at")
    op.execute("ALTER TABLE device_telemetry_snapshots DROP COLUMN IF EXISTS traffic")
