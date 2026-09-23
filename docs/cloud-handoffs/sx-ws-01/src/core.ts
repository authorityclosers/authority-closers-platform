/** Trusted in-process review kernel. No fetch, disk, React, or operational commands.
 * Wire the real parsers/authorizer on the bridge side, never from browser input.
 * 'actual-response' is an adapter assertion, NOT remote attestation by this kernel.
 */
export type Json = null | boolean | number | string | Json[] | { [k: string]: Json };
export type Lane = "actual-response" | "fictional-test";
export const sections = ["overview", "prospect", "moments", "skills", "next-call-plan"] as const;
export type Section = (typeof sections)[number];
export const states = [
  "access.checking", "access.login-required", "access.workspace-choice", "access.no-workspace", "access.unavailable",
  "restore.opening", "restore.missing", "restore.permission-denied", "restore.session-required",
  "upload.empty", "upload.selected", "upload.consent-needed", "upload.challenge-needed", "upload.hashing",
  "upload.transferring", "upload.receipt-uncertain", "processing.recording-check", "processing.c2.queued",
  "processing.c2.running", "processing.c4.queued", "processing.c4.running", "processing.c4.saved-partial",
  "processing.c5.queued", "processing.c5.running", "processing.approval-required", "processing.held",
  "processing.status-unknown", "report.fetching", "report.validating", "report.ready", "report.unavailable",
  "library.loading", "library.empty", "library.ready", "library.unavailable",
] as const;
export type StateId = (typeof states)[number];
export type Resource = "status" | "transcript" | "report";
export type Scope = Readonly<{ owner: string; tenant: string; sessionEpoch: string; call: string }>;
export type Binding = Readonly<{
  recordingId: string; sourceSha256: string; transcriptRevision: string | null; reportId: string | null;
}>;
export type Artifact = Readonly<{ resource: Resource; binding: Binding }>;
export type Ui = Readonly<{
  section: Section; reader: string | null;
  health: "fresh" | "retrying" | "unavailable" | "offline" | "unchanged";
  observationAgeMs: number;
}>;
export type ParsedView = Readonly<{
  stateId: StateId; binding: Binding; artifacts: readonly Artifact[];
  readerTargets: readonly string[]; view: Json;
}>;
export type ResponseInput = Readonly<{
  resource: Resource; method: "GET"; path: string; status: 200; receivedAt: number; body: string;
}>;
export type ResponseRecord = ResponseInput & Readonly<{ sha256: string }>;
export type Frame = Readonly<{
  id: string; lane: Lane; scope: Scope; ordinal: number; observedAt: number; expiresAt: number;
  parserRevision: string; stateId: StateId; binding: Binding; ui: Ui;
  readerTargets: readonly string[]; responses: readonly ResponseRecord[];
}>;
export type Lease = Readonly<{ frameId: string; generation: number; checkedAt: number; expiresAt: number }>;
export type Grant =
  | Readonly<{ status: "denied" | "unavailable" }>
  | Readonly<{
      status: "allowed"; scope: Scope; binding: Binding; checkedAt: number; expiresAt: number;
      artifacts: readonly Readonly<{ resource: "report" | "transcript"; sha256: string }>[];
    }>;
export type Selection =
  | Readonly<{ mode: "live" }>
  | Readonly<{ mode: "observed"; frameId: string; expectedState?: StateId }>
  | Readonly<{
      mode: "presentation"; frameId: string; expectedState?: StateId;
      section?: Section; reader?: string | null; observationAgeMs?: number;
    }>;
export type Unavailable = Readonly<{ kind: "unavailable"; reason: string }>;
export type SelectionResult =
  | Readonly<{ kind: "live" }>
  | Unavailable
  | Readonly<{ kind: "frame"; mode: "observed" | "presentation"; frame: Frame; ui: Ui; view: Json; leaseExpiresAt: number }>;
export type Limits = Readonly<{
  frames: number; bytes: number; responseBytes: number; ttlMs: number; leaseMs: number;
}>;
export const DEFAULT_LIMITS: Limits = Object.freeze({
  frames: 128, bytes: 16 * 1024 ** 2, responseBytes: 4 * 1024 ** 2, ttlMs: 1_800_000, leaseMs: 30_000,
});
export const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
export const REF = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$/;
const HASH = /^[a-f0-9]{64}$/;
const utf8 = new TextEncoder();
const unavailable = (reason: string): Unavailable => ({ kind: "unavailable", reason });
class ReviewError extends Error {}
function ensure(condition: unknown, reason: string): asserts condition {
  if (!condition) throw new ReviewError(reason);
}
export const sameScope = (a: Scope, b: Scope): boolean =>
  a.owner === b.owner && a.tenant === b.tenant && a.sessionEpoch === b.sessionEpoch && a.call === b.call;
