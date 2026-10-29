# Deployment

Three supported topologies:

| Topology | Use | Entry point |
|---|---|---|
| Docker Compose | evaluation, single-host installations, labs | `docker compose up -d --build` |
| Raw Kubernetes | one cluster, manifests as the source of truth | `kubectl apply -k deploy/k8s` |
| Helm + ArgoCD | multi-environment, GitOps-driven operations | `deploy/helm/ofme`, `deploy/argocd` |

The application container is the same artefact in all three: the API, Celery
worker and beat run from one image with different commands.

## Requirements

* Docker 24+ with Compose v2 (compose topology), or Kubernetes 1.27+.
* 4 vCPU / 8 GiB RAM for a pilot fleet (< 250 devices).
* PostgreSQL 16, Redis 7, S3-compatible storage (MinIO is bundled in compose only).
* A TLS-terminating ingress for anything reachable from a browser.
* Outbound HTTPS from the API/worker pods to each device's management address, and
  inbound HTTPS from devices to `/api/v1/agent` through the ingress.

## 1. Docker Compose

```bash
cd ofme
cp .env.example .env
```

Edit `.env` before the first start. The values that must change:

```bash
SECRET_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(48))")
POSTGRES_PASSWORD=$(python -c "import secrets; print(secrets.token_urlsafe(24))")
MINIO_ROOT_PASSWORD=$(python -c "import secrets; print(secrets.token_urlsafe(24))")
S3_SECRET_KEY=$MINIO_ROOT_PASSWORD
DATABASE_URL=postgresql+asyncpg://ofme:$POSTGRES_PASSWORD@postgres:5432/ofme
GRAFANA_ADMIN_PASSWORD=$(python -c "import secrets; print(secrets.token_urlsafe(18))")
BOOTSTRAP_ADMIN_PASSWORD=<one-time-password>
ENVIRONMENT=production
ENABLE_DOCS=false
ALLOWED_HOSTS=ofme.example.com
CORS_ORIGINS=https://ofme.example.com
```

Then:

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f ofme-api
```

What starts:

| Service | Port (host) | Notes |
|---|---|---|
| `postgres` | 5432 | data in `ofme-postgres` volume |
| `redis` | 6379 | AOF enabled, `noeviction` (broker safety) |
| `minio` | 9000 / 9001 | the API creates `ofme-backups` (versioned) and `ofme-artifacts` on startup |
| `ofme-api` | 8000, 50051 | uvicorn **one worker**; runs migrations then serves |
| `ofme-worker` | – | Celery, concurrency 4 |
| `ofme-beat` | – | single instance, schedules in `celery_app.py` |
| `ofme-frontend` | 8080 | nginx-served SPA, proxies `/api` and `/ws` |
| `prometheus` | 9090 | scrapes `ofme-api:8000/metrics` |
| `grafana` | 3000 | provisioned datasources and the OFME dashboard |
| `loki` / `promtail` | 3100 | container logs |
| `otel-collector` | 4317/4318/9464 | OTLP in, Prometheus exporter |

The API entrypoint (`backend/docker-entrypoint.sh`) waits up to 120 s for
PostgreSQL, runs `alembic upgrade head` when `RUN_MIGRATIONS=true`, then execs the
container command. On first boot the lifespan also:

1. creates the CA if `PKI_CA_CERT_PATH`/`PKI_CA_KEY_PATH` are empty (compose keeps
   it in the `ofme-pki` volume);
2. ensures the S3 buckets exist;
3. registers CQRS handlers and starts the Redis event bridge;
4. seeds the default tenant and the `BOOTSTRAP_ADMIN_EMAIL` account **only** when
   `BOOTSTRAP_ADMIN_PASSWORD` is non-empty;
5. starts the WebSocket hub and, when enabled, the gRPC listener.

Failures in steps 1–2 are logged (`startup.pki_failed`, `startup.storage_failed`)
and surface in `GET /api/v1/health/ready`; they do not stop the process.

### First login

Open `http://localhost:8080`, sign in with `BOOTSTRAP_ADMIN_EMAIL` and
`BOOTSTRAP_ADMIN_PASSWORD`, enrol TOTP, change the password, then **remove**
`BOOTSTRAP_ADMIN_PASSWORD` from `.env` and restart the API. The seed is
idempotent and never resets an existing password.

### HTTPS

Compose publishes plain HTTP. Put a reverse proxy in front:

```nginx
server {
    listen 443 ssl http2;
    server_name ofme.example.com;
    ssl_certificate     /etc/ssl/ofme/fullchain.pem;
    ssl_certificate_key /etc/ssl/ofme/privkey.pem;

    client_max_body_size 32m;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    # Agent mTLS: verify the client certificate and forward its fingerprint.
    location /api/v1/agent/ {
        proxy_pass http://127.0.0.1:8000;
        ssl_client_certificate /etc/ssl/ofme/device-ca.crt;
        ssl_verify_client on;
        proxy_set_header X-Client-Cert-Fingerprint $ssl_client_fingerprint;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header Host $host;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    location /ws {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 3600s;
    }
}
```

`ssl_client_certificate` must point at the **device CA** (`pki/ca.crt`), not a
public CA. If the proxy is not configured to verify clients, never accept
`X-Device-Cert-Fingerprint` from the internet: the API trusts it.

In production also close direct access to 5432/6379/9000/9001/9090/3000 and set
`TRUSTED_PROXY_IPS` to the proxy addresses so client IPs in audit rows are the
real ones.

## 2. Environment reference

Full template: `.env.example`. Settings are read by `app/core/config.py`; unknown
keys are ignored, so a shared `.env` across environments is safe.

### Core

| Variable | Default | Purpose |
|---|---|---|
| `ENVIRONMENT` | `development` | `development`/`testing`/`staging`/`production`; production enforces `SECRET_KEY` length and HSTS |
| `DEBUG` | `false` | never enable in production |
| `ENABLE_DOCS` | `true` | serves `/docs`, `/redoc`, `/{prefix}/openapi.json`; disable in production |
| `ALLOWED_HOSTS` | `*` | host allow-list for the trusted-host middleware |
| `CORS_ORIGINS` | localhost origins | comma-separated allow-list; must match the console URL |
| `TRUSTED_PROXY_IPS` | empty | proxies whose `X-Forwarded-*` headers are trusted |
| `RATE_LIMIT_ENABLED` | `true` | master switch for the application rate limiter |
| `RATE_LIMIT_REQUESTS` | `600` | per-identity budget per window for the general API |
| `RATE_LIMIT_AUTH_REQUESTS` | `20` | stricter per-identity budget for `/auth/*` endpoints |
| `RATE_LIMIT_WINDOW_SECONDS` | `60` | fixed-window length in seconds |
| `API_V1_PREFIX` | `/api/v1` | mount point for the REST API |

### Security

| Variable | Default | Purpose |
|---|---|---|
| `SECRET_KEY` | dev placeholder | JWT signing + AES-GCM key derivation; ≥ 32 chars in production |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | access-token TTL |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | refresh-session TTL |
| `PASSWORD_MIN_LENGTH` | `12` | password policy |
| `LOGIN_MAX_FAILURES` / `LOGIN_LOCK_MINUTES` | `5` / `15` | per-account lockout |
| `ENABLE_MFA` | `true` | allow TOTP |
| `API_KEY_PREFIX` | `ofme` | prefix used to recognise API keys |

### Data stores

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://…` | async driver URL; Alembic derives the `+psycopg` form |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | `10` / `20` | per-process pool |
| `REDIS_URL` | `redis://…/0` | cache, WebSocket pub/sub |
| `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` | `…/1`, `…/2` | keep separate from `REDIS_URL` |
| `S3_ENDPOINT`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_REGION`, `S3_USE_SSL` | local MinIO | object storage |
| `S3_BUCKET_BACKUPS` / `S3_BUCKET_ARTIFACTS` | `ofme-backups` / `ofme-artifacts` | created at startup if missing |

### PKI and agents

| Variable | Default | Purpose |
|---|---|---|
| `PKI_CA_CERT_PATH` / `PKI_CA_KEY_PATH` | `/etc/ofme/pki/ca.{crt,key}` | shared by API and workers |
| `PKI_KEY_SIZE` | `3072` | CA RSA key size (already-created CAs are not resized) |
| `PKI_DEVICE_VALIDITY_DAYS` | `365` | device certificate lifetime |
| `PKI_RENEW_BEFORE_DAYS` | `30` | rotation window |
| `ENROLLMENT_TOKEN_TTL_MINUTES` | `60` | default ZTP token TTL |
| `HEARTBEAT_INTERVAL_SECONDS` | `60` | advertised to agents and used by the timeout sweeper |
| `DEVICE_OFFLINE_AFTER_SECONDS` | `180` | heartbeat timeout before `offline` |
| `OPNsense_TIMEOUT_SECONDS` | `20` | REST client timeout |
| `OPNsense_VERIFY_TLS` | `true` | verify device certificates |

### Identity providers

`LDAP_SERVER`, `LDAP_BASE_DN`, `LDAP_BIND_DN`, `LDAP_BIND_PASSWORD`,
`LDAP_USER_FILTER`, `LDAP_GROUP_ATTRIBUTE`, `LDAP_USE_TLS`, `LDAP_ROLE_MAP`;
`OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `OIDC_REDIRECT_URI`,
`OIDC_SCOPES`; `ENTRA_TENANT_ID`, `ENTRA_CLIENT_ID`, `ENTRA_CLIENT_SECRET`.
Leaving the issuer/client empty disables the provider; `GET /api/v1/auth/providers`
reports what is active so the login page can hide unused buttons.

