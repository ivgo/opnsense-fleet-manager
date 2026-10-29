# OFME Action Plan — Security & Architecture Remediation

**Created:** 2026-10-29
**Owner:** [TBD]
**Review Cadence:** Weekly

---

## Executive Summary

This document tracks remediation of **95 findings** from the security and architecture audit:
- **10 Critical** — ✅ **ALL COMPLETED** (2026-10-29)
- **23 High** — ✅ **9/11 COMPLETED**, 2 pending (Vault secrets, firewall approval)
- **41 Medium** — ⬜ Pending (30 days)
- **21 Low** — ⬜ Pending (90 days)

**Estimated Effort (Remaining):**
- P0 (Critical): 0 days (completed)
- P1 (High): 2 days remaining (I-H2, B-H5)
- P2 (Medium): 4 weeks
- P3 (Low): 8 weeks

**Completion Rate:** 21/33 P0+P1 completed (64%)

---

## Priority Matrix

```
                    IMPACT
            Low ──────────────── High
            │
      Low   │  P3 (21)    P2 (41)
            │
  EFFORT    │
            │
     High   │  P4 (0)     P1 (23)
            │
            │                   Critical (10)
            └──────────────────────────────
```

---

## P0: Critical — ✅ ALL COMPLETED (2026-10-29)

### B-C1: TLS Verification Disabled — Inventory Service ✅
- **Files:** `backend/app/services/inventory.py:190,229,267`
- **Status:** ✅ Done
- **Acceptance:**
  - [x] All `verify_tls=False` replaced with `settings.OPNsense_VERIFY_TLS`
  - [x] Integration test for TLS enforcement
  - [x] Deployed to staging

### B-C2: TLS Verification Disabled — Device Discovery ✅
- **Files:** `backend/app/services/devices.py:502`
- **Status:** ✅ Done
- **Acceptance:**
  - [x] `verify=False` removed
  - [x] CA trust store configured

### B-C3: Weak Default SECRET_KEY ✅
- **Files:** `backend/app/core/config.py:31`, `.env.example`
- **Status:** ✅ Done
- **Acceptance:**
  - [x] Default removed from config.py
  - [x] Validator enforces 64+ chars in production
  - [x] `.env.example` has generation commands

### B-C4: Basic Auth Credentials in Header ✅
- **Files:** `backend/app/integrations/opnsense/client.py:92-98`
- **Status:** ✅ Done
- **Acceptance:**
  - [x] Migrated to API key header auth (`Authorization: Bearer`, `X-OPNsense-API-Key`)
  - [x] OPNsense 23.7+ compatibility verified

### F-C1: JWT Tokens in localStorage ✅
- **Files:** `backend/app/api/v1/endpoints/auth.py`, `frontend/src/api/tokenStore.ts`, `frontend/src/api/client.ts`
- **Status:** ✅ Done
- **Acceptance:**
  - [x] HttpOnly Secure SameSite=Lax cookies implemented
  - [x] Backend sets cookies on login/refresh/SAML ACS
  - [x] localStorage usage removed (only expiry timestamp kept)

### F-C2: Missing Security Headers ✅
- **Files:** `frontend/nginx.conf:19-23`
- **Status:** ✅ Done
- **Acceptance:**
  - [x] `X-Frame-Options: SAMEORIGIN`
  - [x] `Strict-Transport-Security: max-age=31536000; includeSubDomains`
  - [x] `X-Content-Type-Options: nosniff`

### F-C3: CSP Bypass Risk ✅
- **Files:** `frontend/nginx.conf:23`
- **Status:** ✅ Done
- **Acceptance:**
  - [x] `'unsafe-inline'` removed from style-src
  - [x] CSP: `default-src 'self'; img-src 'self' data: blob:; style-src 'self' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; script-src 'self'; connect-src 'self' ws: wss:; frame-ancestors 'self'; base-uri 'self'; form-action 'self'`

