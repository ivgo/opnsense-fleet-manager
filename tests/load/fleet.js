// Fleet read load: the dashboard and inventory queries a large tenant hits.
//
//   k6 run -e BASE_URL=http://localhost:8000 -e PASSWORD=... \
//          -e VUS=200 -e DURATION=5m tests/load/fleet.js
//
// This is the test used to size a deployment: it should sustain 200 virtual
// users on a 10 000-device tenant without an API pod above 70% CPU.

import { check, sleep } from 'k6';
import http from 'k6/http';
import { Rate, Trend } from 'k6/metrics';
import {
  API,
  authHeaders,
  dashboardDuration,
  deviceListDuration,
  expectStatus,
  get,
  login,
} from './lib/common.js';

const searchDuration = new Trend('ofme_device_search_duration', true);
const auditDuration = new Trend('ofme_audit_list_duration', true);
const unexpected = new Rate('ofme_unexpected_status');

export const options = {
  scenarios: {
    fleet: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '1m', target: Number(__ENV.VUS || 50) },
        { duration: __ENV.DURATION || '5m', target: Number(__ENV.VUS || 50) },
        { duration: '1m', target: 0 },
      ],
      gracefulRampDown: '30s',
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    checks: ['rate>0.99'],
    ofme_business_errors: ['rate<0.01'],
    ofme_unexpected_status: ['rate<0.01'],
    ofme_device_list_duration: ['p(95)<500', 'p(99)<1500'],
    ofme_dashboard_duration: ['p(95)<900'],
    ofme_device_search_duration: ['p(95)<700'],
    ofme_audit_list_duration: ['p(95)<700'],
  },
  tags: { testid: 'fleet' },
};

const PAGE_SIZE = Number(__ENV.PAGE_SIZE || 50);

export function setup() {
  return { token: login() };
}

function record(trend, response) {
  trend.add(response.timings.duration);
  unexpected.add(response.status >= 500);
  return response;
}

export default function (data) {
  const token = data.token;

  // Every iteration performs one dashboard read and two paginated lists, the
  // same ratio the console produces while an operator watches the fleet.
  const dashboard = record(
    dashboardDuration,
    get('/metrics/dashboard?trend_hours=24&health_limit=100', token, { endpoint: 'metrics.dashboard' }),
  );
  expectStatus(dashboard, 200, 'metrics.dashboard');
  check(dashboard, {
    'dashboard carries the fleet summary': (r) => r.status === 200 && Boolean(r.json('summary')),
  });

  const page = 1 + Math.floor(Math.random() * 5);
  const list = record(
    deviceListDuration,
    get(`/devices?page=${page}&size=${PAGE_SIZE}`, token, { endpoint: 'devices.list' }),
  );
  expectStatus(list, 200, 'devices.list');
  check(list, {
    'device list is paginated': (r) => r.status === 200 && Boolean(r.json('meta')),
    'device page is not larger than requested': (r) =>
      r.status !== 200 || (r.json('items') || []).length <= PAGE_SIZE,
  });

  const summary = record(deviceListDuration, get('/devices/summary', token, { endpoint: 'devices.summary' }));
  expectStatus(summary, 200, 'devices.summary');

  if (__ITER % 5 === 0) {
    const search = record(
      searchDuration,
      get(`/devices/search?q=fw&limit=${Math.min(PAGE_SIZE, 100)}`, token, { endpoint: 'devices.search' }),
    );
    expectStatus(search, 200, 'devices.search');
  }

  if (__ITER % 10 === 0) {
    const audit = record(
      auditDuration,
      get(`/audit?page=1&size=${PAGE_SIZE}`, token, { endpoint: 'audit.list' }),
    );
    expectStatus(audit, 200, 'audit.list');
  }

  if (__ITER % 20 === 0) {
    const health = http.get(`${API}/metrics/health?limit=${PAGE_SIZE}`, {
      headers: authHeaders(token),
      tags: { endpoint: 'metrics.health' },
    });
    check(health, { 'metrics.health answers': (r) => r.status === 200 || r.status === 422 });
  }

  sleep(Number(__ENV.SLEEP || 0.5));
}
