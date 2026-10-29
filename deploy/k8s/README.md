# Kubernetes deployment (raw manifests)

Self-contained manifests for a single-region installation. They are the
reference that the Helm chart mirrors; use the chart for anything that needs
per-environment values.

## Prerequisites

* Kubernetes 1.27+
* an ingress controller (`ingress-nginx`) and, optionally, cert-manager
* a default StorageClass
* `kubectl` 1.27+

## 1. Create the namespace and credentials

```bash
kubectl apply -f deploy/k8s/namespace.yaml

# Application secret (never commit this file)
kubectl -n ofme create secret generic ofme-secrets \
  --from-literal=SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')" \
  --from-literal=POSTGRES_PASSWORD="$(python -c 'import secrets; print(secrets.token_urlsafe(24))')" \
  --from-literal=DATABASE_URL="postgresql+asyncpg://ofme:$(python -c 'import secrets; print(secrets.token_urlsafe(24))')@ofme-postgres:5432/ofme" \
  --from-literal=REDIS_URL="redis://ofme-redis:6379/0" \
  --from-literal=CELERY_BROKER_URL="redis://ofme-redis:6379/1" \
  --from-literal=CELERY_RESULT_BACKEND="redis://ofme-redis:6379/2" \
  --from-literal=S3_ENDPOINT="http://ofme-minio:9000" \
  --from-literal=S3_ACCESS_KEY="ofme-minio" \
  --from-literal=S3_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(24))')" \
  --from-literal=BOOTSTRAP_ADMIN_PASSWORD="<one-time-password>"
```

Generate the CA **once** and store it as a secret (the API and every worker
mount the same material):

```bash
cd backend
python scripts/init_pki.py --output ../deploy/k8s/pki
kubectl -n ofme create secret generic ofme-pki \
  --from-file=ca.crt=../deploy/k8s/pki/ca.crt \
  --from-file=ca.key=../deploy/k8s/pki/ca.key
rm -rf ../deploy/k8s/pki
```

For a managed database/S3, replace `DATABASE_URL` and the `S3_*` values with the
provider endpoints. Delete `datastores.yaml` from `kustomization.yaml` in that
case.

## 2. Apply

```bash
kubectl apply -k deploy/k8s
kubectl -n ofme rollout status deploy/ofme-api
kubectl -n ofme rollout status deploy/ofme-worker
kubectl -n ofme get pods
```

`ofme-api` runs Alembic (`RUN_MIGRATIONS=true`) once per pod before serving; use
a separate migration Job and set `RUN_MIGRATIONS=false` when you scale beyond a
handful of replicas.

## 3. Point DNS and TLS at the ingress

Edit `deploy/k8s/ingress.yaml` (`host`, `cert-manager.io/cluster-issuer`,
`tls.secretName`) and apply it again.

## 4. Verify

```bash
kubectl -n ofme port-forward svc/ofme-api 8000:8000 &
curl -fsS http://127.0.0.1:8000/api/v1/health/ready | jq
curl -fsS http://127.0.0.1:8000/metrics | head
```

## Layout

| File | Contents |
|---|---|
| `namespace.yaml` | namespace with restricted Pod Security |
| `configmap.yaml` | non-secret runtime settings |
| `secret.example.yaml` | template for `ofme-secrets` and `ofme-pki` |
| `datastores.yaml` | PostgreSQL, Redis, MinIO and bucket bootstrap |
| `api.yaml` | API Deployment + Service |
| `worker.yaml` | Celery worker Deployment |
| `beat.yaml` | Celery beat Deployment + PVC |
| `frontend.yaml` | SPA Deployment + Service |
| `ingress.yaml` | TLS ingress for `/`, `/api`, `/ws` |
| `hpa.yaml` | horizontal autoscaling for API and workers |
| `pdb.yaml` | disruption budgets |
| `networkpolicy.yaml` | default-deny plus explicit allow rules |

## Notes

* The API and worker images are the same artifact; only the command differs.
* `ofme-api` and `ofme-frontend` service names are fixed because the SPA's nginx
  configuration proxies `/api` and `/ws` to `ofme-api:8000`.
* The PKI secret contains the CA private key. Use a KMS-backed secret store,
  restrict RBAC to the `ofme` namespace, and rotate the CA with a planned
  re-enrolment of every device.
