# mTLS Implementation Guide

**Status:** 📋 Planned (P0 - I-C3)  
**Target:** Kubernetes production deployment  
**Docker Compose:** Not applicable - requires Service Mesh

---

## Overview

Mutual TLS (mTLS) ensures all service-to-service communication is encrypted and authenticated. In the OFME architecture, this protects:

| Connection | Current | Target |
|------------|---------|--------|
| API → PostgreSQL | Plaintext | mTLS |
| API → Redis | Plaintext | mTLS |
| API → MinIO | Plaintext | mTLS |
| API → OPNsense | TLS (verify=True) | mTLS (optional) |
| Worker → Redis | Plaintext | mTLS |
| Worker → PostgreSQL | Plaintext | mTLS |
| Prometheus → API | Plaintext | mTLS |

---

## Option 1: Cilium (Recommended for Kubernetes)

### Prerequisites
- Kubernetes cluster with Cilium CNI
- Cilium version 1.14+

### Deployment

```yaml
# deploy/cilium/mtls-policy.yaml
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata:
  name: api-to-database
  namespace: ofme
spec:
  endpointSelector:
    matchLabels:
      app: ofme-api
  egress:
    - toEndpoints:
        - matchLabels:
            app: postgres
      toPorts:
        - ports:
            - port: "5432"
              protocol: TCP
        rules:
          http:
            - method: "POST"
              path: "/.*"
---
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata:
  name: api-to-redis
  namespace: ofme
spec:
  endpointSelector:
    matchLabels:
      app: ofme-api
  egress:
    - toEndpoints:
        - matchLabels:
            app: redis
      toPorts:
        - ports:
            - port: "6379"
              protocol: TCP
---
apiVersion: cilium.io/v2alpha1
kind: CiliumClusterwideNetworkPolicy
metadata:
  name: default-deny-all
spec:
  description: "Default deny all ingress/egress - explicit allow required"
  endpointSelector: {}
  ingress:
    - fromEndpoints:
        - matchLabels: {}
  egress:
    - toEndpoints:
        - matchLabels: {}
---
apiVersion: cilium.io/v2alpha1
kind: CiliumClusterwideNetworkPolicy
metadata:
  name: enable-mtls
spec:
  description: "Enable mTLS for all mesh pods"
  nodeSelector: {}
  ingress:
    - fromRequires:
        - kind: "K8sIdentity"
  egress:
    - toRequires:
        - kind: "K8sIdentity"
```

### Enable mTLS in Cilium ConfigMap

```yaml
# cilium-config
enable-mtls: "true"
encrypt-node: "true"
```

---

## Option 2: Istio Service Mesh

### Prerequisites
- Istio 1.20+ installed
- Sidecar injection enabled for namespace

### PeerAuthentication (Strict mTLS)

```yaml
# deploy/istio/peer-authentication.yaml
apiVersion: security.istio.io/v1beta1
kind: PeerAuthentication
metadata:
  name: default
  namespace: ofme
spec:
  mtls:
    mode: STRICT
```

### DestinationRules for mTLS

```yaml
# deploy/istio/destination-rules.yaml
apiVersion: networking.istio.io/v1beta1
kind: DestinationRule
metadata:
  name: postgres-mtls
  namespace: ofme
spec:
  host: postgres.ofme.svc.cluster.local
  trafficPolicy:
    tls:
      mode: ISTIO_MUTUAL
---
apiVersion: networking.istio.io/v1beta1
kind: DestinationRule
metadata:
  name: redis-mtls
  namespace: ofme
spec:
  host: redis.ofme.svc.cluster.local
  trafficPolicy:
    tls:
      mode: ISTIO_MUTUAL
---
apiVersion: networking.istio.io/v1beta1
kind: DestinationRule
metadata:
  name: minio-mtls
  namespace: ofme
spec:
  host: minio.ofme.svc.cluster.local
  trafficPolicy:
    tls:
      mode: ISTIO_MUTUAL
```

---

## Option 3: Application-Level mTLS (Alternative)

If Service Mesh is not available, implement at application level:

### PostgreSQL (asyncpg)

```python
# backend/app/db/session.py - modification needed
import ssl

# Create SSL context for PostgreSQL
ssl_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
ssl_context.load_verify_locations("/etc/ofme/pki/ca.crt")
ssl_context.load_cert_chain("/etc/ofme/pki/client.crt", "/etc/ofme/pki/client.key")

# In engine creation:
engine = create_async_engine(
    DATABASE_URL,
    connect_args={"ssl": ssl_context} if settings.ENVIRONMENT == "production" else {}
)
```

### Redis (redis-py)

```python
# backend/app/core/redis.py
import ssl

redis_ssl_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
redis_ssl_context.load_verify_locations("/etc/ofme/pki/ca.crt")
redis_ssl_context.load_cert_chain("/etc/ofme/pki/client.crt", "/etc/ofme/pki/client.key")

redis_client = redis.from_url(
    REDIS_URL,
    ssl_cert_reqs="required",
    ssl_ca_certs="/etc/ofme/pki/ca.crt",
    ssl_certfile="/etc/ofme/pki/client.crt",
    ssl_keyfile="/etc/ofme/pki/client.key",
)
```

### MinIO (boto3)

