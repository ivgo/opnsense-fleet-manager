"""Write the OpenAPI document straight from the FastAPI application.

No server, database or Redis connection is needed: importing ``app.main`` only
builds the router tree, it does not run the lifespan.

Usage::

    python scripts/export_openapi.py                  # ../api/openapi.yaml
    python scripts/export_openapi.py -o ../api/openapi.json
    python scripts/export_openapi.py --check          # CI drift check
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = BACKEND_DIR.parent / "api" / "openapi.yaml"

# Import-time settings must be importable without a real deployment.
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("SECRET_KEY", "openapi-export-only-secret-key-0123456789abcdef")
os.environ.setdefault("OTEL_ENABLED", "false")

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.main import app  # noqa: E402


def _render(spec: dict, suffix: str) -> str:
    if suffix in {".yaml", ".yml"}:
        import yaml

        return yaml.safe_dump(spec, sort_keys=False, allow_unicode=True, width=110)
    return json.dumps(spec, indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero when the file on disk differs from the application",
    )
    args = parser.parse_args()

    spec = app.openapi()
    spec["openapi"] = "3.1.0"
    rendered = _render(spec, args.output.suffix)

    if args.check:
        if not args.output.exists():
            print(f"{args.output} does not exist")
            return 1
        if args.output.read_text(encoding="utf-8") != rendered:
            print(f"{args.output} is out of date; run scripts/export_openapi.py")
            return 1
        print(f"{args.output} is up to date ({len(spec['paths'])} paths)")
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8", newline="\n")
    schemas = spec.get("components", {}).get("schemas", {})
    print(
        f"wrote {args.output} ({len(spec['paths'])} paths, {len(schemas)} schemas, "
        f"OpenAPI {spec['openapi']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
