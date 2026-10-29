#!/usr/bin/env bash
set -euo pipefail

# Wait for PostgreSQL before running migrations (compose healthchecks are advisory only
# for the first boot of a fresh volume).
if [[ "${WAIT_FOR_DB:-true}" == "true" ]]; then
  python - <<'PY'
import asyncio
import sys
import time

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings

async def main() -> int:
    engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    deadline = time.time() + 120
    while time.time() < deadline:
        try:
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
            await engine.dispose()
            return 0
        except Exception as exc:  # noqa: BLE001 - retry until the deadline
            print(f"[entrypoint] waiting for database: {exc}", flush=True)
            await asyncio.sleep(2)
    await engine.dispose()
    return 1

sys.exit(asyncio.run(main()))
PY
fi

if [[ "${RUN_MIGRATIONS:-true}" == "true" ]]; then
  echo "[entrypoint] applying migrations"
  alembic upgrade head
fi

exec "$@"
