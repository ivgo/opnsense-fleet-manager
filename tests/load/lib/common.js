// Shared helpers for the k6 load tests.
//
// Every test authenticates with either an API key (`API_KEY`) or a
// username/password pair (`USERNAME` / `PASSWORD`). API keys are strongly
// preferred for load testing: they are not rate limited by the login lockout
// counter and they cannot trigger an MFA challenge.

import http from 'k6/http';
import { check, fail } from 'k6';
import { Trend, Rate } from 'k6/metrics';

export const BASE_URL = (__ENV.BASE_URL || 'http://localhost:8000').replace(/\/+$/, '');
export const API = `${BASE_URL}/api/v1`;
export const API_KEY = __ENV.API_KEY || '';
export const USERNAME = __ENV.USERNAME || 'admin@ofme.example.com';
export const PASSWORD = __ENV.PASSWORD || '';
export const TENANT_SLUG = __ENV.TENANT || '';
export const TENANT_ID = __ENV.TENANT_ID || '';

export const loginDuration = new Trend('ofme_login_duration', true);
export const deviceListDuration = new Trend('ofme_device_list_duration', true);
export const dashboardDuration = new Trend('ofme_dashboard_duration', true);
export const businessErrors = new Rate('ofme_business_errors');

export function jsonHeaders(extra = {}) {
  return Object.assign({ 'Content-Type': 'application/json', Accept: 'application/json' }, extra);
}

export function authHeaders(token) {
  const headers = jsonHeaders();
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  if (TENANT_ID) {
    headers['X-Tenant-Id'] = TENANT_ID;
  }
  return headers;
}

export function login() {
  if (API_KEY) {
    return API_KEY;
  }
  if (!PASSWORD) {
    fail('set API_KEY or PASSWORD');
  }

  const payload = { username: USERNAME, password: PASSWORD };
  if (TENANT_SLUG) {
    payload.tenant = TENANT_SLUG;
  }

  const response = http.post(`${API}/auth/login`, JSON.stringify(payload), {
    headers: jsonHeaders(),
    tags: { endpoint: 'auth.login' },
  });
  loginDuration.add(response.timings.duration);

  const ok = check(response, {
    'login returns 200': (r) => r.status === 200,
    'login returns an access token': (r) => {
      if (r.status !== 200) {
        return false;
      }
      try {
        return Boolean(r.json('access_token'));
      } catch (error) {
        return false;
      }
    },
  });
  if (!ok) {
    fail(`login failed: HTTP ${response.status} ${String(response.body).slice(0, 200)}`);
  }
  return response.json('access_token');
}

export function get(path, token, tags = {}) {
  return http.get(`${API}${path}`, { headers: authHeaders(token), tags });
}

export function expectStatus(response, expected, label) {
  const ok = check(response, {
    [`${label} returns ${expected}`]: (r) => r.status === expected,
    [`${label} body is JSON`]: (r) => {
      if (!r.headers['Content-Type']) {
        return false;
      }
      return String(r.headers['Content-Type']).includes('application/json');
    },
  });
  businessErrors.add(!ok);
  return ok;
}