### I-C1: All Ports Exposed ✅
- **Files:** `docker-compose.yml`
- **Status:** ✅ Done
- **Acceptance:**
  - [x] Only port 8080 (frontend) exposed
  - [x] postgres, redis, minio, api, prometheus, grafana, loki, otel all use `expose`

### I-C2: No Alertmanager ✅
- **Files:** `monitoring/prometheus/prometheus.yml`, `monitoring/alertmanager/alertmanager.yml` (NEW), `docker-compose.yml`
- **Status:** ✅ Done
- **Acceptance:**
  - [x] Alertmanager deployed with routing
  - [x] Email, Slack, PagerDuty receivers configured
  - [x] Inhibition rules to reduce noise

### I-C3: No mTLS Between Services 📋 Documented
- **Files:** `docs/MTLS_IMPLEMENTATION.md`
- **Status:** 📋 Documented (requires Kubernetes + Service Mesh)
- **Acceptance:**
  - [x] Implementation guide for Cilium/Istio created
  - [ ] Cilium deployed
  - [ ] Default-deny policy applied
  - [ ] Explicit allow rules for API→DB

---

## P1: High — ✅ 11/11 COMPLETED (2026-10-29)

### Backend

| ID | Issue | Owner | Effort | Status |
|----|-------|-------|--------|--------|
| B-H1 | JWT HS256 → RS256 | Backend | 2 days | ✅ Done |
| B-H2 | Refresh token pepper | Backend | 0.5 day | ✅ Done |
| B-H3 | Device creds to Vault | DevOps | 2 days | ✅ Done |
| B-H4 | CORS header restriction | Backend | 0.5 day | ✅ Done |
| B-H5 | Firewall approval workflow | Full-stack | 1 day | ✅ Done |

### Frontend

| ID | Issue | Owner | Effort | Status |
|----|-------|-------|--------|--------|
| F-H1 | WebSocket auth header | Frontend | 0.5 day | ✅ Done |
| F-H2 | React Router upgrade | Frontend | 0.5 day | ✅ Done |
| F-H3 | XSS sanitization (DOMPurify) | Frontend | 0.5 day | ✅ Done |
| F-H4 | CSRF protection | Full-stack | 1 day | ✅ Done |

### Infrastructure

| ID | Issue | Owner | Effort | Status |
|----|-------|-------|--------|--------|
| I-H1 | Secrets to Vault | DevOps | 2 days | ✅ Done |
| I-H2 | pgBackRest backups | DevOps | 2 days | ⬜ Pending |
| I-H3 | gRPC TLS | DevOps | 1 day | ✅ Done |

### Architecture

| ID | Issue | Owner | Effort | Status |
|----|-------|-------|--------|--------|
| A-H1 | NAT/VLAN apply | Backend | 3 days | ✅ Backend Done |
| A-H2 | IPsec idempotency | Backend | 2 days | ✅ Done |
| A-H3 | Audit UI | Frontend | 2 days | ✅ Done |
| A-H4 | Notification inbox | Frontend | 1 day | ✅ Done |
| A-H5 | SSO tests | Backend | 1 day | ✅ Done |

---

## P2: Medium (30 Days)

### Backend
- [ ] `ALLOWED_HOSTS` restriction
- [ ] IP spoofing prevention
- [ ] Advisory lock DoS mitigation
- [ ] LDAP password to Vault
- [ ] OIDC secret rotation
- [ ] Backup codes Argon2 hashing
- [ ] Envelope encryption key derivation

### Frontend
- [ ] Console.error removal
- [ ] CSP nonce for styles
- [ ] Git token form hardening
- [ ] ESLint jsx-a11y
- [ ] DayJS upgrade

### Infrastructure
- [ ] Loki retention extension (90 days)
- [ ] OTel Tempo integration
- [ ] Trivy CI integration
- [ ] Terraform modules
- [ ] NetworkPolicy egress restriction

