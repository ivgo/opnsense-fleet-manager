// Device lifecycle load: create, read, patch, search, command and delete.
//
//   k6 run -e BASE_URL=http://localhost:8000 -e PASSWORD=... tests/load/devices.js
//
// Each virtual user owns a uniquely named device and removes it again, so the
// test is repeatable and leaves no inventory behind. It exercises the write
// path (validation, audit entry, domain event, exclusive command queue) that
// the read-only tests do not touch.

import { check, fail, sleep } from 'k6';
import http from 'k6/http';
import { Trend } from 'k6/metrics';
import { API, authHeaders, expectStatus, get, login } from './lib/common.js';

const createDuration = new Trend('ofme_device_create_duration', true);
const patchDuration = new Trend('ofme_device_patch_duration', true);
const deleteDuration = new Trend('ofme_device_delete_duration', true);

export const options = {
  scenarios: {
    lifecycle: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '30s', target: Number(__ENV.VUS || 10) },
        { duration: __ENV.DURATION || '2m', target: Number(__ENV.VUS || 10) },
        { duration: '30s', target: 0 },
      ],
      gracefulRampDown: '30s',
    },
  },
  thresholds: {
    checks: ['rate>0.98'],
    http_req_failed: ['rate<0.02'],
    'http_req_duration{endpoint:devices.create}': ['p(95)<1200'],
    'http_req_duration{endpoint:devices.list}': ['p(95)<800'],
    ofme_business_errors: ['rate<0.02'],
  },
  tags: { testid: 'devices' },
};

export function setup() {
  return { token: login() };
}

export default function (data) {
  const token = data.token;
  const headers = authHeaders(token);
  const unique = `k6-${__VU}-${__ITER}-${Date.now()}`;

  // ------------------------------------------------------------------ create
  const created = http.post(
    `${API}/devices`,
    JSON.stringify({
      name: unique,
      hostname: `${unique}.example.test`,
      description: 'k6 lifecycle probe',
      ip_address: '192.0.2.10',
      model: 'DEC750',
      tags: ['k6', 'load'],
    }),
    { headers, tags: { endpoint: 'devices.create' } },
  );
  createDuration.add(created.timings.duration);
  if (!expectStatus(created, 201, 'devices.create')) {
    return;
  }
  const deviceId = created.json('id');
  if (!deviceId) {
    fail('devices.create did not return an id');
  }

  try {
    // -------------------------------------------------------------- read back
    expectStatus(get(`/devices/${deviceId}`, token, { endpoint: 'devices.get' }), 200, 'devices.get');
    expectStatus(
      get(`/devices?search=${encodeURIComponent(unique)}`, token, { endpoint: 'devices.list' }),
      200,
      'devices.list',
    );

    // ------------------------------------------------------------------ patch
    const patched = http.patch(
      `${API}/devices/${deviceId}`,
      JSON.stringify({ description: 'k6 lifecycle probe (updated)', tags: ['k6', 'updated'] }),
      { headers, tags: { endpoint: 'devices.patch' } },
    );
    patchDuration.add(patched.timings.duration);
    check(patched, {
      'devices.patch returns 200': (r) => r.status === 200,
      'devices.patch applies the description': (r) => r.status === 200 && r.json('description').includes('updated'),
    });

    // ---------------------------------------------------------------- command
    const command = http.post(
      `${API}/devices/${deviceId}/commands`,
      JSON.stringify({ action: 'noop', payload: { source: 'k6' } }),
      { headers, tags: { endpoint: 'devices.command' } },
    );
    check(command, {
      'devices.command queues a noop': (r) => r.status === 201,
    });
    expectStatus(
      get(`/devices/${deviceId}/commands`, token, { endpoint: 'devices.commands' }),
      200,
      'devices.commands',
    );

    sleep(0.2);
  } finally {
    // ----------------------------------------------------------------- delete
    const deleted = http.del(`${API}/devices/${deviceId}`, null, {
      headers,
      tags: { endpoint: 'devices.delete' },
    });
    deleteDuration.add(deleted.timings.duration);
    check(deleted, {
      'devices.delete returns 200': (r) => r.status === 200,
    });
  }
}
