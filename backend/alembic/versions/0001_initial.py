"""Initial schema.

The ORM metadata is the single source of truth for the initial baseline: every table,
index, constraint and JSONB column is declared in ``app.models``. Creating the schema
from that metadata guarantees that a fresh database is byte-for-byte identical to the
mapping the application expects, without a 5 000-line hand-maintained DDL file.

Subsequent revisions are generated with ``alembic revision --autogenerate`` and must
contain explicit ``op.*`` calls.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.db.base import Base
import app.models  # noqa: F401 - ensure all mappers are imported

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind, checkfirst=True)
