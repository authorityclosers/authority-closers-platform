import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate, Trend } from 'k6/metrics';
import crypto from 'k6/crypto';

const base = __ENV.REHEARSAL_URL || 'http://127.0.0.1:18780';
if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(base)) throw new Error('SSH loopback URL required');
const phase = __ENV.PHASE || 'daily';
const seconds = Number(__ENV.SECONDS || (phase === 'daily' ? 1800 : 300));
const users = Number(__ENV.USERS || 200);
const uploads = Number(__ENV.UPLOADS || (phase === 'busy' ? 20 : 10));
const errors = new Rate('people_errors');
const latency = new Trend('people_latency', true);
const uploadErrors = new Rate('upload_errors');
const uploadLatency = new Trend('upload_latency', true);
const paths = [
  ['/v1/lead-desk/my-day', 'Home'],
  ['/v1/lead-desk/leads', 'Leads'],
  ['/v1/api/calls', 'Calls'],
];
export const options = {
  scenarios: {
    people: { executor: 'constant-vus', vus: users, duration: `${seconds}s`, exec: 'people', gracefulStop: '10s' },
    ...(uploads > 0 ? { uploads: { executor: 'shared-iterations', vus: uploads, iterations: uploads,
      startTime: `${Math.min(30, Math.floor(seconds / 3))}s`, maxDuration: '60s', exec: 'upload' } } : {}),
  },
  thresholds: {
    people_errors: ['rate==0'],
    people_latency: [`p(95)<${phase === 'daily' ? 1000 : 1500}`],
    ...(uploads > 0 ? { upload_errors: ['rate==0'] } : {}),
  },
  discardResponseBodies: true,
};
function headers(seller) {
  return { Host: 'api.authorityclosers.com', Origin: 'https://salesxray.authorityclosers.com',
    'X-Rehearsal-Seller': String(seller), 'X-Forwarded-Proto': 'https' };
}
export function people() {
  const seller = (__VU - 1) % 10;
  for (const [path, page] of paths) {
    const response = http.get(base + path, { headers: headers(seller), timeout: '15s', tags: { page, phase } });
    const ok = check(response, { 'authenticated data read succeeds': r => r.status === 200 });
    errors.add(!ok, { page });
    latency.add(response.timings.duration, { page });
    sleep(Number(__ENV.THINK || 10));
  }
}
export function upload() {
  const seller = (__VU - 1) % 10;
  // A tiny valid one-second 8 kHz mono PCM WAV, generated here, never real audio.
  const raw = new Uint8Array(16044);
  const view = new DataView(raw.buffer);
  function text(offset, value) { for (let i = 0; i < value.length; i++) raw[offset + i] = value.charCodeAt(i); }
  text(0, 'RIFF'); view.setUint32(4, 16036, true); text(8, 'WAVE'); text(12, 'fmt ');
  view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, 8000, true); view.setUint32(28, 16000, true); view.setUint16(32, 2, true);
  view.setUint16(34, 16, true); text(36, 'data'); view.setUint32(40, 16000, true);
  const response = http.post(base + '/v1/api/calls', raw.buffer, {
    headers: { ...headers(seller), 'Content-Type': 'application/octet-stream',
      'X-Source-SHA256': crypto.sha256(raw.buffer, 'hex'),
      'X-Recording-Consent': 'participants-informed',
      'X-External-Id': `${__ENV.RUN_ID || phase}-${__VU}-${__ITER}`,
      'X-Call-Title': 'Fictional%20AWS%20rehearsal', 'X-File-Name': 'fictional.wav', 'X-Media-Type': 'audio/wav' },
    tags: { page: 'Upload', phase }, timeout: '30s',
  });
  uploadErrors.add(!check(response, { 'fresh recording durably accepted': r => r.status === 202 }));
  uploadLatency.add(response.timings.duration);
}
export function handleSummary(data) {
  return { [__ENV.SUMMARY || 'summary.json']: JSON.stringify(data, null, 2) };
}