### Behaviour, retention, observability

`METRIC_RETENTION_DAYS` (90), `AUDIT_RETENTION_DAYS` (2555),
`WEBHOOK_TIMEOUT_SECONDS` (15), `GIT_WORK_DIR`, `GIT_COMMIT_AUTHOR`;
`OTEL_ENABLED`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_SERVICE_NAME`, `LOG_LEVEL`,
`LOG_JSON`. See [OPERATIONS.md](OPERATIONS.md) for what to alert on.

### gRPC

| Variable | Default | Purpose |
|---|---|---|
| `GRPC_ENABLED` | `false` | opens a listener only when `true` |
| `GRPC_BIND` | `0.0.0.0:50051` | in-container bind address |
| `GRPC_SERVICE_TOKEN` | empty | shared secret; gRPC refuses to start without it |
| `GRPC_TLS_CERT_PATH` / `GRPC_TLS_KEY_PATH` | empty | serve gRPC over TLS |

The listener runs inside the API lifespan, so **the API container must stay at one
uvicorn worker per pod**. Scale with replicas, not workers. Compose maps
`${GRPC_PORT:-50051}:50051`; in Helm the Service port is only rendered when
`grpc.enabled=true`.

## 3. Kubernetes (raw manifests)

`deploy/k8s/` is a self-contained, single-region reference. Follow
`deploy/k8s/README.md`; the sequence is:

```bash
# 1. namespace
kubectl apply -f deploy/k8s/namespace.yaml

# 2. application secret (never commit)
kubectl -n ofme create secret generic ofme-secrets \
  --from-literal=SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')" \
  --from-literal=DATABASE_URL="postgresql+asyncpg://ofme:<password>@ofme-postgres:5432/ofme" \
  --from-literal=REDIS_URL="redis://ofme-redis:6379/0" \
  --from-literal=CELERY_BROKER_URL="redis://ofme-redis:6379/1" \
  --from-literal=CELERY_RESULT_BACKEND="redis://ofme-redis:6379/2" \
  --from-literal=S3_ENDPOINT="http://ofme-minio:9000" \
  --from-literal=S3_ACCESS_KEY="ofme-minio" \
  --from-literal=S3_SECRET_KEY="<password>" \
  --from-literal=BOOTSTRAP_ADMIN_PASSWORD="<one-time-password>"

# 3. CA, generated once and mounted by API + workers
cd backend && python scripts/init_pki.py --output ../deploy/k8s/pki
kubectl -n ofme create secret generic ofme-pki \
  --from-file=ca.crt=../deploy/k8s/pki/ca.crt \
  --from-file=ca.key=../deploy/k8s/pki/ca.key
rm -rf ../deploy/k8s/pki

# 4. workloads
kubectl apply -k deploy/k8s
kubectl -n ofme rollout status deploy/ofme-api
```

Use a managed PostgreSQL/Redis/S3 in production and remove `datastores.yaml` from
`kustomization.yaml`. `ofme-api` and `ofme-frontend` must keep those Service
names: the SPA's nginx config proxies `/api/` and `/ws` to `ofme-api:8000`.

Notable manifest behaviour:

* `configmap.yaml` holds non-secret settings including `RUN_MIGRATIONS=true` and
  `WAIT_FOR_DB=true`.
* `api.yaml` runs a single uvicorn worker, exposes `http` (8000) and `grpc`
  (50051), and mounts `ofme-pki` read-only.
* `worker.yaml` uses the same image with the Celery command; `beat.yaml` is
  `strategy: Recreate` with a small PVC for the schedule file.
* `networkpolicy.yaml` is default-deny plus explicit allows (ingress → API,
  API/worker → datastores, Prometheus → API, DNS).
* `hpa.yaml` scales API on CPU (70%) and workers on CPU (75%); `pdb.yaml` keeps
  one pod available during drains.

### Migrations at scale

`RUN_MIGRATIONS=true` makes every API pod race the same `alembic upgrade`. It is
safe (Alembic takes locks) but noisy. Beyond a handful of replicas:

```bash
# one-shot Job using the same image
kubectl -n ofme create job --from=cronjob/... # or:
kubectl -n ofme run ofme-migrate --rm -it --image=ghcr.io/ofme/ofme-api:1.0.0 \
  --env="DATABASE_URL=$DATABASE_URL" -- alembic upgrade head
