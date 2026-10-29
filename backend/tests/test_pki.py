"""PKI tests: CA bootstrap, CSR issuance, chain validation, tenant binding, CRL."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.pki.ca import CertificateAuthority


@pytest.fixture()
def authority(tmp_path: Path) -> CertificateAuthority:
    ca = CertificateAuthority(
        cert_path=str(tmp_path / "ca.crt"),
        key_path=str(tmp_path / "ca.key"),
    )
    ca.ensure_ca()
    return ca


def _csr(common_name: str) -> tuple[rsa.RSAPrivateKey, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, common_name)]))
        .sign(key, hashes.SHA256())
    )
    return key, csr.public_bytes(serialization.Encoding.PEM).decode("ascii")


def test_ca_is_created_and_reloaded(tmp_path: Path) -> None:
    cert_path = tmp_path / "ca.crt"
    key_path = tmp_path / "ca.key"
    first = CertificateAuthority(cert_path=str(cert_path), key_path=str(key_path))
    first.ensure_ca()
    fingerprint = first.fingerprint

    second = CertificateAuthority(cert_path=str(cert_path), key_path=str(key_path))
    second.ensure_ca()

    assert cert_path.exists()
    assert key_path.exists()
    assert second.fingerprint == fingerprint
    assert second.ca_pem.startswith("-----BEGIN CERTIFICATE-----")


def test_ca_material_is_root_only(tmp_path: Path) -> None:
    if os.name == "nt":
        pytest.skip("POSIX file modes are not enforced on Windows")
    key_path = tmp_path / "ca.key"
    CertificateAuthority(cert_path=str(tmp_path / "ca.crt"), key_path=str(key_path)).ensure_ca()
    assert key_path.stat().st_mode & 0o077 == 0


def test_issue_from_csr_does_not_return_private_key(authority: CertificateAuthority) -> None:
    tenant_id = uuid.uuid4()
    key, csr_pem = _csr("device-fw-01")

    issued = authority.issue(common_name="device-fw-01", tenant_id=tenant_id, csr_pem=csr_pem)

    assert issued.private_key_pem is None
    assert issued.subject_cn == "device-fw-01"
    assert len(issued.serial_number) > 0
    certificate = authority.parse(issued.certificate_pem)
    assert certificate.public_key().public_numbers() == key.public_key().public_numbers()
    assert authority.verify(issued.certificate_pem) is True
    assert authority.tenant_of(issued.certificate_pem) == str(tenant_id)
    assert issued.fingerprint_sha256 == certificate.fingerprint(hashes.SHA256()).hex()


def test_issue_without_csr_generates_keypair(authority: CertificateAuthority) -> None:
    issued = authority.issue(common_name="device-fw-02", tenant_id=uuid.uuid4())
    assert issued.private_key_pem is not None
    assert "BEGIN PRIVATE KEY" in issued.private_key_pem
    assert authority.verify(issued.certificate_pem) is True


def test_certificate_is_client_auth_only(authority: CertificateAuthority) -> None:
    issued = authority.issue(common_name="device-fw-03", tenant_id=uuid.uuid4())
    certificate = authority.parse(issued.certificate_pem)
    usage = certificate.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    assert list(usage) == [x509.oid.ExtendedKeyUsageOID.CLIENT_AUTH]
    assert certificate.extensions.get_extension_for_class(x509.BasicConstraints).value.ca is False


def test_san_entries_are_embedded(authority: CertificateAuthority) -> None:
    issued = authority.issue(
        common_name="device-fw-04",
        tenant_id=uuid.uuid4(),
        san_dns=["fw-04.example.test"],
        san_ips=["192.0.2.10"],
    )
    certificate = authority.parse(issued.certificate_pem)
    san = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert "fw-04.example.test" in san.get_values_for_type(x509.DNSName)
    assert "192.0.2.10" in [str(value) for value in san.get_values_for_type(x509.IPAddress)]


def test_verify_rejects_unrelated_certificate(authority: CertificateAuthority, tmp_path: Path) -> None:
    other = CertificateAuthority(
        cert_path=str(tmp_path / "other-ca.crt"), key_path=str(tmp_path / "other-ca.key")
    )
    other.ensure_ca()
    foreign = other.issue(common_name="rogue", tenant_id=uuid.uuid4())
    assert authority.verify(foreign.certificate_pem) is False


def test_verify_rejects_malformed_pem(authority: CertificateAuthority) -> None:
    assert authority.verify("not a certificate") is False


def test_crl_contains_revoked_serial(authority: CertificateAuthority) -> None:
    issued = authority.issue(common_name="device-fw-05", tenant_id=uuid.uuid4())
    crl_pem = authority.build_crl([(issued.serial_number, datetime.now(UTC), "keyCompromise")])
    assert crl_pem.startswith("-----BEGIN X509 CRL-----")
    crl = x509.load_pem_x509_crl(crl_pem.encode("ascii"))
    assert len(list(crl)) == 1
    assert list(crl)[0].serial_number == int(issued.serial_number, 16)
