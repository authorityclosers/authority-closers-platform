import { createHash, randomUUID } from "node:crypto";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const SHA = /^[a-f0-9]{64}$/;
const STATES = new Set([
  "queued",
  "pending",
  "running",
  "completed",
  "active",
  "ready",
  "received",
  "saved",
  "held",
  "failed",
  "cancelled",
  "uncertain",
]);
export const REVIEW_LIMITS = Object.freeze({
  frames: 128,
  sessions: 16,
  bytes: 16 * 1024 ** 2,
  responseBytes: 4 * 1024 ** 2,
  lifetimeMs: 30 * 60_000,
  leaseMs: 30_000,
});

// Called only with an actual successful upstream submission read. Deliberately
// excludes report/transcript text, profile data, provider receipts and credentials.
export function progressReceipt(value) {
  if (
    !value ||
    typeof value !== "object" ||
    Array.isArray(value) ||
    !UUID.test(value.submission_id) ||
    !UUID.test(value.recording_id) ||
    !SHA.test(value.source_sha256) ||
    !STATES.has(value.state) ||
    !(value.local_state === null || STATES.has(value.local_state)) ||
    typeof value.has_report !== "boolean" ||
    typeof value.automatic_progression !== "boolean" ||
    !Array.isArray(value.stages) ||
    value.stages.length > 128
  )
    return null;
  const stages = [];
  for (const stage of value.stages) {
    if (
      !stage ||
      !["C2", "C4", "C5"].includes(stage.stage) ||
      !STATES.has(stage.state)
    )
      return null;
    stages.push({ stage: stage.stage, state: stage.state });
  }
  return {
    submission_id: value.submission_id,
    recording_id: value.recording_id,
    source_sha256: value.source_sha256,
    state: value.state,
    local_state: value.local_state,
    has_report: value.has_report,
    automatic_progression: value.automatic_progression,
    stages,
    // Failure codes are identifiers, never provider error bodies or prose.
    ...(typeof value.failure_code === "string" &&
    /^[a-z0-9_]{1,128}$/.test(value.failure_code)
      ? { failure_code: value.failure_code }
      : {}),
  };
}

export function observedStage(receipt) {
  if (receipt.has_report) return "report.available";
  if (
    receipt.state === "held" ||
    receipt.stages.some((x) => x.state === "uncertain")
  )
    return "processing.held";
  if (
    ["failed", "cancelled"].includes(receipt.local_state) ||
    ["failed", "cancelled", "completed"].includes(receipt.state)
  )
    return "processing.attention";
  if (receipt.local_state !== "completed") return "processing.recording-check";
  const latest = ["C2", "C4", "C5"].map((stage) =>
    receipt.stages.findLast((x) => x.stage === stage),
  );
  const running = latest.findLast((x) => x?.state === "running");
  const queued = latest.find((x) => ["queued", "pending"].includes(x?.state));
  if (running) return `processing.${running.stage.toLowerCase()}.running`;
  if (queued) return `processing.${queued.stage.toLowerCase()}.queued`;
  if (latest[1]?.state === "completed" && !latest[2])
    return "processing.c4.saved";
  return "processing.waiting";
}

export class ReviewFrameStore {
  #sessions = new Map();
  constructor({
    now = Date.now,
    id = randomUUID,
    limits = REVIEW_LIMITS,
  } = {}) {
    this.now = now;
    this.id = id;
    this.limits = limits;
  }
  reset(session) {
    clearTimeout(this.#sessions.get(session)?.expiryTimer);
    this.#sessions.delete(session);
  }
  #entry(session) {
    const entry = this.#sessions.get(session);
    if (entry && this.now() >= entry.expiresAt) {
      this.reset(session);
      return null;
    }
    return entry ?? null;
  }
  // Opt-in binds one call to an already authenticated local handle. No supplied
  // client snapshot can be inserted through this API.
  start(session, callId) {
    if (typeof session !== "string" || !session || !UUID.test(callId))
      throw new Error("invalid_review_scope");
    for (const key of this.#sessions.keys()) this.#entry(key);
    if (
      !this.#sessions.has(session) &&
      this.#sessions.size >= this.limits.sessions
    )
      throw new Error("review_capacity");
    this.reset(session);
    const entry = {
      callId,
      epoch: this.id(),
      lineage: null,
      expiresAt: this.now() + this.limits.lifetimeMs,
      leaseUntil: 0,
      frames: [],
      bytes: 0,
      sequence: 0,
      lastDigest: null,
    };
    // Expire idle captures too; no browser polling is required for retention.
    entry.expiryTimer = setTimeout(() => {
      if (this.#sessions.get(session) === entry) this.reset(session);
    }, this.limits.lifetimeMs);
    entry.expiryTimer.unref();
    this.#sessions.set(session, entry);
  }
  authorize(session, value, epoch) {
    const entry = this.#entry(session),
      receipt = progressReceipt(value);
    if (!entry) return false;
    if (epoch !== undefined && entry.epoch !== epoch) return false;
    if (!receipt || receipt.submission_id !== entry.callId) {
      this.reset(session);
      return false;
    }
    const lineage = `${receipt.recording_id}:${receipt.source_sha256}`;
    if (entry.lineage && entry.lineage !== lineage) {
      this.reset(session);
      return false;
    }
    entry.lineage = lineage;
    entry.leaseUntil = Math.min(
      this.now() + this.limits.leaseMs,
      entry.expiresAt,
    );
    return true;
  }
  scope(session) {
    const entry = this.#entry(session);
    return entry
      ? { callId: entry.callId, epoch: entry.epoch, expiresAt: entry.expiresAt }
      : null;
  }
  observe(session, value, epoch) {
    const entry = this.#entry(session),
      receipt = progressReceipt(value);
    if (!entry || !receipt || receipt.submission_id !== entry.callId)
      return null;
    if (!this.authorize(session, receipt, epoch)) return null;
    const json = JSON.stringify(receipt),
      bytes = Buffer.byteLength(json);
    if (bytes > this.limits.responseBytes || bytes > this.limits.bytes)
      return null;
    const digest = createHash("sha256").update(json).digest("hex");
    if (entry.lastDigest === digest) return entry.frames.at(-1)?.id ?? null;
    const frame = {
      id: this.id(),
      sequence: ++entry.sequence,
      observedAt: this.now(),
      state: observedStage(receipt),
      digest,
      receipt,
      bytes,
    };
    entry.frames.push(frame);
    entry.bytes += bytes;
    entry.lastDigest = digest;
    while (
      entry.frames.length > this.limits.frames ||
      entry.bytes > this.limits.bytes
    )
      entry.bytes -= entry.frames.shift().bytes;
    return frame.id;
  }
  #readable(session) {
    const entry = this.#entry(session);
    return entry && this.now() < entry.leaseUntil ? entry : null;
  }
  catalog(session) {
    const entry = this.#readable(session);
    if (!entry) return null;
    return {
      callId: entry.callId,
      expiresAt: entry.expiresAt,
      leaseUntil: entry.leaseUntil,
      frames: entry.frames.map(
        ({ receipt: _receipt, bytes: _bytes, ...metadata }) => ({
          ...metadata,
        }),
      ),
    };
  }
  frame(session, id) {
    const entry = this.#readable(session);
    const frame = entry?.frames.find((value) => value.id === id);
    return frame
      ? structuredClone({
          id: frame.id,
          observedAt: frame.observedAt,
          state: frame.state,
          receipt: frame.receipt,
          leaseUntil: entry.leaseUntil,
        })
      : null;
  }
}
