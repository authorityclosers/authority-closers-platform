import { createHash, randomUUID } from "node:crypto";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const SHA = /^[a-f0-9]{64}$/;
const LOCAL_PHASES = new Set([
  "upload.empty",
  "upload.file.selected",
  "upload.validation.error",
]);
const LOCAL_VERIFICATION = new Set([
  "checking",
  "session-present",
  "guest-challenge-required",
  "guest-challenge-complete",
]);
const REPORT_LANGUAGES = new Set(["en", "hi-Deva+en", "mr-Deva+en"]);
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
  localFrames: 128,
  sessions: 16,
  bytes: 16 * 1024 ** 2,
  localBytes: 1024 * 1024,
  responseBytes: 4 * 1024 ** 2,
  lifetimeMs: 30 * 60_000,
  leaseMs: 30_000,
});

// Browser-local observations contain display metadata only: never file content,
// upload hash, challenge token, source URL, or free-form UI text.
export function localReviewObservation(value) {
  if (
    !value ||
    typeof value !== "object" ||
    Array.isArray(value) ||
    Object.keys(value).length !== 7 ||
    !LOCAL_PHASES.has(value.phase) ||
    typeof value.privacy_open !== "boolean" ||
    typeof value.consent_checked !== "boolean" ||
    !(
      value.report_language === null ||
      REPORT_LANGUAGES.has(value.report_language)
    ) ||
    !LOCAL_VERIFICATION.has(value.verification) ||
    !(
      value.file_name === null ||
      (typeof value.file_name === "string" &&
        value.file_name.length > 0 &&
        value.file_name.length <= 255 &&
        !/[\u0000-\u001f\u007f]/.test(value.file_name))
    ) ||
    !(
      value.file_size_bytes === null ||
      (Number.isSafeInteger(value.file_size_bytes) &&
        value.file_size_bytes > 0 &&
        value.file_size_bytes <= 32 * 1024 ** 2)
    ) ||
    (value.phase === "upload.file.selected" &&
      (value.file_name === null || value.file_size_bytes === null)) ||
    (value.phase === "upload.empty" &&
      (value.file_name !== null || value.file_size_bytes !== null)) ||
    (value.phase === "upload.validation.error" &&
      (value.file_name === null) !== (value.file_size_bytes === null))
  )
    return null;
  return {
    phase: value.phase,
    privacy_open: value.privacy_open,
    consent_checked: value.consent_checked,
    report_language: value.report_language,
    verification: value.verification,
    file_name: value.file_name,
    file_size_bytes: value.file_size_bytes,
  };
}

export function localReviewLabel(value) {
  const observation = localReviewObservation(value);
  if (!observation) return null;
  const phase = {
    "upload.empty": "Upload · empty",
    "upload.file.selected": "Upload · actual file selected",
    "upload.validation.error": "Upload · local validation error",
  }[observation.phase];
  const file = observation.file_name
    ? `${observation.file_name} · ${(observation.file_size_bytes / 1048576).toFixed(1)} MB`
    : "";
  const privacy = observation.privacy_open
    ? "privacy details open"
    : "privacy details closed";
  const consent = observation.consent_checked
    ? "consent checkbox checked locally"
    : "consent checkbox unchecked";
  const language = observation.report_language
    ? `report language ${observation.report_language}`
    : "report language unavailable";
  const verification = {
    checking: "verification checking",
    "session-present": "account or guest session present",
    "guest-challenge-required": "guest challenge required",
    "guest-challenge-complete": "guest challenge completed locally",
  }[observation.verification];
  return [phase, file, privacy, consent, language, verification]
    .filter(Boolean)
    .join(" · ");
}

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
  #localSessions = new Map();
  constructor({
    now = Date.now,
    id = randomUUID,
    limits = REVIEW_LIMITS,
  } = {}) {
    this.now = now;
    this.id = id;
    this.limits = limits;
  }
  resetCall(session) {
    clearTimeout(this.#sessions.get(session)?.expiryTimer);
    this.#sessions.delete(session);
  }
  resetLocal(session) {
    clearTimeout(this.#localSessions.get(session)?.expiryTimer);
    this.#localSessions.delete(session);
  }
  reset(session) {
    this.resetCall(session);
    this.resetLocal(session);
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
    this.resetCall(session);
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
  #localEntry(session) {
    const entry = this.#localSessions.get(session);
    if (entry && this.now() >= entry.expiresAt) {
      this.resetLocal(session);
      return null;
    }
    return entry ?? null;
  }
  observeLocal(session, value) {
    if (typeof session !== "string" || !session) return null;
    const observation = localReviewObservation(value);
    if (!observation) return null;
    let entry = this.#localEntry(session);
    if (!entry) {
      for (const key of this.#localSessions.keys()) this.#localEntry(key);
      if (this.#localSessions.size >= this.limits.sessions) return null;
      entry = {
        expiresAt: this.now() + this.limits.lifetimeMs,
        frames: [],
        bytes: 0,
        sequence: 0,
        lastDigest: null,
      };
      entry.expiryTimer = setTimeout(() => {
        if (this.#localSessions.get(session) === entry)
          this.resetLocal(session);
      }, this.limits.lifetimeMs);
      entry.expiryTimer.unref();
      this.#localSessions.set(session, entry);
    }
    const json = JSON.stringify(observation);
    const bytes = Buffer.byteLength(json);
    if (bytes > this.limits.localBytes) return null;
    const digest = createHash("sha256").update(json).digest("hex");
    if (entry.lastDigest === digest) return entry.frames.at(-1)?.id ?? null;
    const frame = {
      id: this.id(),
      sequence: ++entry.sequence,
      observedAt: this.now(),
      state: observation.phase,
      label: localReviewLabel(observation),
      observation,
      digest,
      bytes,
    };
    entry.frames.push(frame);
    entry.bytes += bytes;
    entry.lastDigest = digest;
    while (
      entry.frames.length > this.limits.localFrames ||
      entry.bytes > this.limits.localBytes
    )
      entry.bytes -= entry.frames.shift().bytes;
    return frame.id;
  }
  localCatalog(session) {
    const entry = this.#localEntry(session);
    return {
      expiresAt: entry?.expiresAt ?? null,
      frames: (entry?.frames ?? []).map(
        ({
          observation: _observation,
          digest: _digest,
          bytes: _bytes,
          ...metadata
        }) => ({
          ...metadata,
        }),
      ),
    };
  }
  localFrame(session, id) {
    const entry = this.#localEntry(session);
    const frame = entry?.frames.find((value) => value.id === id);
    return frame
      ? structuredClone({
          id: frame.id,
          sequence: frame.sequence,
          observedAt: frame.observedAt,
          state: frame.state,
          label: frame.label,
          observation: frame.observation,
          expiresAt: entry.expiresAt,
        })
      : null;
  }
}
