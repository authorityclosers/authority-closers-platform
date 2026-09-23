import assert from "node:assert/strict";
import test from "node:test";
import {
  progressReceipt,
  ReviewFrameStore,
  REVIEW_LIMITS,
  localReviewObservation,
} from "./sales-xray-review-store.mjs";
const call = "11111111-1111-4111-8111-111111111111";
const base = () => ({
  submission_id: call,
  recording_id: "22222222-2222-4222-8222-222222222222",
  source_sha256: "a".repeat(64),
  state: "active",
  local_state: "completed",
  has_report: false,
  automatic_progression: true,
  stages: [{ stage: "C2", state: "running" }],
});
function setup(limits = REVIEW_LIMITS) {
  let time = 100;
  const store = new ReviewFrameStore({ now: () => time, limits });
  store.start("owner", call);
  return {
    store,
    advance: (ms) => {
      time += ms;
    },
  };
}

test("idle retention expires even when the wall clock does not advance", async () => {
  const { store } = setup({ ...REVIEW_LIMITS, lifetimeMs: 10 });
  store.observe("owner", base());
  await new Promise((resolve) => setTimeout(resolve, 25));
  assert.equal(store.scope("owner"), null);
});
test("only allowlisted upstream progress facts are retained", () => {
  const receipt = progressReceipt({
    ...base(),
    token: "secret",
    transcript: "private",
    profile: {},
    stages: [{ stage: "C2", state: "running", text: "private" }],
  });
  assert.deepEqual(receipt, base());
  assert.equal(
    progressReceipt({ ...base(), stages: [{ stage: "C2", state: "guessed" }] }),
    null,
  );
});
test("a current completed read cannot manufacture old queued or running history", () => {
  const { store } = setup();
  store.observe("owner", {
    ...base(),
    has_report: true,
    stages: [{ stage: "C2", state: "completed" }],
  });
  assert.deepEqual(
    store.catalog("owner").frames.map((x) => x.state),
    ["report.available"],
  );
});
test("deduplicates repeated polls but records real A/B/A transitions", () => {
  const { store } = setup();
  const a = store.observe("owner", base());
  assert.equal(store.observe("owner", base()), a);
  store.observe("owner", {
    ...base(),
    stages: [
      { stage: "C2", state: "completed" },
      { stage: "C4", state: "running" },
    ],
  });
  store.observe("owner", base());
  assert.deepEqual(
    store.catalog("owner").frames.map((x) => x.sequence),
    [1, 2, 3],
  );
});
test("lease expiration masks history until a fresh same-source authorization", () => {
  const { store, advance } = setup();
  const id = store.observe("owner", base());
  advance(30_000);
  assert.equal(store.catalog("owner"), null);
  assert.equal(store.frame("owner", id), null);
  assert.equal(store.authorize("owner", base()), true);
  assert.ok(store.frame("owner", id));
});
test("hard lifetime cannot be extended by polling", () => {
  const { store, advance } = setup();
  store.observe("owner", base());
  advance(REVIEW_LIMITS.lifetimeMs - 1);
  store.observe("owner", base());
  advance(1);
  assert.equal(store.scope("owner"), null);
  assert.equal(store.catalog("owner"), null);
});
test("source changes, auth denial and reset purge history; sessions cannot cross-read", () => {
  const { store } = setup();
  const id = store.observe("owner", base());
  assert.equal(store.frame("other", id), null);
  assert.equal(
    store.authorize("owner", { ...base(), source_sha256: "b".repeat(64) }),
    false,
  );
  assert.equal(store.scope("owner"), null);
  store.start("owner", call);
  store.observe("owner", base());
  store.authorize("owner", null);
  assert.equal(store.scope("owner"), null);
  store.start("owner", call);
  store.observe("owner", base());
  store.reset("owner");
  assert.equal(store.scope("owner"), null);
});
test("bounded ring retains newest frames and returned objects cannot alter receipts", () => {
  const { store } = setup({ ...REVIEW_LIMITS, frames: 2 });
  const first = store.observe("owner", base());
  store.observe("owner", { ...base(), state: "held" });
  const last = store.observe("owner", base());
  assert.equal(store.frame("owner", first), null);
  assert.equal(store.catalog("owner").frames.length, 2);
  const copy = store.frame("owner", last);
  copy.receipt.stages[0].state = "failed";
  assert.equal(store.frame("owner", last).receipt.stages[0].state, "running");
});
test("new call scope resets old history and capacity is bounded", () => {
  const { store } = setup({ ...REVIEW_LIMITS, sessions: 1 });
  const id = store.observe("owner", base());
  assert.throws(() => store.start("other", call), /capacity/);
  store.start("owner", "33333333-3333-4333-8333-333333333333");
  assert.equal(store.frame("owner", id), null);
});

test("browser-local snapshots retain only allowlisted volatile control values", () => {
  const { store } = setup();
  const observation = {
    phase: "upload.file.selected",
    privacy_open: true,
    consent_checked: true,
    report_language: "hi-Deva+en",
    verification: "session-present",
    file_name: "Sales call.wav",
    file_size_bytes: 1800,
  };
  const id = store.observeLocal("owner", observation);
  assert.ok(id);
  assert.equal(store.observeLocal("owner", observation), id);
  assert.equal(store.localCatalog("owner").frames.length, 1);
  assert.equal("observation" in store.localCatalog("owner").frames[0], false);
  assert.deepEqual(store.localFrame("owner", id).observation, observation);
  const validationError = { ...observation, phase: "upload.validation.error" };
  const validationId = store.observeLocal("owner", validationError);
  assert.ok(validationId);
  assert.deepEqual(
    store.localFrame("owner", validationId).observation,
    validationError,
  );
  assert.equal(
    localReviewObservation({ ...validationError, file_size_bytes: null }),
    null,
  );
  assert.equal(
    localReviewObservation({ ...validationError, file_name: null }),
    null,
  );
  assert.equal(store.localFrame("other", id), null);
  assert.equal(
    localReviewObservation({ ...observation, file_name: "x".repeat(256) }),
    null,
  );
  assert.equal(
    localReviewObservation({ ...observation, challenge_token: "secret" }),
    null,
  );
});

test("browser-local observations expire, are not extended by call capture, and reset with the session", () => {
  const { store, advance } = setup();
  const id = store.observeLocal("owner", {
    phase: "upload.empty",
    privacy_open: false,
    consent_checked: false,
    report_language: null,
    verification: "checking",
    file_name: null,
    file_size_bytes: null,
  });
  assert.ok(id);
  store.start("owner", call);
  assert.ok(store.localFrame("owner", id));
  advance(REVIEW_LIMITS.lifetimeMs);
  assert.equal(store.localFrame("owner", id), null);
  assert.equal(store.localCatalog("owner").frames.length, 0);
  store.observeLocal("owner", {
    phase: "upload.file.selected",
    privacy_open: false,
    consent_checked: false,
    report_language: "en",
    verification: "session-present",
    file_name: "Sales call.wav",
    file_size_bytes: 1800,
  });
  store.reset("owner");
  assert.deepEqual(store.localCatalog("owner").frames, []);
});
