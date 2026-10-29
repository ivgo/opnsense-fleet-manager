# Deployment assets

This directory holds everything that runs OFME outside a development shell.
The written guide is [../docs/DEPLOYMENT.md](../docs/DEPLOYMENT.md); this file is
the map and the invariants that must hold when you edit the manifests.

```text
deploy/
├── k8s/            raw Kubernetes manifests (Kustomize), single region
├── helm/ofme/      Helm chart for stateless components (API, worker, beat, SPA)
└── argocd/         AppProject + staging/production Applications
```

`../docker-compose.yml` is the fourth topology (single host, all dependencies
included) and is documented in DEPLOYMENT.md, not here.

## Prerequisites

| Topology | Needs |
|---|---|
| Raw Kubernetes | Kubernetes 1.27+, `kubectl` 1.27+, `kustomize` (built in), ingress-nginx, a default StorageClass |
| Helm | Helm 3.14+, the same cluster prerequisites |
| ArgoCD | ArgoCD 2.10+, a Git remote that contains this repository, cluster credentials for the `ofme`/`ofme-staging` namespaces |
| Compose | Docker 24+ with Compose v2 |

External dependencies for every Kubernetes topology: PostgreSQL 16, Redis 7,
S3-compatible object storage, and a TLS-terminating ingress. The raw manifests
bundle PostgreSQL/Redis/MinIO for evaluation; the Helm chart does not.

## `deploy/k8s` — raw manifests

Applied as one Kustomization:

```bash
kubectl apply -f deploy/k8s/namespace.yaml
# create ofme-secrets and ofme-pki first (see deploy/k8s/README.md)
kubectl apply -k deploy/k8s
```

| File | Contents |
|---|---|
| `namespace.yaml` | `ofme` namespace, restricted Pod Security |
| `configmap.yaml` | non-secret environment (`RUN_MIGRATIONS=true`, `WAIT_FOR_DB=true`, …) |
| `secret.example.yaml` | template for `ofme-secrets` and `ofme-pki` |
| `datastores.yaml` | PostgreSQL, Redis, MinIO, bucket bootstrap (evaluation only) |
| `api.yaml` | API Deployment + Service (8000, 50051), PKI mount |
| `worker.yaml` | Celery worker Deployment |
| `beat.yaml` | Celery beat Deployment (`Recreate`) + schedule PVC |
| `frontend.yaml` | nginx-served SPA Deployment + Service |
| `ingress.yaml` | TLS ingress: `/` → frontend, `/api` and `/ws` → API |
| `hpa.yaml` | CPU autoscaling for API and workers |
| `pdb.yaml` | PodDisruptionBudgets |
| `networkpolicy.yaml` | default-deny plus explicit allows |
| `serviceaccounts.yaml` | dedicated ServiceAccounts |

Invariants:

* **Service names are fixed**: `ofme-api` and `ofme-frontend`. The frontend
  nginx image proxies `/api/` and `/ws` to `http://ofme-api:8000`.
* **One uvicorn worker per API pod.** gRPC runs inside the API lifespan; scale
  with replicas, not workers.
* **The CA exists before the API starts.** Create `ofme-pki` from
  `backend/scripts/init_pki.py`; otherwise two replicas can each bootstrap a
  different CA.
* **`RUN_MIGRATIONS=true`** makes every API pod race Alembic. It is safe but
  noisy; move to a one-shot Job and set it to `false` beyond a few replicas.
* Remove `datastores.yaml` from `kustomization.yaml` when using managed
  PostgreSQL/Redis/S3, and point `DATABASE_URL`, `REDIS_URL` and `S3_*` at the
  providers.

## `deploy/helm/ofme` — chart

Stateless components only; PostgreSQL, Redis and object storage come from
`secrets.existingSecret` values.

```bash
helm lint deploy/helm/ofme
helm template ofme deploy/helm/ofme --namespace ofme > /tmp/ofme.yaml
helm upgrade --install ofme deploy/helm/ofme --namespace ofme \
  --set image.api.tag=1.0.0 \
  --set image.frontend.tag=1.0.0 \
  --set ingress.hosts[0].host=ofme.example.com
```

| Template | Object |
|---|---|
| `api.yaml` | API Deployment + Service (`http`, optional `grpc`) |
| `worker.yaml` | Celery worker Deployment |
| `beat.yaml` | Celery beat Deployment |
| `frontend.yaml` | SPA Deployment + Service |
| `configmap.yaml` | non-secret environment |
| `secret.yaml` | renders only when `secrets.create=true`; prefer an existing secret |
| `pki-secret.yaml` | renders only when `pki.create=true`; prefer an existing secret |
| `ingress.yaml` | host/path/TLS routing |
| `hpa.yaml` | API/worker autoscaling |
| `pdb.yaml` | disruption budgets |
| `serviceaccount.yaml` | ServiceAccount |

Key values (defaults in `values.yaml`):

