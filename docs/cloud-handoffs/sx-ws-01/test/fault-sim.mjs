// Seeded model fault simulation. Every response/identity is FICTIONAL; no browser or provider is used.
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { parseCommand, reviewRequestAllowed } from '../.build/commands.js';
import { rig, scope, observed } from './helpers.mjs';
const seed = Number(process.argv[2] ?? 20260923), trials = Number(process.argv[3] ?? 10000);
assert.ok(Number.isSafeInteger(seed) && seed > 0 && seed <= 0xffffffff);
assert.ok(Number.isSafeInteger(trials) && trials > 0 && trials <= 100000);
let random = seed >>> 0;
function draw(n) { random ^= random << 13; random ^= random >>> 17; random ^= random << 5; return (random >>> 0) % n; }
const r = rig({ limits: { frames: 4, bytes: 14000, ttlMs: 100, leaseMs: 20 } });
const counts = { capture: 0, authorize: 0, expire: 0, revoke: 0, switch: 0, malformed: 0, write: 0, reset: 0, duplicate: 0, select: 0 };
const trace = createHash('sha256'); let ordinal = 0, selected = null, maxFrames = 0, maxBytes = 0, upstreamWrites = 0;
for (let step = 0; step < trials; step++) {
  r.ctx.now += draw(4); const action = draw(10); let outcome = '';
  if (action === 0) {
    counts.capture++;
    const state = ['processing.c2.running', 'processing.c4.running', 'processing.c5.running', 'report.ready'][draw(4)];
    const result = await r.store.capture(r.make(++ordinal, state)); outcome = result.kind;
    if (result.kind === 'captured' || result.kind === 'duplicate') selected = result.frameId;
  } else if (action === 1) {
    counts.authorize++; r.ctx.access = draw(4) ? 'allowed' : 'unavailable';
    outcome = selected ? (await r.store.reauthorize(selected)).kind : 'no-frame';
  } else if (action === 2) { counts.expire++; r.ctx.now += 21; outcome = 'clock-advance-fictional'; }
  else if (action === 3) { counts.revoke++; r.store.revoke(); outcome = 'purged'; }
  else if (action === 4) {
    counts.switch++; r.ctx.scope = { ...scope, tenant: `fictional-tenant-${draw(4)}` }; r.store.switchScope(r.ctx.scope); outcome = 'purged';
  } else if (action === 5) {
    counts.malformed++; assert.throws(() => parseCommand(JSON.stringify({ type: 'set-stage', state: 'C5', accepted: true })));
    outcome = 'invalid-command';
  } else if (action === 6) {
    counts.write++; const method = ['POST', 'PUT', 'PATCH', 'DELETE'][draw(4)];
    const path = `/v1/conversation/acquisition/submissions/${scope.call}/plan`;
    if (reviewRequestAllowed(method, path, scope.call)) upstreamWrites++; outcome = 'denied';
  } else if (action === 7) { counts.reset++; r.store.reset(); outcome = 'purged'; }
  else if (action === 8) {
    counts.duplicate++; const a = r.make(++ordinal); const first = await r.store.capture(a); const second = await r.store.capture(a);
    if (first.kind !== 'unavailable') assert.equal(second.reason, 'duplicate-or-out-of-order'); outcome = second.kind;
  } else {
    counts.select++; outcome = selected ? r.store.read(observed(selected)).kind : 'no-frame';
  }
  const stats = r.store.stats(); maxFrames = Math.max(maxFrames, stats.frames); maxBytes = Math.max(maxBytes, stats.bytes);
  assert.ok(stats.frames <= 4 && stats.bytes <= 14000 && stats.leases <= stats.frames);
  if ([3, 4, 7].includes(action)) assert.equal(stats.frames, 0);
  if (selected) {
    const result = r.store.read(observed(selected));
    if (result.kind === 'frame') {
      assert.equal(result.frame.lane, 'fictional-test'); assert.equal(result.frame.scope.tenant, r.ctx.scope.tenant);
      assert.ok(r.ctx.now < result.frame.expiresAt && r.ctx.now < result.leaseExpiresAt);
      const bad = r.store.read({ ...observed(selected), expectedState: 'upload.hashing' });
      assert.equal(bad.reason, 'state-not-observed');
    }
  }
  trace.update(JSON.stringify([step, action, outcome, stats.frames, stats.bytes]) + '\n');
}
assert.equal(upstreamWrites, 0);
console.log(JSON.stringify({ evidence: 'fictional-model-only', seed, trials, counts, maxFrames, maxBytes,
  modeledUpstreamWrites: upstreamWrites, networkRequests: 0, traceSha256: trace.digest('hex'), result: 'PASS' }, null, 2));
