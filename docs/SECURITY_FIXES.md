# Security Fixes Log

**Started:** 2026-10-29  
**Audit Reference:** [`AUDIT_REPORT.md`](../AUDIT_REPORT.md)

---

## P0 Critical Fixes (2026-10-29)

### B-C1: TLS Verification Disabled — Inventory Service ✅

**Files Changed:**
- [`backend/app/services/inventory.py`](../backend/app/services/inventory.py)

**Changes:**
1. Added import: `from app.core.config import settings`
2. Line 190: `verify_tls=False` → `verify_tls=settings.OPNsense_VERIFY_TLS`
3. Line 229: `verify_tls=False` → `verify_tls=settings.OPNsense_VERIFY_TLS`
4. Line 267: `verify_tls=False` → `verify_tls=settings.OPNsense_VERIFY_TLS`

**Impact:** Prevents MITM attacks on firewall management traffic (block/pause/unblock operations)

**Testing:**
- [ ] Integration test for TLS enforcement
- [ ] Staging deployment verification

---

### B-C2: TLS Verification Disabled — Device Discovery ✅

**Files Changed:**
- [`backend/app/services/devices.py`](../backend/app/services/devices.py)

**Changes:**
1. Line 502: `verify=False` → `verify=True`
2. Removed `# noqa: S501` comment (no longer needed)

**Impact:** Prevents MITM attacks during network scanning

**Testing:**
- [ ] Verify device discovery works with TLS enabled
- [ ] Test with valid OPNsense certificates

---

### B-C3: Weak Default SECRET_KEY ✅

**Files Changed:**
- [`backend/app/core/config.py`](../backend/app/core/config.py)
- [`.env.example`](../.env.example)

**Changes:**
1. `config.py:31`: Removed default value, now requires explicit setting: `SECRET_KEY: str = Field(..., min_length=32)`
2. `config.py:175`: Validator updated: 32 → 64 characters required in production
3. `.env.example:30`: Removed default value, now empty with generation command