| Value | Default | Notes |
|---|---|---|
| `image.api.repository` / `image.api.tag` | `ghcr.io/ofme/ofme-api` / `1.0.0` | same image for worker and beat |
| `image.frontend.tag` | `1.0.0` | version independently, deploy together |
| `api.replicaCount` / `api.autoscaling.maxReplicas` | 2 / 12 | keep one uvicorn worker each |
| `worker.replicaCount` / `worker.concurrency` | 2 / 4 | all tasks on the `ofme` queue |
| `beat.replicaCount` | 1 | never > 1 |
| `secrets.existingSecret` | `ofme-secrets` | must contain the keys listed in `values.yaml` |
| `pki.existingSecret` | `ofme-pki` | `ca.crt` + `ca.key` |
| `ingress.hosts[0].host` | `ofme.example.com` | update `config.ALLOWED_HOSTS` and `config.CORS_ORIGINS` too |
| `grpc.enabled` | `false` | also set `config.GRPC_ENABLED=true`; requires `config.GRPC_SERVICE_TOKEN` |
| `podSecurityContext` / `securityContext` | UID 10001, non-root, read-only rootfs | do not relax without a reason |

The chart does not create the namespace, the application secret or the PKI
secret. `NOTES.txt` prints the post-install checks.

## `deploy/argocd` — GitOps

| File | Contents |
|---|---|
| `project.yaml` | `AppProject ofme`: allowed repos, destinations, RBAC roles |
| `application-staging.yaml` | tracks `develop`, 1 replica each, staging host |
| `application.yaml` | tracks `main`, image tags `1.0.0`, production host, TLS |
| `kustomization.yaml` | applies project + both applications |

```bash
kubectl apply -f deploy/argocd/project.yaml
kubectl apply -f deploy/argocd/application-staging.yaml
kubectl apply -f deploy/argocd/application.yaml
```

Before applying, change `source.repoURL`, the hostnames, the TLS secret and the
`config.*` values in both Applications. They point at
`https://github.com/ofme/ofme.git` and `ofme.example.com` as placeholders.

Both Applications use `automated: {prune: true, selfHeal: true}` and ignore
`/spec/replicas` so the HPA owns replica counts.

Promotion:

```text
develop ──► staging Application (auto-sync)
   │
   └─ tag 1.1.0 ──► bump image.*.tag in the production Application (commit)
                     └─► production Application syncs ──► verify ──► done
```

Rollback: `argocd app rollback ofme-production <revision>` or revert the tag
commit. Schema rollback is a database restore, not a Helm rollback (see
DEPLOYMENT.md §7).

## Secrets that must exist before the first sync

| Secret | Keys | Created by |
|---|---|---|
| `ofme-secrets` | `SECRET_KEY`, `DATABASE_URL`, `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`, `S3_ENDPOINT`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, optional `BOOTSTRAP_ADMIN_PASSWORD` | platform team / Vault |
| `ofme-pki` | `ca.crt`, `ca.key` | `backend/scripts/init_pki.py` |

```bash
cd backend
python scripts/init_pki.py --kubectl-secret --namespace ofme | kubectl apply -f -
```

Never commit either secret. The chart can render them from values
(`secrets.create`, `pki.create`), which exists for labs only; a real installation
uses an external secret store.

## Verification after any sync

```bash
kubectl -n ofme rollout status deploy/ofme-api
kubectl -n ofme rollout status deploy/ofme-worker
kubectl -n ofme rollout status deploy/ofme-frontend
kubectl -n ofme port-forward svc/ofme-api 8000:8000 &
curl -fsS http://127.0.0.1:8000/api/v1/health/ready | jq
curl -fsS -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8000/api/v1/audit/integrity | jq
```

`/health/ready` returns 503 with per-component detail when PostgreSQL, Redis, S3
or the PKI is unavailable. A pod that serves `/health/live` but fails
`/health/ready` is running with a broken dependency, not a healthy deployment.

## What is deliberately not here

* **The OPNsense plugin package** — built from `plugin/os-fleet-agent` with a
  FreeBSD ports tree (`make package`), not by these manifests.
* **Database/Redis/S3 operators** — use your platform's managed services or
  operators; `deploy/k8s/datastores.yaml` is a lab baseline.
* **Monitoring stack** — Prometheus, Grafana, Loki and the OTel collector live in
  `monitoring/` and are deployed with the Compose stack or your own observability
  platform. Point Prometheus at `ofme-api:8000/metrics` in the `ofme` namespace.
* **Backup and DR automation** — the platform backs up device configurations;
  backing up PostgreSQL is an operator responsibility (see DEPLOYMENT.md §8).
* **The ingress controller and cert-manager** — assumed to exist. The manifests
  reference `ingressClassName: nginx` and `cert-manager.io/cluster-issuer`.

## Related documents

* [../docs/DEPLOYMENT.md](../docs/DEPLOYMENT.md) — compose, environment reference,
  PKI, migrations, upgrades, disaster recovery, sizing, air-gapped installs.
* [../docs/OPERATIONS.md](../docs/OPERATIONS.md) — health endpoints, alerts,
  runbooks, scheduled work.
* [../docs/SECURITY.md](../docs/SECURITY.md) — trust boundaries, ingress mTLS,
  hardening checklist.
* [k8s/README.md](k8s/README.md) — step-by-step for the raw manifests.
