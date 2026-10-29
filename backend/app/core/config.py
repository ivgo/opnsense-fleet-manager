"""Central configuration. All runtime configuration flows from environment variables."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---------------------------------------------------------------- application
    APP_NAME: str = "OPNsense Fleet Manager Enterprise"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: Literal["development", "testing", "staging", "production"] = "development"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"
    ALLOWED_HOSTS: str = "*"
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000"
    TRUSTED_PROXY_IPS: str = ""

    # ---------------------------------------------------------------- security
    SECRET_KEY: str = Field(..., min_length=32)
    JWT_ALGORITHM: str = "RS256"
    JWT_PRIVATE_KEY_PATH: str = ""
    JWT_PUBLIC_KEY_PATH: str = ""
    REFRESH_TOKEN_PEPPER: str = ""  # HMAC pepper for refresh token hashing (generate with: openssl rand -hex 32)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    PASSWORD_MIN_LENGTH: int = 12
    LOGIN_MAX_FAILURES: int = 5
    LOGIN_LOCK_MINUTES: int = 15
    ENABLE_MFA: bool = True
    MFA_ISSUER: str = "OFME"
    API_KEY_PREFIX: str = "ofme"

    # ---------------------------------------------------------------- database
    DATABASE_URL: str = "postgresql+asyncpg://ofme:ofme@localhost:5432/ofme"
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_RECYCLE_SECONDS: int = 1800
    DB_ECHO: bool = False

    # ---------------------------------------------------------------- redis / celery
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"
    CELERY_TASK_TIME_LIMIT: int = 1800
    CELERY_TASK_SOFT_TIME_LIMIT: int = 1500

    # ---------------------------------------------------------------- object storage
    S3_ENDPOINT: str = "http://localhost:9000"
    S3_ACCESS_KEY: str = "minioadmin"
    S3_SECRET_KEY: str = "minioadmin"
    S3_REGION: str = "us-east-1"
    S3_USE_SSL: bool = False
    S3_BUCKET_BACKUPS: str = "ofme-backups"
    S3_BUCKET_ARTIFACTS: str = "ofme-artifacts"
    # Optional server-side encryption for every uploaded object. Leave empty
    # for MinIO without KMS (MinIO dropped SSE-S3); set "AES256" for AWS S3 or
    # "aws:kms" together with S3_KMS_KEY_ID. Backup payloads are additionally
    # encrypted client-side (AES-256-GCM) before they reach the bucket.
    S3_SERVER_SIDE_ENCRYPTION: str = ""
    S3_KMS_KEY_ID: str | None = None

    # ---------------------------------------------------------------- PKI
    PKI_CA_CERT_PATH: str = "/etc/ofme/pki/ca.crt"
    PKI_CA_KEY_PATH: str = "/etc/ofme/pki/ca.key"
    PKI_DEVICE_VALIDITY_DAYS: int = 365
    PKI_RENEW_BEFORE_DAYS: int = 30
    PKI_KEY_SIZE: int = 3072
    ENROLLMENT_TOKEN_TTL_MINUTES: int = 60

    # ---------------------------------------------------------------- directory / SSO
    LDAP_SERVER: str = ""
    LDAP_BASE_DN: str = ""
    LDAP_BIND_DN: str = ""
    LDAP_BIND_PASSWORD: str = ""
    LDAP_USER_FILTER: str = "(uid={username})"
    LDAP_GROUP_ATTRIBUTE: str = "memberOf"
    LDAP_USE_TLS: bool = True
    LDAP_ROLE_MAP: str = ""  # "cn=ofme-admins,ou=groups,dc=x=TenantAdmin;..."

    OIDC_ISSUER: str = ""
    OIDC_CLIENT_ID: str = ""
    OIDC_CLIENT_SECRET: str = ""
    OIDC_REDIRECT_URI: str = "http://localhost:5173/auth/callback"
    OIDC_SCOPES: str = "openid profile email groups"

    ENTRA_TENANT_ID: str = ""
    ENTRA_CLIENT_ID: str = ""
    ENTRA_CLIENT_SECRET: str = ""

    SAML_ENABLED: bool = False
    SAML_IDP_ENTITY_ID: str = ""
    SAML_IDP_SSO_URL: str = ""
    SAML_IDP_SLO_URL: str = ""
    #: PEM or bare base64 body of the IdP signing certificate.
    SAML_IDP_CERT: str = ""
    SAML_SP_ENTITY_ID: str = "ofme"
    SAML_SP_ACS_URL: str = "http://localhost:8000/api/v1/auth/saml/acs"
    #: Optional PEM private key/certificate used to sign AuthnRequests.
    SAML_SP_KEY: str = ""
    SAML_SP_CERT: str = ""
    SAML_ATTRIBUTE_EMAIL: str = "email"
    SAML_ATTRIBUTE_NAME: str = "displayName"
    SAML_ATTRIBUTE_USERNAME: str = "uid"
    SAML_ATTRIBUTE_GROUPS: str = "groups"
    SAML_DEFAULT_ROLE: str = "ReadOnly"
    #: Where the ACS sends the browser after issuing tokens.
    FRONTEND_URL: str = "http://localhost:8080"

    # ---------------------------------------------------------------- vault
    VAULT_ADDR: str = ""
    VAULT_TOKEN: str = ""
    VAULT_MOUNT_POINT: str = "secret"
    VAULT_ENABLED: bool = False
    # Vault secret paths (optional - if set, secrets are read from Vault at startup)
    VAULT_SECRET_KEY_PATH: str = ""  # e.g., "ofme/secret-key"
    VAULT_REFRESH_PEPPER_PATH: str = ""  # e.g., "ofme/refresh-pepper"
    VAULT_DB_PASSWORD_PATH: str = ""  # e.g., "ofme/database/password"
    VAULT_MINIO_PASSWORD_PATH: str = ""  # e.g., "ofme/minio/password"

    # ---------------------------------------------------------------- git providers
    GITHUB_API_URL: str = "https://api.github.com"
    GITHUB_TOKEN: str = ""
    GITLAB_URL: str = "https://gitlab.com"
    GITLAB_TOKEN: str = ""
    AZURE_DEVOPS_ORG: str = ""
    AZURE_DEVOPS_PAT: str = ""
    GIT_WORK_DIR: str = "/tmp/ofme-git"
    GIT_COMMIT_AUTHOR: str = "OFME Automation <automation@ofme.local>"

    # ---------------------------------------------------------------- platform behaviour
    HEARTBEAT_INTERVAL_SECONDS: int = 60
    DEVICE_OFFLINE_AFTER_SECONDS: int = 180
    METRIC_RETENTION_DAYS: int = 90
    AUDIT_RETENTION_DAYS: int = 2555
    WEBHOOK_TIMEOUT_SECONDS: int = 15
    OPNsense_TIMEOUT_SECONDS: int = 20
    OPNsense_VERIFY_TLS: bool = True
    DEFAULT_TENANT_SLUG: str = "default"
    BOOTSTRAP_ADMIN_EMAIL: str = "admin@ofme.example.com"
    BOOTSTRAP_ADMIN_PASSWORD: str = ""
    ENABLE_DOCS: bool = True

    # ---------------------------------------------------------------- rate limiting
    # Fixed-window budgets per identity (credential digest, device id or client
    # IP). Authentication endpoints get their own, much smaller budget.
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_REQUESTS: int = 600
    RATE_LIMIT_AUTH_REQUESTS: int = 20
    RATE_LIMIT_WINDOW_SECONDS: int = 60

    # ---------------------------------------------------------------- observability
    OTEL_ENABLED: bool = False
    OTEL_EXPORTER_OTLP_ENDPOINT: str = "http://localhost:4318"
    OTEL_SERVICE_NAME: str = "ofme-api"
    LOG_LEVEL: str = "INFO"
    LOG_JSON: bool = True

    # ---------------------------------------------------------------- grpc
    # Internal read-only inventory API. Off by default: no listener is opened
    # until both GRPC_ENABLED and GRPC_SERVICE_TOKEN are set.
    # For mTLS: set GRPC_TLS_CERT_PATH, GRPC_TLS_KEY_PATH, and GRPC_TLS_CA_CERT_PATH.
    GRPC_ENABLED: bool = False
    GRPC_BIND: str = "0.0.0.0:50051"
    GRPC_SERVICE_TOKEN: str = ""
    GRPC_TLS_CERT_PATH: str = ""
    GRPC_TLS_KEY_PATH: str = ""
    GRPC_TLS_CA_CERT_PATH: str = ""  # CA cert for client certificate verification (mTLS)
    GRPC_REQUIRE_CLIENT_CERT: bool = False  # Require client certificate for mTLS

    @field_validator("SECRET_KEY")
    @classmethod
    def _secret_strength(cls, value: str, info) -> str:
        env = info.data.get("ENVIRONMENT", "development")
        if env == "production" and len(value) < 64:
            raise ValueError("SECRET_KEY must be at least 64 characters in production")
        return value

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def allowed_hosts(self) -> list[str]:
        return [host.strip() for host in self.ALLOWED_HOSTS.split(",") if host.strip()]

    @property
    def trusted_proxy_ips(self) -> list[str]:
        """Proxy addresses/CIDRs whose ``X-Real-IP``/``X-Forwarded-For`` are honoured."""
        return [entry.strip() for entry in self.TRUSTED_PROXY_IPS.split(",") if entry.strip()]

    @property
    def sync_database_url(self) -> str:
        """psycopg URL for Alembic and synchronous tooling."""
        return self.DATABASE_URL.replace("+asyncpg", "+psycopg")

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def ldap_role_map(self) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for pair in self.LDAP_ROLE_MAP.split(";"):
            if "=" in pair:
                dn, role = pair.split("=", 1)
                mapping[dn.strip().lower()] = role.strip()
        return mapping


import asyncio
import os

# Lazy-loaded Vault secrets - loaded once at startup
_vault_secrets_loaded = False

@lru_cache(maxsize=1)
def get_settings() -> Settings:
    global _vault_secrets_loaded
    cfg = Settings()
    # Load secrets from Vault if enabled and paths are provided.
    # Import is deferred to avoid a circular import: vault.py imports
    # app.core.config.settings, and app.integrations.__init__ imports
    # app.integrations.git.providers which imports settings.
    # Import directly from the vault module to avoid triggering app.integrations.__init__
    if cfg.VAULT_ENABLED and not _vault_secrets_loaded:
        # Use synchronous hvac client to load secrets at startup
        # This avoids asyncio.run() issues during uvicorn startup
        try:
            import hvac
            client = hvac.Client(
                url=cfg.VAULT_ADDR,
                token=cfg.VAULT_TOKEN if cfg.VAULT_TOKEN else None,
            )
            mount_point = cfg.VAULT_MOUNT_POINT

            # SECRET_KEY
            if cfg.VAULT_SECRET_KEY_PATH:
                try:
                    result = client.secrets.kv.v2.read_secret_version(
                        path=cfg.VAULT_SECRET_KEY_PATH,
                        mount_point=mount_point,
                    )
                    if result and "data" in result and "data" in result["data"]:
                        values = result["data"]["data"]
                        # Get first value
                        val = next(iter(values.values()), None)
                        if val:
                            cfg.SECRET_KEY = val
                except Exception:
                    pass  # Secret not found, keep default

            # REFRESH_TOKEN_PEPPER
            if cfg.VAULT_REFRESH_PEPPER_PATH:
                try:
                    result = client.secrets.kv.v2.read_secret_version(
                        path=cfg.VAULT_REFRESH_PEPPER_PATH,
                        mount_point=mount_point,
                    )
                    if result and "data" in result and "data" in result["data"]:
                        values = result["data"]["data"]
                        val = next(iter(values.values()), None)
                        if val:
                            cfg.REFRESH_TOKEN_PEPPER = val
                except Exception:
                    pass

            # DATABASE password
            if cfg.VAULT_DB_PASSWORD_PATH:
                try:
                    result = client.secrets.kv.v2.read_secret_version(
                        path=cfg.VAULT_DB_PASSWORD_PATH,
                        mount_point=mount_point,
                    )
                    if result and "data" in result and "data" in result["data"]:
                        values = result["data"]["data"]
                        val = next(iter(values.values()), None)
                        if val:
                            # Replace password in DATABASE_URL
                            parts = cfg.DATABASE_URL.split('@')
                            if len(parts) == 2:
                                cred, rest = parts
                                user = cred.split(':')[1].split('//')[1]
                                cfg.DATABASE_URL = f"postgresql+asyncpg://{user}:{val}@{rest}"
                except Exception:
                    pass

            # MinIO password
            if cfg.VAULT_MINIO_PASSWORD_PATH:
                try:
                    result = client.secrets.kv.v2.read_secret_version(
                        path=cfg.VAULT_MINIO_PASSWORD_PATH,
                        mount_point=mount_point,
                    )
                    if result and "data" in result and "data" in result["data"]:
                        values = result["data"]["data"]
                        val = next(iter(values.values()), None)
                        if val:
                            cfg.S3_SECRET_KEY = val
                except Exception:
                    pass
        except ImportError:
            pass  # hvac not installed, skip Vault loading
        except Exception:
            pass  # Vault not accessible, skip

        _vault_secrets_loaded = True
    return cfg


# Resolve Literal forward references for pydantic 2.x
Settings.model_rebuild()


settings = get_settings()
