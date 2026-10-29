# HashiCorp Vault Integration

**Date:** 2026-10-29  
**Status:** ✅ COMPLETED (I-H1, B-H3)

This document describes the HashiCorp Vault integration for secure secrets management in OFME.

---

## Overview

OFME now supports reading sensitive configuration from HashiCorp Vault KV v2 secrets engine. When enabled, the application fetches secrets from Vault at startup instead of reading them from environment variables or `.env` files.

### Supported Secrets

| Secret | Config Path | Environment Variable |
|--------|-------------|---------------------|
| `SECRET_KEY` | `VAULT_SECRET_KEY_PATH` | `VAULT_SECRET_KEY_PATH` |
| `REFRESH_TOKEN_PEPPER` | `VAULT_REFRESH_PEPPER_PATH` | `VAULT_REFRESH_PEPPER_PATH` |
| Database password | `VAULT_DB_PASSWORD_PATH` | `VAULT_DB_PASSWORD_PATH` |
| MinIO password | `VAULT_MINIO_PASSWORD_PATH` | `VAULT_MINIO_PASSWORD_PATH` |

Device credentials (OPNsense API keys) are stored in Vault using the `secret_backend` interface.

---

## Quick Start (Development)

### 1. Start Vault

```bash
docker compose up -d vault
```

Vault runs in dev mode with:
- URL: `http://localhost:8200`
- Root token: `ofme-dev-token`
- UI: http://localhost:8200 (use token to login)

### 2. Create Secrets

Using the Vault CLI:

```bash
export VAULT_ADDR=http://localhost:8200
export VAULT_TOKEN=ofme-dev-token

# Create secret key
vault kv put secret/ofme/secret-key value=$(openssl rand -hex 48)

# Create refresh pepper
vault kv put secret/ofme/refresh-pepper value=$(openssl rand -hex 32)

# Create database password
vault kv put secret/ofme/database/password value=CHANGE_ME_db_password

# Create MinIO password
vault kv put secret/ofme/minio/password value=CHANGE_ME_minio_password
```

### 3. Configure Application

Add to `.env`:

```bash
# Enable Vault
VAULT_ENABLED=true
VAULT_ADDR=http://vault:8200
VAULT_TOKEN=ofme-dev-token
VAULT_MOUNT_POINT=secret

# Secret paths
VAULT_SECRET_KEY_PATH=ofme/secret-key
VAULT_REFRESH_PEPPER_PATH=ofme/refresh-pepper
VAULT_DB_PASSWORD_PATH=ofme/database/password
VAULT_MINIO_PASSWORD_PATH=ofme/minio/password
```

### 4. Start Application

```bash
docker compose up -d
```

Check logs for Vault connection:

```bash
docker logs ofme-api | grep vault
# Expected: "vault.client_initialized" and "vault.backend_initialized"
```

---

## Production Deployment

### Vault Requirements

- Vault 1.18+ with KV v2 secrets engine enabled
- AppRole or Kubernetes auth method for automatic token renewal
- TLS enabled for Vault communication
- Proper ACL policies for least-privilege access

### ACL Policy

Create a policy `ofme-policy` with minimal permissions:

```hcl
# Vault policy: ofme-policy.hcl
path "secret/data/ofme/*" {
  capabilities = ["read", "create", "update", "delete"]
}

path "secret/metadata/ofme/*" {
  capabilities = ["read", "delete"]
}
```

Apply the policy:

```bash
vault policy write ofme-policy ofme-policy.hcl
```

### AppRole Authentication (Recommended)

Create AppRole for OFME:

```bash
# Create AppRole
vault write auth/approle/role/ofme \
    token_policies="ofme-policy" \
    token_ttl=1h \
    token_max_ttl=4h \
    secret_id_num_uses=0 \
    secret_id_ttl=24h

# Get role_id
vault read auth/approle/role/ofme/role-id

# Get secret_id
vault write -f auth/approle/role/ofme/secret-id
```

Configure environment:

```bash
VAULT_ADDR=https://vault.example.com
VAULT_AUTH_METHOD=approle
VAULT_ROLE_ID=<role-id>
VAULT_SECRET_ID=<secret-id>
```

### Kubernetes Authentication

For Kubernetes deployments:

```bash
# Enable Kubernetes auth
vault auth enable kubernetes

# Configure Kubernetes auth
vault write auth/kubernetes/config \
    kubernetes_host=https://kubernetes.default.svc \
    kubernetes_ca_cert=@/var/run/secrets/kubernetes.io/serviceaccount/ca.crt

# Create OFME role
vault write auth/kubernetes/role/ofme \
    bound_service_account_names=ofme-api \
    bound_service_account_namespaces=ofme \
    policies=ofme-policy \
    ttl=1h
```

---

## Device Credentials (B-H3)

Device credentials (OPNsense API keys) are automatically stored in Vault when enabled.

### Storage Format

```
secret/ofme/devices/<device_uuid>
{
  "api_key_encrypted": "<envelope-encrypted-api-key>",
  "api_secret_encrypted": "<envelope-encrypted-secret>"
}
```

### Implementation Details

- Credentials are envelope-encrypted with AES-256-GCM using the `SECRET_KEY`
- Encrypted values are stored in Vault to minimize plaintext exposure
- On startup, Vault secrets take precedence over environment variables
- Local encrypted fields used as fallback when Vault unavailable

### Usage in Code

```python
from app.integrations.vault import secret_backend

# Store device credentials (internal, handles encryption)
await secret_backend.put(
    f"devices/{device_id}",
    {"api_key_encrypted": <key>, "api_secret_encrypted": <secret>}
)

# Retrieve device credentials (internal, handles decryption)
creds = await secret_backend.get(f"devices/{device_id}")
if creds:
    api_key = decrypt_secret(creds["api_key_encrypted"])
    api_secret = decrypt_secret(creds["api_secret_encrypted"])
```

---

## Health Check

Vault connectivity is included in the `/api/v1/health/ready` endpoint:

```json
{
  "status": "ready",
  "components": {
    "database": {"status": "up"},
    "redis": {"status": "up"},
    "object_storage": {"status": "up"},
    "pki": {"status": "up"},
    "vault": {"status": "up", "detail": "backend=vault"}
  }
}
```

---

## Migration from Local Secrets

### Before Migration

Ensure all secrets are in `.env` file or environment variables.

### Migration Steps

1. **Enable Vault in dev mode** alongside existing configuration
2. **Copy secrets to Vault** using the CLI or UI
3. **Verify Vault connectivity** via health endpoint
4. **Switch one service at a time** to Vault-based secrets
5. **Monitor logs** for any secret retrieval failures
6. **Remove secrets from `.env`** once confident

### Rollback

If Vault becomes unavailable:
1. Set `VAULT_ENABLED=false`
2. Application falls back to environment variables
3. Restart affected services

---

## Files Modified

| File | Description |
|------|-------------|
| `backend/app/integrations/vault.py` | Vault client with hvac library |
| `backend/app/core/config.py` | Vault secret loading at startup |
| `backend/app/api/v1/endpoints/health.py` | Vault health check |
| `backend/app/services/devices.py` | Device credentials in Vault |
| `docker-compose.yml` | Vault dev service |
| `.env.example` | Vault configuration template |
| `pyproject.toml` | Added hvac dependency |
| `docs/VAULT_INTEGRATION.md` | This documentation |

---

## Security Considerations

### Token Management

- **Never commit** Vault tokens to version control
- Use **short-lived tokens** with automatic renewal
- Rotate tokens regularly (recommended: every 24-72 hours)
- Use **AppRole** or **Kubernetes auth** for automatic token renewal

### Network Security

- Vault communication **must use TLS** in production
- Restrict Vault access to application network
- Use **mTLS** for service-to-Vault communication

### Audit Logging

Enable Vault audit logging:

```bash
vault audit enable file file_path=/var/log/vault/audit.log
```

### Secret Rotation

Implement regular secret rotation:

```bash
# Rotate SECRET_KEY
vault kv patch secret/ofme/secret-key value=$(openssl rand -hex 48)

# Application must be restarted to pick up new secrets
# Or implement dynamic secret reloading
```

---

## Troubleshooting

### "hvac package not installed"

Install the hvac package:

```bash
pip install hvac>=1.1.1
```

### "Vault read failed: 403"

Check ACL policy permissions and token validity.

### "Vault read failed: 404"

Verify secret path is correct and KV v2 engine is mounted at expected path.

### Application won't start without Vault

Ensure `VAULT_ENABLED=false` for local development without Vault.

---

## References

- [HashiCorp Vault Documentation](https://developer.hashicorp.com/vault/docs)
- [hvac Python Client](https://github.com/hvac/hvac)
- [Vault KV Secrets Engine v2](https://developer.hashicorp.com/vault/docs/secrets/kv/kv-v2)
