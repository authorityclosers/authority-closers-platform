// node --test scripts/qa/monitor/monitor.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";
import { ALLOWED_WRITES, SCREENS, isQaAccount, judge, mayLeave, reasonOf, redNote } from "./monitor.mjs";

const clean = { text: "Leads\nTo Call 4", overflow: 0, errors: [], serverErrors: [] };
const leads = SCREENS[0];

test("read-only: only reads leave, plus the QA account's own sign-in and its session's workspace", () => {
  assert.deepEqual(ALLOWED_WRITES, ["/v1/auth/password/login", "/v1/context"]);
  for (const method of ["GET", "HEAD", "OPTIONS"]) assert.ok(mayLeave(method, "/v1/lead-desk/leads"));
  assert.ok(mayLeave("POST", "/v1/auth/password/login"));
  assert.ok(mayLeave("PUT", "/v1/context"));
  for (const [method, path] of [
    ["POST", "/v1/lead-desk/leads"],
    ["PUT", "/v1/conversation/acquisition/submissions/x/source"],
    ["PATCH", "/v1/me"],
    ["DELETE", "/v1/lead-desk/leads/x"],
    ["POST", "/v1/telemetry/events"],
  ])
    assert.ok(!mayLeave(method, path), `${method} ${path}`);
});

test("only the production QA alias may run it", () => {
  assert.ok(isQaAccount("someone+ac-qa-production@authorityclosers.com"));
  assert.ok(!isQaAccount("someone@authorityclosers.com"));
  assert.ok(!isQaAccount("someone+ac-qa-production@example.com"));
  assert.ok(!isQaAccount(""));
});

test("a screen is judged by what a person would see", () => {
  assert.equal(judge(leads, clean), null);
  assert.equal(judge(leads, { ...clean, text: "Leads work inside an organisation" }), "the QA account has no organisation");
  assert.equal(judge(leads, { ...clean, text: "Loading" }), "key words missing");
  assert.equal(judge(leads, { ...clean, text: "Leads\nOwner: undefined" }), "junk on screen");
  assert.equal(judge(leads, { ...clean, overflow: 24 }), "scrolls sideways by 24 px");
  assert.equal(judge(leads, { ...clean, errors: ["x is not a function"] }), "uncaught error: x is not a function");
  assert.equal(judge(leads, { ...clean, serverErrors: ["502 on /v1/me"] }), "API 502 on /v1/me");
  assert.equal(SCREENS[0].name, "leads");
  assert.equal(SCREENS.length, 4);
});

test("a card is due only when the same failure shows twice in a row", () => {
  const red = (note, at) => ({ ok: false, at, steps: [{ name: "leads", ok: false, note }] });
  const green = { ok: true, at: "t0", steps: [{ name: "leads", ok: true }] };
  assert.equal(redNote(null, red("key words missing", "t1")), null);
  assert.equal(redNote(green, red("key words missing", "t1")), null);
  assert.equal(redNote(red("API 502 on /v1/me", "t1"), red("key words missing", "t2")), null);
  assert.match(redNote(red("key words missing", "t1"), red("key words missing", "t2")), /RED twice in a row/);
  assert.equal(redNote(red("key words missing", "t1"), green), null);
  // A number that moves (pixels, seconds) does not make it a different reason.
  assert.equal(
    reasonOf(red("scrolls sideways by 24 px").steps),
    reasonOf(red("scrolls sideways by 31 px").steps),
  );
});
