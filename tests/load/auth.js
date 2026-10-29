// Authentication load: password login, token refresh and rejected credentials.
//
//   k6 run -e BASE_URL=http://localhost:8000 -e PASSWORD=... tests/load/auth.js
//
// Purpose: prove that the login path (Argon2 verification, refresh-token
// rotation and the failed-login lockout counter) stays responsive. Run it
// against a staging tenant only - it writes refresh sessions and lockout
// counters.

import { check, fail } from 'k6';
import http from 'k6/http';
import { Trend } from 'k6/metrics';
import { API, PASSWORD, TENANT_SLUG, USERNAME, jsonHeaders, login } from './lib/common.js';

const refreshDuration = new Trend('ofme_refresh_duration', true);
const rejectedLoginDuration = new Trend('ofme_rejected_login_duration', true);

export const options = {
  scenarios: {
    login: {
      executor: 'constant-arrival-rate',
      exec: 'loginOnce',
      rate: Number(__ENV.RATE || 5),
      timeUnit: '1s',
      duration: __ENV.DURATION || '2m',
      preAllocatedVUs: 20,
      maxVUs: 100,
      tags: { scenario: 'login' },
    },
    refresh: {
      executor: 'constant-arrival-rate',
      exec: 'refreshOnce',
      rate: Number(__ENV.REFRESH_RATE || 2),
      timeUnit: '1s',
      startTime: '10s',
      duration: __ENV.DURATION || '2m',
      preAllocatedVUs: 10,
      maxVUs: 50,
      tags: { scenario: 'refresh' },
    },
    rejected: {
      executor: 'per-vu-iterations',
      exec: 'rejectedLogin',
      vus: 1,
      iterations: 5,
      startTime: '30s',
      maxDuration: '1m',
      tags: { scenario: 'rejected' },
    },
  },
  thresholds: {
    // Successful logins are dominated by the Argon2 work factor.
    'http_req_duration{expected_response:true}': ['p(95)<3000'],
    'ofme_login_duration': ['p(95)<3000'],
    'ofme_refresh_duration': ['p(95)<500'],
    checks: ['rate>0.98'],
    http_req_failed: ['rate<0.01'],
  },
  tags: { testid: 'auth' },
};

export function setup() {
  if (!PASSWORD) {
    fail('PASSWORD is required for the authentication load test');
  }
}

export function loginOnce() {
  const token = login();
  check(token, { 'access token is a non-empty string': (value) => typeof value === 'string' && value.length > 20 });
}

export function refreshOnce() {
  const payload = { username: USERNAME, password: PASSWORD };
  if (TENANT_SLUG) {
    payload.tenant = TENANT_SLUG;
  }
  const loginResponse = http.post(`${API}/auth/login`, JSON.stringify(payload), {
    headers: jsonHeaders(),
    tags: { endpoint: 'auth.login' },
  });
  if (loginResponse.status !== 200) {
    check(loginResponse, { 'refresh prerequisite login succeeds': () => false });
    return;
  }

  const refreshToken = loginResponse.json('refresh_token');
  const response = http.post(
    `${API}/auth/refresh`,
    JSON.stringify({ refresh_token: refreshToken }),
    { headers: jsonHeaders(), tags: { endpoint: 'auth.refresh' } },
  );
  refreshDuration.add(response.timings.duration);

  check(response, {
    'refresh returns 200': (r) => r.status === 200,
    'refresh rotates both tokens': (r) => r.status === 200 && Boolean(r.json('access_token')) && Boolean(r.json('refresh_token')),
  });
}

export function rejectedLogin() {
  // A dedicated, non-existent account: repeated failures must never lock the
  // account used by the successful-login scenario.
  const response = http.post(
    `${API}/auth/login`,
    JSON.stringify({
      username: __ENV.REJECTED_USERNAME || 'loadtest-no-such-user@example.com',
      password: 'definitely-not-the-password',
    }),
    { headers: jsonHeaders(), tags: { endpoint: 'auth.login.rejected' } },
  );
  rejectedLoginDuration.add(response.timings.duration);

  check(response, {
    'wrong password is rejected with 401': (r) => r.status === 401,
    'rejection does not leak token data': (r) => !String(r.body).includes('access_token'),
  });
}