```python
# backend/app/integrations/s3.py
import boto3
from botocore.config import Config

s3_client = boto3.client(
    "s3",
    endpoint_url=S3_ENDPOINT,
    verify="/etc/ofme/pki/ca.crt",
    config=Config(
        retries={"max_attempts": 3},
        connect_timeout=5,
    ),
    # For mutual TLS, MinIO must be configured with client certs
)
```

---

## Certificate Management

### Generate mTLS Certificates

```bash
#!/bin/bash
# deploy/scripts/generate-mtls-certs.sh

set -e

CA_DIR="/etc/ofme/pki"
mkdir -p $CA_DIR

# Generate CA
openssl req -x509 -newkey rsa:4096 -sha256 -days 3650 \
  -nodes -keyout $CA_DIR/ca.key -out $CA_DIR/ca.crt \
  -subj "/CN=OFME Root CA"

# Generate server certs for each service
for SERVICE in postgres redis minio api worker beat; do
  openssl req -newkey rsa:2048 -nodes -keyout $CA_DIR/${SERVICE}.key -out $CA_DIR/${SERVICE}.csr \
    -subj "/CN=${SERVICE}.ofme.svc.cluster.local"

  openssl x509 -req -in $CA_DIR/${SERVICE}.csr -CA $CA_DIR/ca.crt -CAkey $CA_DIR/ca.key \
    -CAcreateserial -out $CA_DIR/${SERVICE}.crt -days 365 -sha256 \
    -extfile <(echo "subjectAltName=DNS:${SERVICE}.ofme.svc.cluster.local,DNS:localhost,IP:127.0.0.1")
done

# Generate client cert for API
openssl req -newkey rsa:2048 -nodes -keyout $CA_DIR/client.key -out $CA_DIR/client.csr \
  -subj "/CN=ofme-api-client"

openssl x509 -req -in $CA_DIR/client.csr -CA $CA_DIR/ca.crt -CAkey $CA_DIR/ca.key \
  -CAcreateserial -out $CA_DIR/client.crt -days 365 -sha256 \
  -extfile <(echo "extendedKeyUsage=clientAuth")
```

---

## Kubernetes Secrets for Certificates

```yaml
# deploy/k8s/secrets/mtls-certs.yaml
apiVersion: v1
kind: Secret
metadata:
  name: mtls-certs
  namespace: ofme
type: Opaque
stringData:
  ca.crt: |
    # base64 encoded CA cert
  api.crt: |
    # base64 encoded API cert
  api.key: |
    # base64 encoded API key
  postgres.crt: |
    # base64 encoded PostgreSQL cert
  postgres.key: |
    # base64 encoded PostgreSQL key
  redis.crt: |
    # base64 encoded Redis cert
  redis.key: |
    # base64 encoded Redis key
  minio.crt: |
    # base64 encoded MinIO cert
  minio.key: |
    # base64 encoded MinIO key
```

---

## Integration with Helm Chart

```yaml
# deploy/helm/ofme/values.yaml
global:
  mtls:
    enabled: true
    provider: cilium  # or istio

postgresql:
  tls:
    enabled: true
    caSecret: mtls-certs
    serverCertSecret: mtls-certs
    clientCertSecret: mtls-certs

redis:
  tls:
    enabled: true
    caSecret: mtls-certs
    serverCertSecret: mtls-certs

minio:
  tls:
    enabled: true
    caSecret: mtls-certs
    serverCertSecret: mtls-certs

api:
  tls:
    enabled: true
    caSecret: mtls-certs
    clientCertSecret: mtls-certs
```

---

## Testing mTLS

### Verify Cilium mTLS

```bash
# Check policy enforcement
cilium policy get

# Check encryption status
cilium bpf ipsec list

# Test connectivity
kubectl exec -it deployment/ofme-api -- openssl s_client -connect postgres:5432 -CAfile /etc/ofme/pki/ca.crt
```

### Verify Istio mTLS

```bash
# Check peer authentication
istioctl authn tls-check deployment/ofme-api.ofme

# Verify mTLS in Kiali
istioctl dashboard kiali
```

---

## Docker Compose Limitation

**Docker Compose does not support mTLS natively.** For local development:

1. **Option A:** Use `mkcert` for local TLS (not mTLS)
2. **Option B:** Run local Kubernetes (kind/k3d) with Cilium
3. **Option C:** Accept plaintext for local dev, enforce mTLS in CI/staging/prod

```yaml
# docker-compose.override.yml (local dev only)
services:
  postgres:
    environment:
      POSTGRES_SSL: "off"
  redis:
    command: ["redis-server", "--tls-port", "0"]
```

---

## Acceptance Criteria for I-C3

- [ ] Cilium/Istio deployed in staging cluster
- [ ] All service-to-service traffic encrypted with mTLS
- [ ] Network policies enforce default-deny
- [ ] Certificate rotation automated (cert-manager)
- [ ] mTLS verified in staging
- [ ] Documentation updated

---

## References

- [Cilium mTLS Documentation](https://docs.cilium.io/en/stable/security/encrypt/)
- [Istio mTLS Documentation](https://istio.io/latest/docs/tasks/security/mtls-migration/)
- [Kubernetes Network Policies](https://kubernetes.io/docs/concepts/services-networking/network-policies/)
- [cert-manager for Certificate Rotation](https://cert-manager.io/)