const sameBinding = (a: Binding, b: Binding): boolean =>
  a.recordingId === b.recordingId && a.sourceSha256 === b.sourceSha256 &&
  a.transcriptRevision === b.transcriptRevision && a.reportId === b.reportId;
export function resourcePath(call: string, resource: Resource): string {
  return `/v1/conversation/acquisition/submissions/${call}${resource === "status" ? "" : `/${resource}`}`;
}
function validScope(s: Scope): boolean {
  return REF.test(s.owner) && REF.test(s.tenant) && REF.test(s.sessionEpoch) && UUID.test(s.call);
}
function validBinding(b: Binding): boolean {
  return UUID.test(b.recordingId) && HASH.test(b.sourceSha256) &&
    (b.transcriptRevision === null || REF.test(b.transcriptRevision)) &&
    (b.reportId === null || REF.test(b.reportId));
}
function validateUi(ui: Ui, parsed: Pick<ParsedView, "stateId" | "readerTargets">): void {
  ensure(sections.includes(ui.section), "section-invalid");
  ensure(["fresh", "retrying", "unavailable", "offline", "unchanged"].includes(ui.health), "health-invalid");
  ensure(Number.isSafeInteger(ui.observationAgeMs) && ui.observationAgeMs >= 0 && ui.observationAgeMs <= 1_800_000, "age-invalid");
  ensure(ui.reader === null || (parsed.stateId === "report.ready" && parsed.readerTargets.includes(ui.reader)), "reader-unavailable");
  ensure(parsed.stateId === "report.ready" || ui.section === "overview", "section-unavailable");
}
function validateParsed(p: ParsedView, responses: readonly ResponseInput[]): void {
  ensure(states.includes(p.stateId) && validBinding(p.binding), "parser-metadata-invalid");
  ensure(p.artifacts.length === responses.length && p.artifacts.length <= 3, "artifact-count");
  const kinds = new Set<Resource>();
  for (const a of p.artifacts) {
    ensure(!kinds.has(a.resource) && responses.some(r => r.resource === a.resource), "artifact-kind");
    kinds.add(a.resource);
    ensure(validBinding(a.binding) && a.binding.recordingId === p.binding.recordingId &&
      a.binding.sourceSha256 === p.binding.sourceSha256, "source-mismatch");
    if (a.resource === "status" && a.binding.reportId !== null && p.binding.reportId !== null)
      ensure(a.binding.reportId === p.binding.reportId, "status-report-mismatch");
    if (a.resource !== "status") ensure(a.binding.transcriptRevision === p.binding.transcriptRevision, "transcript-mismatch");
    if (a.resource === "report") ensure(a.binding.reportId === p.binding.reportId && a.binding.reportId !== null, "report-mismatch");
  }
  ensure(kinds.has("status"), "status-required");
  if (p.stateId === "report.ready") ensure(kinds.has("report") && kinds.has("transcript") && p.binding.reportId !== null &&
    p.binding.transcriptRevision !== null, "report-bundle-required");
  ensure(p.readerTargets.length <= 256 && new Set(p.readerTargets).size === p.readerTargets.length &&
    p.readerTargets.every(x => REF.test(x)), "reader-targets-invalid");
}
/** Data integrity fingerprint, not a signature and not proof of upstream identity. */
async function digest(text: string): Promise<string> {
  const bytes = await globalThis.crypto.subtle.digest("SHA-256", utf8.encode(text));
  return Array.from(new Uint8Array(bytes), n => n.toString(16).padStart(2, "0")).join("");
}
function immutable<T>(value: T): T {
  const copy = structuredClone(value);
  function freeze(x: unknown): void {
    if (x && typeof x === "object" && !Object.isFrozen(x)) {
      Object.freeze(x);
      for (const child of Object.values(x)) freeze(child);
    }
  }
  freeze(copy);
  return copy;
}
/** Pure eligibility. It never changes the call, lease, cache, or backend. */
export function eligibility(selection: Selection, frame: Frame | undefined, lease: Lease | undefined,
  context: Readonly<{ scope: Scope; generation: number; now: number; lane: Lane }>): Unavailable | { kind: "eligible"; ui: Ui } | { kind: "live" } {
  if (selection.mode === "live") return { kind: "live" };
  if (!frame) return unavailable("history-not-captured-or-expired");
  if (frame.id !== selection.frameId) return unavailable("frame-selector-mismatch");
  if (frame.lane !== context.lane) return unavailable("evidence-lane-mismatch");
  if (!sameScope(frame.scope, context.scope)) return unavailable("scope-mismatch");
  if (context.now < frame.observedAt || context.now >= frame.expiresAt) return unavailable("frame-expired");
  if (!lease || lease.generation !== context.generation || lease.frameId !== frame.id ||
    context.now < lease.checkedAt || context.now >= lease.expiresAt) return unavailable("reauthorization-required");
  if (selection.expectedState !== undefined && frame.stateId !== selection.expectedState) return unavailable("state-not-observed");
  const ui: Ui = selection.mode === "observed" ? frame.ui : {
    ...frame.ui,
    section: selection.section ?? frame.ui.section,
    reader: selection.reader === undefined ? frame.ui.reader : selection.reader,
    observationAgeMs: selection.observationAgeMs ?? frame.ui.observationAgeMs,
  };
  try { validateUi(ui, { stateId: frame.stateId, readerTargets: frame.readerTargets }); }
  catch { return unavailable("presentation-unavailable"); }
  return { kind: "eligible", ui };
}
export type CaptureInput = Readonly<{
  ordinal: number; observedAt: number; retainUntil: number; responses: readonly ResponseInput[]; ui: Ui;
}>;
export type CaptureResult = Unavailable | Readonly<{ kind: "captured" | "duplicate"; frameId: string }>;
type Entry = { frame: Frame; bytes: number; fingerprint: string };
export type Authorize = (scope: Scope, binding: Binding, responses: readonly Readonly<{ resource: Resource; sha256: string }>[], signal: AbortSignal) => Promise<Grant>;
export type Parse = (responses: readonly ResponseInput[]) => ParsedView;
export class FrameStore {
  #scope: Scope; #lane: Lane; #limits: Limits; #clock: () => number; #parse: Parse;
  #authorize: Authorize; #parserRevision: string; #frames = new Map<string, Entry>();
  #leases = new Map<string, Lease>(); #bytes = 0; #ordinal = -1; #generation = 0;
  #captureBusy = false;
  #lastTime = 0; #authSerial = 0; #authAbort: AbortController | undefined;
  constructor(options: { scope: Scope; lane: Lane; now: () => number; parse: Parse; authorize: Authorize;
    parserRevision: string; limits?: Partial<Limits> }) {
    ensure(validScope(options.scope) && REF.test(options.parserRevision), "scope-or-parser-invalid");
    ensure(["actual-response", "fictional-test"].includes(options.lane), "lane-invalid");
    this.#scope = immutable(options.scope); this.#lane = options.lane; this.#clock = options.now;
    this.#parse = options.parse; this.#authorize = options.authorize; this.#parserRevision = options.parserRevision;
    this.#limits = { ...DEFAULT_LIMITS, ...options.limits };
    for (const key of Object.keys(DEFAULT_LIMITS) as (keyof Limits)[]) {
      const n = this.#limits[key]; ensure(Number.isSafeInteger(n) && n > 0 && n <= DEFAULT_LIMITS[key], "limit-invalid");
    }
  }
  #time(): number {
    const now = this.#clock();
    if (!Number.isSafeInteger(now) || now < this.#lastTime) { this.reset(); throw new Error("clock-invalid-or-regressed"); }
    this.#lastTime = now; return now;
  }
  #drop(id: string): void {
    const e = this.#frames.get(id); if (e) this.#bytes -= e.bytes;
    this.#frames.delete(id); this.#leases.delete(id);
  }
  #prune(now: number): void {
    for (const [id, e] of this.#frames) if (now >= e.frame.expiresAt) this.#drop(id);
    for (const [id, lease] of this.#leases) if (now >= lease.expiresAt) this.#leases.delete(id);
  }
  /** Purges only review state. It does not modify or log out a real application. */
  reset(): void {
    this.#generation++; this.#authSerial++; this.#authAbort?.abort(); this.#authAbort = undefined;
    this.#frames.clear(); this.#leases.clear(); this.#bytes = 0; this.#ordinal = -1;
  }
  switchScope(scope: Scope): void {
    ensure(validScope(scope), "scope-invalid"); this.reset(); this.#scope = immutable(scope);
  }
  revoke(): void { this.reset(); }
  stats(): Readonly<{ frames: number; bytes: number; leases: number; generation: number }> {
    this.#prune(this.#time()); return { frames: this.#frames.size, bytes: this.#bytes, leases: this.#leases.size, generation: this.#generation };
  }
  catalog(): readonly Readonly<{ frameId: string; stateId: StateId; lane: Lane; observedAt: number; expiresAt: number }>[] {
    this.#prune(this.#time());
    return [...this.#frames.values()].map(({ frame: f }) => ({ frameId: f.id, stateId: f.stateId, lane: f.lane, observedAt: f.observedAt, expiresAt: f.expiresAt }));
  }
  async capture(input: CaptureInput): Promise<CaptureResult> {
    const epoch = this.#generation; const now = this.#time(); this.#prune(now);
    if (this.#captureBusy) return unavailable("capture-busy");
    this.#captureBusy = true;
    try {
      ensure(Number.isSafeInteger(input.ordinal) && input.ordinal >= 0 && input.ordinal > this.#ordinal, "duplicate-or-out-of-order");
      ensure(Number.isSafeInteger(input.observedAt) && input.observedAt <= now && input.observedAt >= 0, "observation-time-invalid");
      ensure(Number.isSafeInteger(input.retainUntil) && input.retainUntil > now, "retention-expired");
      ensure(input.responses.length > 0 && input.responses.length <= 3, "response-count");
      const kinds = new Set<Resource>();
      for (const r of input.responses) {
        ensure(["status", "transcript", "report"].includes(r.resource) && !kinds.has(r.resource), "response-kind");
        kinds.add(r.resource);
        ensure(r.method === "GET" && r.path === resourcePath(this.#scope.call, r.resource) && r.status === 200, "response-route");
        ensure(Number.isSafeInteger(r.receivedAt) && r.receivedAt <= input.observedAt && r.receivedAt >= 0, "response-time");
        ensure(typeof r.body === "string" && r.body.length <= this.#limits.responseBytes && utf8.encode(r.body).length <= this.#limits.responseBytes, "response-too-large");
      }
      const snapshot = immutable(input);
      const parsed = this.#parse(snapshot.responses); validateParsed(parsed, snapshot.responses); validateUi(snapshot.ui, parsed);
      const responses: ResponseRecord[] = [];
      for (const r of snapshot.responses) responses.push({ ...r, sha256: await digest(r.body) });
      const fingerprint = await digest(JSON.stringify({ responses: responses.map(r => [r.resource, r.sha256]), state: parsed.stateId,
        binding: parsed.binding, ui: snapshot.ui, parser: this.#parserRevision }));
      const current = this.#time(); this.#prune(current);
      if (epoch !== this.#generation) return unavailable("reset-race");
      if (snapshot.ordinal <= this.#ordinal) return unavailable("duplicate-or-out-of-order");
      const expiresAt = Math.min(snapshot.observedAt + this.#limits.ttlMs, snapshot.retainUntil);
      ensure(expiresAt > current, "frame-expired");
      const frame: Frame = immutable({ id: `f-${epoch}-${snapshot.ordinal}-${fingerprint.slice(0, 16)}`, lane: this.#lane,
        scope: this.#scope, ordinal: snapshot.ordinal, observedAt: snapshot.observedAt, expiresAt,
        parserRevision: this.#parserRevision, stateId: parsed.stateId, binding: parsed.binding,
        ui: snapshot.ui, readerTargets: parsed.readerTargets, responses });
      // Budget is retained UTF-8 serialization, not exact JS heap allocation. No parsed customer view is cached twice.
      const bytes = utf8.encode(JSON.stringify(frame)).length;
      ensure(bytes <= this.#limits.bytes, "frame-too-large");
      this.#ordinal = snapshot.ordinal;
      for (const { frame: existing, fingerprint: fp } of this.#frames.values()) {
        if (fp === fingerprint && expiresAt >= existing.expiresAt) return { kind: "duplicate", frameId: existing.id };
      }
      while (this.#frames.size >= this.#limits.frames || this.#bytes + bytes > this.#limits.bytes) {
        const oldest = this.#frames.keys().next().value; if (!oldest) break; this.#drop(oldest);
      }
      this.#frames.set(frame.id, { frame, bytes, fingerprint }); this.#bytes += bytes;
      return { kind: "captured", frameId: frame.id };
    } catch (e) { return unavailable(e instanceof ReviewError ? e.message : "parser-or-capture-rejected"); }
    finally { this.#captureBusy = false; }
  }
  async reauthorize(frameId: string): Promise<Readonly<{ kind: "authorized"; expiresAt: number }> | Unavailable> {
    const now = this.#time(); this.#prune(now); const entry = this.#frames.get(frameId);
    if (!entry) return unavailable("history-not-captured-or-expired");
    this.#authAbort?.abort(); const controller = new AbortController(); this.#authAbort = controller;
    const serial = ++this.#authSerial; const generation = this.#generation;
    this.#leases.clear(); // Unverifiable access must not leave an older lease usable.
    const f = entry.frame;
    let grant: Grant; let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      grant = await Promise.race([
        this.#authorize(this.#scope, f.binding, f.responses.map(r => ({ resource: r.resource, sha256: r.sha256 })), controller.signal),
        new Promise<Grant>(resolve => { timer = setTimeout(() => {
          controller.abort(); resolve({ status: "unavailable" });
        }, this.#limits.leaseMs); }),
      ]);
    } catch { grant = { status: "unavailable" }; }
    finally { clearTimeout(timer); }
    const end = this.#time(); this.#prune(end);
    if (serial !== this.#authSerial || generation !== this.#generation || controller.signal.aborted) return unavailable("stale-authorization");
    this.#authAbort = undefined;
    if (grant.status === "denied") { this.reset(); return unavailable("access-revoked"); }
    if (grant.status !== "allowed") return unavailable("authorization-unavailable");
    if (!sameScope(grant.scope, this.#scope) || !sameBinding(grant.binding, f.binding)) {
      this.reset(); return unavailable("authorization-binding-mismatch");
    }
    if (!this.#frames.has(frameId)) return unavailable("frame-expired");
    for (const r of f.responses) if (r.resource !== "status" && !grant.artifacts.some(a => a.resource === r.resource && a.sha256 === r.sha256)) {
      this.#drop(frameId); return unavailable("artifact-not-currently-authorized");
    }
    if (!Number.isSafeInteger(grant.checkedAt) || grant.checkedAt < now || grant.checkedAt > end || !Number.isSafeInteger(grant.expiresAt))
      return unavailable("authorization-time-invalid");
    const expiresAt = Math.min(grant.expiresAt, grant.checkedAt + this.#limits.leaseMs, f.expiresAt);
    if (end >= expiresAt) return unavailable("lease-expired");
    this.#leases.set(frameId, immutable({ frameId, generation, checkedAt: grant.checkedAt, expiresAt }));
    return { kind: "authorized", expiresAt };
  }
  read(selection: Selection): SelectionResult {
    const now = this.#time(); this.#prune(now);
    if (selection.mode === "live") return { kind: "live" };
    const frame = this.#frames.get(selection.frameId)?.frame;
    const result = eligibility(selection, frame, this.#leases.get(selection.frameId), { scope: this.#scope, generation: this.#generation, now, lane: this.#lane });
    if (result.kind !== "eligible" || !frame) return result as Unavailable;
    try {
      // Reuse the supplied production parser, not a second relaxed report validator.
      const parsed = this.#parse(frame.responses); validateParsed(parsed, frame.responses);
      ensure(parsed.stateId === frame.stateId && sameBinding(parsed.binding, frame.binding) &&
        JSON.stringify(parsed.readerTargets) === JSON.stringify(frame.readerTargets), "parser-drift");
      const lease = this.#leases.get(frame.id)!;
      if (this.#time() >= Math.min(lease.expiresAt, frame.expiresAt)) {
        this.#leases.delete(frame.id); return unavailable("lease-expired-during-parse");
      }
      return immutable({ kind: "frame", mode: selection.mode, frame, ui: result.ui, view: parsed.view, leaseExpiresAt: lease.expiresAt });
    } catch {
      this.#drop(frame.id); return unavailable("revalidation-failed");
    }
  }
}
