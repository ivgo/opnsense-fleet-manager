// Smoke test: a single virtual user walks the critical read paths once.
//
//   k6 run -e BASE_URL=http://localhost:8000 -e PASSWORD=... tests/load/smoke.js
//
// Fails fast when the deployment is not healthy, when authentication is broken
// or when the core read endpoints do not answer with JSON.

import { check, group, sleep } from 'k6';
import http from 'k6/http';
import { BASE_URL, API, get, login, authHeaders, expectStatus } from './lib/common.js';

export const options = {
  vus: 1,
  iterations: 1,
  thresholds: {
    checks: ['rate==1'],
    http_req_failed: ['rate==0'],
    http_req_duration: ['p(95)<1500'],
    ofme_business_errors: ['rate==0'],
  },
  tags: { testid: 'smoke' },
};

export default function () {
  group('health', () => {
    const live = http.get(`${API}/health/live`, { tags: { endpoint: 'health.live' } });
    expectStatus(live, 200, 'health.live');

    const ready = http.get(`${API}/health/ready`, { tags: { endpoint: 'health.ready' } });
    check(ready, {
      'health.ready responds': (r) => r.status === 200 || r.status === 503,
    });

    const version = http.get(`${API}/health/version`, { tags: { endpoint: 'health.version' } });
    expectStatus(version, 200, 'health.version');
  });

  const token = login();
  const headers = authHeaders(token);

  group('identity', () => {
    const me = http.get(`${API}/auth/me`, { headers, tags: { endpoint: 'auth.me' } });
    expectStatus(me, 200, 'auth.me');
  });

  group('inventory', () => {
    expectStatus(get('/devices?page=1&size=50', token, { endpoint: 'devices.list' }), 200, 'devices.list');
    expectStatus(get('/devices/summary', token, { endpoint: 'devices.summary' }), 200, 'devices.summary');
    expectStatus(get('/sites', token, { endpoint: 'sites.list' }), 200, 'sites.list');
    expectStatus(get('/groups', token, { endpoint: 'groups.list' }), 200, 'groups.list');
  });

  group('monitoring', () => {
    expectStatus(
      get('/metrics/dashboard?trend_hours=24', token, { endpoint: 'metrics.dashboard' }),
      200,
      'metrics.dashboard',
    );
    expectStatus(get('/metrics/summary', token, { endpoint: 'metrics.summary' }), 200, 'metrics.summary');
    expectStatus(get('/alerts', token, { endpoint: 'alerts.list' }), 200, 'alerts.list');
  });

  group('governance', () => {
    expectStatus(get('/audit?page=1&size=20', token, { endpoint: 'audit.list' }), 200, 'audit.list');
    expectStatus(
      get('/compliance/frameworks', token, { endpoint: 'compliance.frameworks' }),
      200,
      'compliance.frameworks',
    );
    expectStatus(get('/jobs?page=1&size=20', token, { endpoint: 'jobs.list' }), 200, 'jobs.list');
  });

  sleep(1);
}
