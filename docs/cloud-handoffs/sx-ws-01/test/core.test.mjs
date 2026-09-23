// All data is fictional; these tests do not contact any API or verify React/browser integration.
import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { FrameStore, eligibility, resourcePath } from '../.build/core.js';
import { parseCommand, parseReviewAddress, reviewRequestAllowed, CommandQueue } from '../.build/commands.js';
import { workspaceViewPort } from '../.build/view-port.js';
import { assertDevBoundary, createDevViewPort } from '../.build/dev-view-port.js';
import { scope, binding, rig, sample, observed, fictionalParser } from './helpers.mjs';
const devEnv = { nodeEnv: 'development', phase: 'phase-development-server', staticExport: false, analysisReadOnly: true };
const capture = async (r, n = 1, state = 'processing.c4.running') => {
  const out = await r.store.capture(r.make(n, state)); assert.equal(out.kind, 'captured'); return out.frameId;
};

test('capture retains raw-byte fingerprints and fictional provenance; access is initially masked', async () => {
  const r = rig(), id = await capture(r);
  assert.equal(r.store.read(observed(id)).reason, 'reauthorization-required');
  await r.store.reauthorize(id); const shown = r.store.read(observed(id));
  assert.equal(shown.kind, 'frame'); assert.equal(shown.frame.lane, 'fictional-test');
  assert.equal(shown.frame.responses[0].sha256, createHash('sha256').update(shown.frame.responses[0].body).digest('hex'));
  assert.throws(() => { shown.frame.stateId = 'report.ready'; }, TypeError);
});
test('lease expires at the boundary and remains expired until a new actual-time check', async () => {
  const r = rig(), id = await capture(r); await r.store.reauthorize(id);
  r.ctx.now += 29_999; assert.equal(r.store.read(observed(id)).kind, 'frame');
  r.ctx.now++; assert.equal(r.store.read(observed(id)).reason, 'reauthorization-required');
  await r.store.reauthorize(id); assert.equal(r.store.read(observed(id)).kind, 'frame');
});
test('access revocation purges frames; temporary unavailable access masks without restoring prior lease', async () => {
  const r = rig(), id = await capture(r); await r.store.reauthorize(id);
  r.ctx.access = 'unavailable'; await r.store.reauthorize(id);
  assert.equal(r.store.read(observed(id)).kind, 'unavailable'); assert.equal(r.store.stats().frames, 1);
  r.ctx.access = 'denied'; assert.equal((await r.store.reauthorize(id)).reason, 'access-revoked');
  assert.equal(r.store.stats().frames, 0);
});
test('tenant/session switch purges; a forged grant for another tenant is rejected', async () => {
  const r = rig(), id = await capture(r); await r.store.reauthorize(id);
  r.store.switchScope({ ...scope, tenant: 'fictional-other' }); assert.equal(r.store.stats().frames, 0);
  assert.equal(r.store.read(observed(id)).kind, 'unavailable');
  const q = rig(), next = await capture(q); q.ctx.grantTransform = g => ({ ...g, scope: { ...g.scope, tenant: 'fictional-other' } });
  assert.equal((await q.store.reauthorize(next)).reason, 'authorization-binding-mismatch');
});
test('report permission needs exact artifact digests, not merely access to the call', async () => {
  const r = rig(), id = await capture(r, 1, 'report.ready');
  r.ctx.grantTransform = g => ({ ...g, artifacts: [] });
  assert.equal((await r.store.reauthorize(id)).reason, 'artifact-not-currently-authorized');
  assert.equal(r.store.stats().frames, 0);
});
test('newer report with old transcript fails even when individual JSON parses', async () => {
  const r = rig(), data = r.make(1, 'report.ready');
  const raw = JSON.parse(data.responses[2].body); raw.binding.transcriptRevision = 'fictional-transcript-2';
  data.responses[2].body = JSON.stringify(raw);
  assert.equal((await r.store.capture(data)).reason, 'transcript-mismatch');
});
test('changed source identity and ready-without-artifacts fail closed', async () => {
  const r = rig(), data = r.make(1, 'report.ready');
  const raw = JSON.parse(data.responses[1].body); raw.binding.sourceSha256 = 'b'.repeat(64);
  data.responses[1].body = JSON.stringify(raw); assert.equal((await r.store.capture(data)).reason, 'source-mismatch');
  const bad = r.make(2, 'report.ready'); bad.responses = [bad.responses[0]];
  assert.equal((await r.store.capture(bad)).reason, 'report-bundle-required');
});
test('duplicate observations do not grow memory or extend original TTL', async () => {
  const r = rig({ limits: { ttlMs: 100 } }), id = await capture(r), size = r.store.stats().bytes;
  r.ctx.now += 20; const duplicate = await r.store.capture(r.make(2));
  assert.deepEqual(duplicate, { kind: 'duplicate', frameId: id }); assert.equal(r.store.stats().bytes, size);
  r.ctx.now += 80; assert.equal(r.store.stats().frames, 0);
});
test('duplicate ordinal and out-of-order completion cannot replace newer observations', async () => {
  const r = rig(); await capture(r, 2);
  assert.equal((await r.store.capture(r.make(2))).reason, 'duplicate-or-out-of-order');
  assert.equal((await r.store.capture(r.make(1))).reason, 'duplicate-or-out-of-order');
  assert.equal(r.store.stats().frames, 1);
});
test('memory count, retained UTF-8 bytes, oversized response and earliest retention are bounded', async () => {
  const r = rig({ limits: { frames: 2, bytes: 2800, responseBytes: 512 } });
  for (let i = 1; i <= 20; i++) {
    const data = r.make(i); data.ui.observationAgeMs = i;
    await r.store.capture(data); assert.ok(r.store.stats().frames <= 2); assert.ok(r.store.stats().bytes <= 2800);
  }
  const large = r.make(21); large.responses[0].body = 'x'.repeat(513);
  assert.equal((await r.store.capture(large)).reason, 'response-too-large');
  const q = rig(), input = q.make(1); input.retainUntil = q.ctx.now + 1;
  assert.equal((await q.store.capture(input)).kind, 'captured'); q.ctx.now++; assert.equal(q.store.stats().frames, 0);
});
test('retention boundary and clock rollback purge instead of renewing access', async () => {
  const r = rig(), id = await capture(r); await r.store.reauthorize(id);
  r.ctx.now--; assert.throws(() => r.store.read(observed(id)), /clock-invalid-or-regressed/);
  r.ctx.now += 2; assert.equal(r.store.stats().frames, 0);
});
test('a completed call never reconstructs unobserved running state', async () => {
  const r = rig(), id = await capture(r, 1, 'report.ready'); await r.store.reauthorize(id);
  assert.equal(r.store.read({ ...observed(id), expectedState: 'processing.c2.running' }).reason, 'state-not-observed');
  assert.equal(r.store.read(observed('f-0-99-aaaaaaaaaaaaaaaa')).reason, 'history-not-captured-or-expired');
});
test('presentation controls are orthogonal; reader requires a real selected target', async () => {
  const r = rig(), id = await capture(r, 1, 'report.ready'); await r.store.reauthorize(id);
  const selected = { mode: 'presentation', frameId: id, section: 'moments', reader: 'fictional-moment-1', observationAgeMs: 60_001 };
  const shown = r.store.read(selected); assert.equal(shown.kind, 'frame'); assert.equal(shown.frame.stateId, 'report.ready');
  assert.equal(shown.ui.section, 'moments'); assert.equal(shown.frame.ui.section, 'overview');
  assert.equal(r.store.read({ ...selected, reader: 'missing' }).reason, 'presentation-unavailable');
  const q = rig(), active = await capture(q); await q.store.reauthorize(active);
  assert.equal(q.store.read({ mode: 'presentation', frameId: active, section: 'moments' }).reason, 'presentation-unavailable');
});
test('each read reuses parser; parser drift revokes a stored view', async () => {
  let broken = false; const r = rig({ parse: rows => { if (broken) throw new Error('sensitive-private-parser-message'); return fictionalParser(rows); } });
  const id = await capture(r); await r.store.reauthorize(id); broken = true;
  assert.deepEqual(r.store.read(observed(id)), { kind: 'unavailable', reason: 'revalidation-failed' });
  const out = await r.store.capture(r.make(2)); assert.equal(out.reason, 'parser-or-capture-rejected');
  assert.ok(!JSON.stringify(out).includes('sensitive'));
});
test('response capture rejects non-GET, arbitrary origins, and duplicate resources', async () => {
  for (const patch of [{ method: 'POST' }, { path: 'https://example.invalid/v1' }, { status: 201 }, { path: resourcePath(scope.call, 'status') + '?x=1' }]) {
    const r = rig(), data = r.make(1); Object.assign(data.responses[0], patch);
    assert.equal((await r.store.capture(data)).reason, 'response-route');
  }
  const r = rig(), data = r.make(1); data.responses.push(data.responses[0]);
  assert.equal((await r.store.capture(data)).reason, 'response-kind');
});
test('reset fences pending capture and pending authorization', async () => {
  const r = rig(), promise = r.store.capture(r.make(1)); r.store.reset();
  assert.equal((await promise).reason, 'reset-race');
  let finish; const q = rig({ authorize: () => new Promise(resolve => { finish = resolve; }) });
  const id = await capture(q), pending = q.store.reauthorize(id); q.store.reset();
  finish({ status: 'denied' }); assert.equal((await pending).reason, 'stale-authorization'); assert.equal(q.store.stats().frames, 0);
});
test('late authorization cannot approve another frame or resurrect earlier epoch', async () => {
  const finishes = []; const r = rig({ authorize: (s, b, rows) => new Promise(resolve => finishes.push(() => resolve({ status: 'allowed', scope: s, binding: b,
    checkedAt: 1_000_000, expiresAt: 1_030_000, artifacts: rows.filter(x => x.resource !== 'status') }))) });
  const a = await capture(r, 1), b = await capture(r, 2, 'processing.c5.running');
  const first = r.store.reauthorize(a), second = r.store.reauthorize(b); finishes[1](); finishes[0]();
  assert.equal((await first).reason, 'stale-authorization'); assert.equal((await second).kind, 'authorized');
  assert.equal(r.store.read(observed(a)).kind, 'unavailable'); assert.equal(r.store.read(observed(b)).kind, 'frame');
});
test('future or excessively old authorization timestamp cannot mint a valid lease', async () => {
  for (const delta of [-1, 1]) {
    const r = rig(), id = await capture(r); r.ctx.grantTransform = g => ({ ...g, checkedAt: g.checkedAt + delta });
    assert.equal((await r.store.reauthorize(id)).reason, 'authorization-time-invalid');
  }
});
test('a hung authorizer returns without revealing a frame', async () => {
  const r = rig({ limits: { leaseMs: 5 }, authorize: () => new Promise(() => {}) }), id = await capture(r);
  assert.equal((await r.store.reauthorize(id)).kind, 'unavailable');
  assert.equal(r.store.read(observed(id)).kind, 'unavailable');
});
test('wrong evidence lane is not eligible', async () => {
  const r = rig(), id = await capture(r); await r.store.reauthorize(id); const shown = r.store.read(observed(id));
  assert.equal(eligibility(observed(id), shown.frame, { frameId: id, generation: 0, checkedAt: r.ctx.now, expiresAt: r.ctx.now + 100 },
    { scope, generation: 0, now: r.ctx.now, lane: 'actual-response' }).reason, 'evidence-lane-mismatch');
});
test('URL grammar rejects remote origins, authority flags, duplicate selectors and traversal', () => {
  const base = `/?call=${scope.call}`;
  assert.equal(parseReviewAddress(`${base}&section=prospect`).section, 'prospect');
  for (const bad of [`https://example.invalid${base}`, `//example.invalid${base}`, `${base}&stage=C2`, `${base}&accepted=true`,
    `${base}&call=${scope.call}`, `${base}&section=bad`, '/?call=not-a-uuid', `/hidden/../?call=${scope.call}`,  `/\\example.invalid${base}`, `${base}#sx-review=v1&mode=observed&frame=bad`,
    `${base}#sx-review=v1&sx-review=v1&mode=observed&frame=f-0-1-aaaaaaaaaaaaaaaa`]) assert.throws(() => parseReviewAddress(bad));
});
test('finite commands reject operational intent, unknown keys and oversized payloads', () => {
  assert.equal(parseCommand('{"type":"viewport","width":390,"height":844}').type, 'viewport');
  assert.equal(parseCommand('{"type":"motion","value":"reduce"}').value, 'reduce');
  for (const value of [{ type: 'approve' }, { type: 'select', selection: { mode: 'live', accepted: true } },
    { type: 'viewport', width: 1, height: 1 }, { type: 'hover', target: 'body > *' }, { type: 'reset', eval: '1+1' },
    { type: 'select', selection: { mode: 'observed', frameId: 'f-0-1-aaaaaaaaaaaaaaaa', section: 'moments' } }])
    assert.throws(() => parseCommand(JSON.stringify(value)));
  assert.throws(() => parseCommand('x'.repeat(4097)));
});
test('modeled read-only policy dispatches zero provider/business writes; auth exceptions are explicit', () => {
  let upstream = 0; const root = `/v1/conversation/acquisition/submissions/${scope.call}`;
  for (const method of ['POST', 'PUT', 'PATCH', 'DELETE']) for (const path of [root, `${root}/source`, `${root}/plan`, `${root}/plan/quote`, '/v1/conversation/runs', '/v1/conversation/acquisition/claim'])
    if (reviewRequestAllowed(method, path, scope.call)) upstream++;
  assert.equal(upstream, 0);
  for (const path of ['/v1/auth/password/login', '/v1/auth/logout', '/v1/context']) assert.equal(reviewRequestAllowed('POST', path, scope.call), true);
  assert.equal(reviewRequestAllowed('GET', root, scope.call), true); assert.equal(reviewRequestAllowed('GET', root + '/report?source=elsewhere', scope.call), false);
});
test('production port is the exact live object and imports no review runtime', async () => {
  const model = { state: 'live-model' }; assert.strictEqual(workspaceViewPort(model).model, model);
  const source = await readFile(new URL('../.build/view-port.js', import.meta.url), 'utf8');
  assert.ok(!/import\s|fetch\(|FrameStore|__review/.test(source));
});
test('dev guard rejects builds/static or mutation-capable policy', () => {
  const good = { nodeEnv: 'development', phase: 'phase-development-server', staticExport: false, analysisReadOnly: true };
  assert.doesNotThrow(() => assertDevBoundary(good));
  for (const patch of [{ nodeEnv: 'production' }, { phase: 'phase-production-build' }, { staticExport: true }, { analysisReadOnly: false }])
    assert.throws(() => assertDevBoundary({ ...good, ...patch }));
});
test('per-canvas remount resumes descriptor after fresh auth; hold never overwrites live model', async () => {
  const r = rig(), id = await capture(r); const project = f => ({ state: f.frame.stateId });
  const a = createDevViewPort(r.store, project, devEnv), live = { state: 'new-live-state' }; await a.select(observed(id));
  assert.equal(a.render(live).model.state, 'processing.c4.running'); assert.equal(live.state, 'new-live-state');
  const count = r.ctx.calls, b = createDevViewPort(r.store, project, devEnv); await b.select(a.descriptor()); assert.equal(r.ctx.calls, count + 1);
  assert.equal(b.render(live).model.state, 'processing.c4.running'); r.ctx.now += 30_000; assert.equal(b.render(live).kind, 'blocked');
  b.reset(); assert.strictEqual(b.render(live).model, live); assert.equal(r.store.stats().frames, 0);
});
test('pending capture and command queue allocations are bounded', async () => {
  const r = rig(), pending = r.store.capture(r.make(1));
  for (let i = 2; i < 50; i++) assert.equal((await r.store.capture(r.make(i))).reason, 'capture-busy');
  assert.equal((await pending).kind, 'captured');
  const queue = new CommandQueue();
  for (let i = 0; i < 16; i++) queue.enqueue('{"type":"return-live"}');
  assert.throws(() => queue.enqueue('{"type":"return-live"}'), /queue-full/);
  assert.equal(queue.size, 16); queue.clear(); assert.equal(queue.take(), undefined);
});
test('pure eligibility requires exact selected frame identity', async () => {
  const r = rig(), id = await capture(r); await r.store.reauthorize(id); const { frame } = r.store.read(observed(id));
  assert.equal(eligibility(observed('f-0-2-aaaaaaaaaaaaaaaa'), frame, undefined,
    { scope, generation: 0, now: r.ctx.now, lane: 'fictional-test' }).reason, 'frame-selector-mismatch');
});
test('a current status naming a different report cannot be composed into a ready frame', async () => {
  const r = rig(), input = r.make(1, 'report.ready');
  const body = JSON.parse(input.responses[0].body); body.binding.reportId = 'fictional-report-old'; input.responses[0].body = JSON.stringify(body);
  assert.equal((await r.store.capture(input)).reason, 'status-report-mismatch');
});
test('lease expiring during parser work does not release a stale private model', async () => {
  let duringRead = false; const r = rig({ parse: rows => { if (duringRead) r.ctx.now += 30_000; return fictionalParser(rows); } });
  const id = await capture(r); await r.store.reauthorize(id); duringRead = true;
  assert.equal(r.store.read(observed(id)).reason, 'lease-expired-during-parse');
});