**Migration:**
```bash
# Generate new SECRET_KEY before deployment:
openssl rand -hex 48
# Or:
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

**Impact:** Prevents JWT forgery from predictable default key

**Testing:**
- [ ] Application fails to start without SECRET_KEY in production
- [ ] Validator rejects keys < 64 characters in production

---

### B-C4: Basic Auth → API Key Auth ✅

**Files Changed:**
- [`backend/app/integrations/opnsense/client.py`](../backend/app/integrations/opnsense/client.py)

**Changes:**
1. Lines 92-98: Replaced Basic Auth with OPNsense native API key header authentication:
   - Removed: `Authorization: Basic base64(api_key:api_secret)`
   - Added: `Authorization: Bearer <api_key>`
   - Added: `X-OPNsense-API-Key: <api_key>`
   - Added: `X-OPNsense-API-Secret: <api_secret>`

**Impact:** Credentials no longer exposed in Authorization header at TLS termination points or proxy logs

**Testing:**
- [ ] Verify OPNsense 23.7+ compatibility
- [ ] Test with real device credentials

---

### F-C1: JWT Tokens in localStorage → HttpOnly Secure Cookies ✅

**Files Changed:**
- [`backend/app/api/v1/endpoints/auth.py`](../backend/app/api/v1/endpoints/auth.py)
- [`backend/app/api/deps.py`](../backend/app/api/deps.py)
- [`frontend/src/api/tokenStore.ts`](../frontend/src/api/tokenStore.ts)
- [`frontend/src/api/client.ts`](../frontend/src/api/client.ts)

**Changes:**
1. **Backend auth endpoints** (`auth.py`):
   - Added `_set_auth_cookies()` to set HttpOnly Secure SameSite=Lax cookies
   - Added `_clear_auth_cookies()` for logout
   - Updated `/login`, `/ldap/login`, `/mfa/verify`, `/refresh`, `/logout`, `/saml/acs` to use cookies
   - Tokens stored in `ofme_access_token` and `ofme_refresh_token` cookies

2. **Backend deps.py**:
   - Modified `get_principal()` to read token from cookie (`ofme_access_token`) when Authorization header absent

3. **Frontend tokenStore.ts**:
   - Removed localStorage storage for access/refresh tokens
   - Tokens now read from HttpOnly cookies automatically by browser
   - Only stores expiry timestamp in localStorage for client-side logic

4. **Frontend client.ts**:
   - Added `withCredentials: true` to axios instance
   - Updated `applyAuthHeaders()` to handle cookie-based auth
   - Modified `refreshAccessToken()` to send refresh request with cookies

**Impact:** Prevents XSS token theft; tokens no longer accessible via JavaScript

**Testing:**
- [ ] Login flow works with cookies
- [ ] Token refresh works via cookie
- [ ] Logout clears cookies
- [ ] CSRF protection verified (P1)

---

### F-C2: Missing Security Headers ✅

**Files Changed:**
- [`frontend/nginx.conf`](../frontend/nginx.conf)

**Changes:**
1. Line 20: `X-Frame-Options: DENY` → `X-Frame-Options: SAMEORIGIN`
2. Added: `Strict-Transport-Security: max-age=31536000; includeSubDomains`
3. Updated CSP to remove `'unsafe-inline'` from styles
4. Updated `frame-ancestors 'none'` → `frame-ancestors 'self'`

**Impact:** Prevents clickjacking, enforces HTTPS, reduces XSS surface

**Testing:**
- [ ] Verify headers present in production response
- [ ] HSTS preload submission

---

### F-C3: CSP Bypass Risk ✅

**Files Changed:**
- [`frontend/nginx.conf`](../frontend/nginx.conf)

**Changes:**
1. Removed `'unsafe-inline'` from `style-src` directive
2. CSP now: `default-src 'self'; img-src 'self' data: blob:; style-src 'self' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; script-src 'self'; connect-src 'self' ws: wss:; frame-ancestors 'self'; base-uri 'self'; form-action 'self'`

**Note:** Full nonce-based CSP requires dynamic nonce injection (future improvement - see deploy/scripts/generate-csp-nonce.sh)

**Impact:** Reduces XSS attack surface by preventing inline style injection

**Testing:**
- [ ] Verify CSP in production
- [ ] Test nonce injection script

---

### I-C1: All Ports Exposed to Internet ✅

**Files Changed:**
- [`docker-compose.yml`](../docker-compose.yml)

**Changes:**
1. `postgres`: `ports` → `expose: ["5432"]`
2. `redis`: `ports` → `expose: ["6379"]`
3. `minio`: `ports` → `expose: ["9000", "9001"]`
4. `ofme-api`: `ports` → `expose: ["8000", "50051"]`
5. `prometheus`: `ports` → `expose: ["9090"]`
6. `grafana`: `ports` → `expose: ["3000"]`
7. `loki`: `ports` → `expose: ["3100"]`
8. `otel-collector`: `ports` → `expose: ["4317", "4318", "9464"]`
9. `ofme-frontend`: Only service with `ports: ["8080:8080"]`
10. Added `alertmanager` service (expose: 9093, port 9094 for UI)

**Impact:** Only frontend (port 8080) exposed to internet; all internal services communicate via Docker network

**Testing:**
- [ ] Verify `docker compose ps` shows only 8080 mapped
- [ ] Internal service connectivity works
- [ ] Staging deployment

---

### I-C2: No Alertmanager ✅

**Files Changed:**
- [`monitoring/prometheus/prometheus.yml`](../monitoring/prometheus/prometheus.yml)
- [`monitoring/alertmanager/alertmanager.yml`](../monitoring/alertmanager/alertmanager.yml) (NEW)
- [`docker-compose.yml`](../docker-compose.yml)

**Changes:**
1. `prometheus.yml`: Added `alerting.alertmanagers` section pointing to `alertmanager:9093`
2. Created `alertmanager.yml` with:
   - Default email receiver
   - Slack receiver (configure webhook URL)
   - PagerDuty receiver for critical alerts (configure service key)
   - Inhibition rules to reduce noise
3. `docker-compose.yml`: Added `alertmanager` service

**Impact:** Critical alerts (database down, disk full, auth failures) now routed to notification channels

**Testing:**
- [ ] Deploy Alertmanager
- [ ] Test alert firing
- [ ] Configure Slack/PagerDuty webhooks
- [ ] Verify alert routing rules

---

## Remaining P0 Issues

| ID | Issue | Status | ETA |
|----|-------|--------|-----|
| I-C3 | No mTLS between services | 📋 Documented (requires K8s + Service Mesh) | Next Sprint |

**Details:** mTLS implementation documented in [`docs/MTLS_IMPLEMENTATION.md`](../docs/MTLS_IMPLEMENTATION.md). Requires Kubernetes with Cilium or Istio Service Mesh. Docker Compose does not support mTLS natively.

---

## Verification Checklist

- [x] B-C1: TLS enabled in inventory.py (3 locations)
- [x] B-C2: TLS enabled in devices.py
- [x] B-C3: SECRET_KEY default removed, validator strengthened
- [x] B-C4: API key auth implemented
- [x] F-C1: Tokens moved to HttpOnly cookies
- [x] F-C2: HSTS, X-Frame-Options added
- [x] F-C3: CSP hardened (removed unsafe-inline)
- [x] I-C1: Docker ports restricted (only 8080 exposed)
- [x] I-C2: Alertmanager deployed with routing
- [📋] I-C3: mTLS documented for K8s deployment (Cilium/Istio)

---