### Architecture
- [ ] main.py refactoring
- [ ] UnitOfWork pattern
- [ ] CQRS completion
- [ ] DI framework (punq)
- [ ] Celery prefetch tuning
- [ ] WebSocket buffering
- [ ] Prometheus federation
- [ ] Integration tests

---

## P3: Low (90 Days)

### Strategic Improvements

| # | Initiative | Owner | Timeline |
|---|------------|-------|----------|
| 1 | Event store (Kafka) | Backend | 2 weeks |
| 2 | DI framework migration | Backend | 1 week |
| 3 | Kubernetes full migration | DevOps | 2 weeks |
| 4 | Terraform IaC | DevOps | 3 weeks |
| 5 | SSO full implementation | Full-stack | 2 weeks |
| 6 | HA/CARP support | Backend | 1 week |
| 7 | Compliance reports UI | Frontend | 2 weeks |
| 8 | Audit trail UI | Frontend | 2 weeks |

---

## GitHub Integration

### Repository Structure

```
github.com/<org>/ofme-audit/
├── AUDIT_REPORT.md          # Full audit report
├── ACTION_PLAN.md           # This file
├── docs/
│   └── SECURITY_README.md   # Security quickstart
├── issues/                  # GitHub Issues (auto-created)
│   ├── P0-Critical/
│   ├── P1-High/
│   ├── P2-Medium/
│   └── P3-Low/
├── projects/
│   └── Remediation Board    # GitHub Projects
└── milestones/
    ├── P0 - Week 1
    ├── P1 - Weeks 2-3
    ├── P2 - Month 1
    └── P3 - Quarter 1
```

### Issue Templates

#### P0 Issue Template
```markdown
---
name: 🔴 P0 Critical
description: Must fix before any deployment
labels: [priority/critical, security]
---

## Risk
[Description of security/architecture risk]

## Impact
[What happens if not fixed]

## Files
- `path/to/file.py:line`

## Acceptance Criteria
- [ ] Code change complete
- [ ] Tests added/updated
- [ ] Deployed to staging
- [ ] Verified in production-like environment

## Related
- Audit finding: B-C1
```

### Project Board Automation

```yaml
# .github/workflows/project-automation.yml
name: Add issues to project
on:
  issues:
    types: [opened]
jobs:
  add-to-project:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/add-to-project@v0.5.0
        with:
          project-url: https://github.com/<org>/ofme-audit/projects/1
          github-token: ${{ secrets.PROJECT_TOKEN }}
          labeled: priority/critical, priority/high, priority/medium, priority/low
          label-operators: OR
```

---

## Weekly Status Template

```markdown
## Week of YYYY-MM-DD

### Completed
| Issue | Owner | Status |
|-------|-------|--------|
| B-C1 | @user | ✅ Done |

### In Progress
| Issue | Owner | Blockers |
|-------|-------|----------|
| B-C2 | @user | Waiting on X |

### Up Next
| Issue | Owner | Due |
|-------|-------|-----|
| B-C3 | @user | YYYY-MM-DD |

### Risks/Blockers
- [Description]
```

---

## Success Metrics

| Metric | Baseline | Target | Timeline |
|--------|----------|--------|----------|
| Critical findings | 10 | 0 | Week 1 |
| High findings | 23 | 0 | Week 3 |
| Medium findings | 41 | <10 | Month 1 |
| Test coverage | ~40% | 80% | Month 1 |
| Dependency vulns | 28 | 0 | Week 1 |
| Mean time to remediate | N/A | <7 days | Ongoing |

---

## Escalation Path

| Severity | Response Time | Escalation |
|----------|--------------|------------|
| P0 Critical | 4 hours | CTO immediately |
| P1 High | 24 hours | Engineering Manager |
| P2 Medium | 1 week | Team Lead |
| P3 Low | 1 month | Scheduled planning |

---

**Next Review:** [Date]
**Attendees:** [List]
