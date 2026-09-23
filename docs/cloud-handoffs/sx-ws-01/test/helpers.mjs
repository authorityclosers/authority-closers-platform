// FICTIONAL model-only response shapes. This parser is NOT an application parser.
import { FrameStore, resourcePath } from '../.build/core.js';
export const scope = Object.freeze({ owner: 'fictional-owner', tenant: 'fictional-tenant', sessionEpoch: 'fictional-session', call: '11111111-1111-4111-8111-111111111111' });
export const binding = Object.freeze({ recordingId: '22222222-2222-4222-8222-222222222222', sourceSha256: 'a'.repeat(64), transcriptRevision: 'fictional-transcript-1', reportId: 'fictional-report-1' });
export function fictionalParser(responses) {
  const rows = responses.map(r => ({ resource: r.resource, value: JSON.parse(r.body) }));
  const status = rows.find(r => r.resource === 'status').value;
  const report = rows.find(r => r.resource === 'report');
  return {
    stateId: status.stateId, binding: report?.value.binding ?? status.binding,
    artifacts: rows.map(r => ({ resource: r.resource, binding: r.value.binding })),
    readerTargets: report ? ['fictional-moment-1'] : [],
    view: { caption: 'Fictional model data, not a provider output', stateId: status.stateId },
  };
}
export function sample(time, ordinal, stateId = 'processing.c4.running', currentScope = scope) {
  const resources = stateId === 'report.ready' ? ['status', 'transcript', 'report'] : ['status'];
  return { ordinal, observedAt: time, retainUntil: time + 1_800_000,
    responses: resources.map(resource => ({ resource, method: 'GET', path: resourcePath(currentScope.call, resource), status: 200,
      receivedAt: time, body: JSON.stringify({ fictional: true, stateId, binding: stateId === 'report.ready' ? binding : { ...binding, transcriptRevision: null, reportId: null } }) })),
    ui: { section: 'overview', reader: null, health: 'fresh', observationAgeMs: 0 },
  };
}
export function rig(options = {}) {
  const ctx = { now: 1_000_000, access: 'allowed', scope, grantTransform: x => x, calls: 0 };
  const authorize = async (s, b, responses) => {
    ctx.calls++;
    if (ctx.access !== 'allowed') return { status: ctx.access };
    return ctx.grantTransform({ status: 'allowed', scope: s, binding: b, checkedAt: ctx.now, expiresAt: ctx.now + 30_000,
      artifacts: responses.filter(r => r.resource !== 'status').map(r => ({ resource: r.resource, sha256: r.sha256 })) });
  };
  const store = new FrameStore({ scope, lane: 'fictional-test', now: () => ctx.now,
    parse: fictionalParser, authorize, parserRevision: 'fictional-parser-v1', ...options });
  return { ctx, store, make: (ordinal, stateId) => sample(ctx.now, ordinal, stateId, ctx.scope), authorize };
}
export const observed = frameId => ({ mode: 'observed', frameId });
