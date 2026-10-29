"""Regenerate the Python gRPC stubs from ``proto/fleet.proto``.

The generated modules are committed so that production images do not need
``grpcio-tools`` at build time. The script rewrites the absolute import in
``fleet_pb2_grpc.py`` into a package-relative import.

Usage::

    python scripts/generate_grpc.py
    python scripts/generate_grpc.py --check   # fail when stubs are stale
"""

from __future__ import annotations

import argparse
import filecmp
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROTO_DIR = BACKEND_DIR.parent / "proto"
PROTO_FILE = PROTO_DIR / "fleet.proto"
OUTPUT_DIR = BACKEND_DIR / "app" / "grpc" / "generated"

GENERATED = ("fleet_pb2.py", "fleet_pb2.pyi", "fleet_pb2_grpc.py")

INIT_PY = '''"""Generated protobuf modules. Do not edit by hand.

Regenerate with ``python scripts/generate_grpc.py``.
"""

from __future__ import annotations

from . import fleet_pb2, fleet_pb2_grpc

__all__ = ["fleet_pb2", "fleet_pb2_grpc"]
'''


def _generate(target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "grpc_tools.protoc",
        f"--proto_path={PROTO_DIR}",
        f"--python_out={target}",
        f"--pyi_out={target}",
        f"--grpc_python_out={target}",
        str(PROTO_FILE),
    ]
    print("running:", " ".join(command))
    # The argv is fully constructed above from this file's own locations and the
    # running interpreter; no user input reaches the command line.
    subprocess.run(command, check=True)  # noqa: S603

    grpc_module = target / "fleet_pb2_grpc.py"
    source = grpc_module.read_text(encoding="utf-8")
    rewritten = source.replace(
        "import fleet_pb2 as fleet__pb2",
        "from . import fleet_pb2 as fleet__pb2",
    )
    if rewritten == source:
        raise SystemExit("fleet_pb2_grpc.py did not contain the expected import")
    grpc_module.write_text(rewritten, encoding="utf-8", newline="\n")
    (target / "__init__.py").write_text(INIT_PY, encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify that the committed stubs match the .proto without writing",
    )
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as temporary:
        staging = Path(temporary)
        _generate(staging)
        if args.check:
            stale = [
                name
                for name in GENERATED
                if not (OUTPUT_DIR / name).exists()
                or not filecmp.cmp(staging / name, OUTPUT_DIR / name, shallow=False)
            ]
            if stale:
                print("stale generated files:", ", ".join(stale))
                return 1
            print("gRPC stubs are up to date")
            return 0

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        for name in (*GENERATED, "__init__.py"):
            shutil.copy2(staging / name, OUTPUT_DIR / name)
        print(f"wrote {len(GENERATED) + 1} files to {OUTPUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
