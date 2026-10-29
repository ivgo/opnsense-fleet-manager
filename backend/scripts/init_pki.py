"""Generate the device CA outside the cluster and hand it to Kubernetes.

The CA private key must exist before the first API pod starts so that every
replica serves the same trust anchor. This script creates the key/certificate
pair locally (or in your HSM-backed directory), then either writes PEM files or
prints a Kubernetes Secret manifest.

Usage::

    python scripts/init_pki.py --output ./pki
    python scripts/init_pki.py --kubectl-secret --namespace ofme > pki-secret.yaml
    kubectl apply -f pki-secret.yaml && rm pki-secret.yaml
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("ENVIRONMENT", "development")

from app.pki.ca import CertificateAuthority  # noqa: E402


def _secret_manifest(cert_pem: str, key_pem: str, name: str, namespace: str) -> str:
    def indent(block: str, spaces: int = 4) -> str:
        prefix = " " * spaces
        return "\n".join(prefix + line if line else "" for line in block.rstrip().splitlines())

    return (
        "apiVersion: v1\n"
        "kind: Secret\n"
        "metadata:\n"
        f"  name: {name}\n"
        f"  namespace: {namespace}\n"
        "  labels:\n"
        "    app.kubernetes.io/name: ofme\n"
        "    app.kubernetes.io/component: pki\n"
        "type: Opaque\n"
        "stringData:\n"
        "  ca.crt: |\n"
        f"{indent(cert_pem)}\n"
        "  ca.key: |\n"
        f"{indent(key_pem)}\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="directory that receives ca.crt and ca.key")
    parser.add_argument(
        "--kubectl-secret",
        action="store_true",
        help="print a Secret manifest instead of writing files",
    )
    parser.add_argument("--secret-name", default="ofme-pki")
    parser.add_argument("--namespace", default="ofme")
    parser.add_argument("--force", action="store_true", help="overwrite an existing CA")
    args = parser.parse_args()

    if not args.output and not args.kubectl_secret:
        parser.error("choose --output and/or --kubectl-secret")

    if args.kubectl_secret:
        authority = CertificateAuthority()
        authority.ensure_ca()
        print(
            _secret_manifest(
                authority.ca_pem,
                Path(authority.key_path).read_text(encoding="utf-8"),
                args.secret_name,
                args.namespace,
            )
        )
        return 0

    target = args.output
    assert target is not None
    cert_path = target / "ca.crt"
    key_path = target / "ca.key"
    if (cert_path.exists() or key_path.exists()) and not args.force:
        print(f"refusing to overwrite existing CA in {target} (pass --force)")
        return 1

    target.mkdir(parents=True, exist_ok=True)
    authority = CertificateAuthority(cert_path=str(cert_path), key_path=str(key_path))
    authority.ensure_ca()
    os.chmod(key_path, 0o600)

    print(f"certificate: {cert_path}")
    print(f"private key: {key_path} (mode 0600)")
    print(f"sha256 fingerprint: {authority.fingerprint}")
    print(f"subject: {authority.cert.subject.rfc4514_string()}")
    print(f"valid until: {authority.cert.not_valid_after_utc.isoformat()}")
    print()
    print("Create the Kubernetes secret with:")
    print(
        f"  kubectl -n {args.namespace} create secret generic {args.secret_name} "
        f"--from-file=ca.crt={cert_path} --from-file=ca.key={key_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