```

then set `RUN_MIGRATIONS=false` in the ConfigMap and roll the deployment.

## 4. Helm

```bash
helm lint deploy/helm/ofme
helm template ofme deploy/helm/ofme --namespace ofme > /tmp/ofme.yaml   # inspect

kubectl create namespace ofme
kubectl -n ofme create secret generic ofme-secrets \
  --from-literal=SECRET_KEY=... \
  --from-literal=DATABASE_URL=... \
  --from-literal=REDIS_URL=... \
  --from-literal=CELERY_BROKER_URL=... \
  --from-literal=CELERY_RESULT_BACKEND=... \
  --from-literal=S3_ENDPOINT=... \
  --from-literal=S3_ACCESS_KEY=... \
  --from-literal=S3_SECRET_KEY=... \
  --from-literal=BOOTSTRAP_ADMIN_PASSWORD=...

helm upgrade --install ofme deploy/helm/ofme \
  --namespace ofme \
  --set image.api.tag=1.0.0 \
  --set image.frontend.tag=1.0.0 \
  --set ingress.hosts[0].host=ofme.example.com \
  --set config.ALLOWED_HOSTS=ofme.example.com \
  --set config.CORS_ORIGINS=https://ofme.example.com \
  --set config.ENABLE_DOCS=false
```

The chart deploys **stateless components only** (API, worker, beat, frontend);
PostgreSQL, Redis and object storage are external. Every pod runs as UID 10001,
non-root, read-only root filesystem, all capabilities dropped, with
`RuntimeDefault` seccomp.

Values that commonly change:

| Value | Default | Notes |
|---|---|---|
| `api.replicaCount` / `api.autoscaling.maxReplicas` | 2 / 12 | API is stateless; one uvicorn worker each |
| `worker.replicaCount` / `worker.concurrency` | 2 / 4 | raise concurrency for I/O-heavy backup runs |
| `beat.replicaCount` | 1 | must never be > 1 |
| `ingress.hosts[0].host` | `ofme.example.com` | also update `config.ALLOWED_HOSTS`/`CORS_ORIGINS` |
| `config.GRPC_ENABLED` + `grpc.enabled` | `false` | both must be set together |
| `secrets.existingSecret` | `ofme-secrets` | must contain the keys listed in `values.yaml` |
| `pki.existingSecret` | `ofme-pki` | created with `init_pki.py` |

`helm test` is not used; verify with:

```bash
kubectl -n ofme port-forward svc/ofme-api 8000:8000 &
curl -fsS http://127.0.0.1:8000/api/v1/health/ready | jq
```

## 5. ArgoCD

`deploy/argocd/` contains an `AppProject`, a production and a staging
`Application`, and a `kustomization.yaml` that applies all three.

```bash
kubectl apply -f deploy/argocd/project.yaml
kubectl apply -f deploy/argocd/application-staging.yaml
# production is promoted by changing the image tag (or the values file) in Git
kubectl apply -f deploy/argocd/application.yaml
```

Both Applications point at `deploy/helm/ofme` with `automated: {prune: true,
selfHeal: true}`; `ignoreDifferences` excludes `/spec/replicas` so the HPA owns
replica counts. Update `source.repoURL`, the hostnames and `config.*` in the
Application before applying — they are placeholders for a real installation.

Promotion flow: staging Application syncs `main`, a tag is cut, the production
Application's `image.*.tag` is bumped in a commit, ArgoCD syncs it. Rollback is
`argocd app rollback ofme-production <revision>` or reverting the tag commit.

## 6. PKI bootstrap

The CA must exist **before** the first API pod starts, otherwise two replicas can
each create a different CA.

```bash
cd backend
python scripts/init_pki.py --output ../pki
# certificate: ../pki/ca.crt
# private key: ../pki/ca.key (mode 0600)
# sha256 fingerprint: ...
```

* Compose keeps the pair in the `ofme-pki` volume; the first API container
  creates it if the volume is empty. That is acceptable for a single-host
  installation and **not** for a multi-replica deployment.
* Kubernetes: create `ofme-pki` from the files (or
  `python scripts/init_pki.py --kubectl-secret --namespace ofme | kubectl apply -f -`)
  and mount it read-only into every API and worker pod.
* The CA certificate is what agents pin; distribute `ca.crt` with the plugin
  package and to the ingress (`ssl_client_certificate`).
* Back up `ca.key` offline. Losing it means re-enrolling every device; leaking it
  means an attacker can mint device identities.

## 7. Upgrades

```bash
# compose
docker compose pull
docker compose up -d --build
docker compose logs -f ofme-api | grep -E 'startup|migration'

# kubernetes (Helm)
helm upgrade ofme deploy/helm/ofme --namespace ofme --reuse-values --set image.api.tag=1.1.0 ...
kubectl -n ofme rollout status deploy/ofme-api

# argocd
argocd app set ofme-production -p image.api.tag=1.1.0
argocd app sync ofme-production
```

Order of operations for a release that changes the schema:

1. back up PostgreSQL (`make db-dump` or the managed snapshot);
2. apply the migration (entrypoint or a Job);
3. roll the API, then the workers;
4. roll beat last (it only schedules tasks);
5. verify `/api/v1/health/ready`, `/api/v1/audit/integrity`, and one device
   heartbeat.

`alembic downgrade -1` exists for every revision but is not a rollback strategy
for data-changing migrations. Prefer restore-from-snapshot for those.

### Rollback

* Stateless components: `helm rollback ofme <revision>` or
  `docker compose up -d --build` with the previous `OFME_IMAGE_TAG`.
* Schema: restore the pre-upgrade dump if the old image cannot read the new
  schema. The audit chain survives a logical restore because hashes are stored
  values — verify with `/api/v1/audit/integrity` afterwards.
* Frontend and API are versioned independently by image tag, but the SPA expects
  the API contract it was built against; roll both together.

## 8. Disaster recovery

| Asset | RPO | How |
|---|---|---|
| PostgreSQL | snapshot interval / WAL | `pg_dump` nightly + PITR; test restore quarterly |
| Device backups | last successful run | objects in S3 with checksums + HMAC; re-run from the device if the bucket is lost |
| CA key | zero | offline escrow; without it, re-enrol every device |
| `SECRET_KEY` | zero | Vault/KMS; without it, stored device secrets are unrecoverable (and JWTs invalid) |
| Configuration (Helm values, Git policies) | last commit | Git |

Restore drill:

```bash
gunzip -c ofme-20260101T000000Z.sql.gz \
  | docker compose exec -T postgres psql -U ofme -d ofme
cd backend && alembic upgrade head
curl -fsS localhost:8000/api/v1/audit/integrity -H "Authorization: Bearer $TOKEN"
```

Then confirm the fleet count, one device's latest backup and a WebSocket feed.

## 9. Sizing

| Fleet | API replicas | Workers | PostgreSQL | Redis |
|---|---|---|---|---|
| ≤ 250 devices | 1 | 2 × 4 | 2 vCPU / 4 GiB | 1 GiB |
| 1 000 devices | 2 | 2 × 8 | 4 vCPU / 16 GiB | 2 GiB |
| 10 000 devices | 4–8 (HPA) | 4–8 × 8 | 8–16 vCPU / 32–64 GiB, PITR | 4 GiB, replica |

Rules of thumb:

* one API pod handles ~150 dashboard requests/second at p95 < 500 ms on 4 vCPU;
* one worker slot handles one device operation at a time; a full backup sweep of
  10 000 devices at concurrency 32 takes roughly 30–60 minutes depending on
  latency;
* `device_metrics` grows ~1 row per metric per scrape; size storage from
  `METRIC_RETENTION_DAYS` or partition the table (see DATABASE.md).

Load-test before committing to a size: `tests/load/README.md`.

## 10. Air-gapped installations

* Mirror `ghcr.io/ofme/ofme-api`, `ghcr.io/ofme/ofme-frontend`, plus
  `postgres:16-alpine`, `redis:7-alpine`, `cgr.dev/chainguard/minio`,
  `prom/prometheus`, `grafana/grafana`, `grafana/loki`, `grafana/promtail` and
  `otel/opentelemetry-collector-contrib`.
* Pin MinIO to a release digest instead of `latest`; MinIO deleted its Docker Hub
  repositories in September 2026 and quay.io requires authentication, so the
  compose stack uses the Chainguard build. The image is distroless, which is why
  it has no in-container healthcheck and no `minio-init` sidecar: the API creates
  the buckets and enables versioning during startup.
* The frontend image needs no build-time network access; `VITE_API_BASE_URL`
  empty means same-origin.
* The OPNsense plugin package is built in a FreeBSD ports tree on the mirror;
  see `plugin/os-fleet-agent/README.md`.
* Set `OTEL_ENABLED=false` if no collector is deployed; the API must not block on
  an unreachable exporter.
