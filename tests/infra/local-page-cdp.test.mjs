import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { localPage } from "../../scripts/local-page-cdp.mjs";

// No browser connection: ownership must come from the creation response itself.
class FakeSocket {
  listeners = new Map();
  addEventListener(name, callback) {
    this.listeners.set(name, callback);
    if (name === "open") queueMicrotask(callback);
  }
  send(raw) {
    const { id } = JSON.parse(raw);
    queueMicrotask(() => this.listeners.get("message")({ data: JSON.stringify({ id, result: {} }) }));
  }
  close() {}
}

for (const newTab of [true, false]) {
  test(`only explicitly created tabs expose cleanup ownership: ${newTab}`, async (t) => {
    const originalFetch = globalThis.fetch;
    const originalSocket = globalThis.WebSocket;
    t.after(() => { globalThis.fetch = originalFetch; globalThis.WebSocket = originalSocket; });
    const calls = [];
    const target = {
      id: "exact-created-or-borrowed-target", type: "page",
      url: "http://learner.localhost:3100/progress", webSocketDebuggerUrl: "ws://unused.test/mock",
    };
    globalThis.fetch = async (url, options) => {
      calls.push({ url, method: options?.method });
      return { json: async () => newTab ? target : [target] };
    };
    globalThis.WebSocket = FakeSocket;
    const page = await localPage({ pathname: "/progress", newTab });
    assert.equal(page.createdTargetId, newTab ? target.id : null);
    assert.equal(calls.length, 1);
    assert.equal(calls[0].method, newTab ? "PUT" : undefined);
    assert.equal(calls[0].url, newTab
      ? "http://127.0.0.1:9327/json/new?http://learner.localhost:3100/progress"
      : "http://127.0.0.1:9327/json/list");
    await page.close();
    assert.equal(calls.length, 1, "Closing the connection never closes a user's tab");
  });
}

for (const name of ["progress", "practice-sound"]) {
  test(`${name} QA preserves earlier runs and uses exact creation ownership`, async () => {
    const source = await readFile(new URL(`../../scripts/verify-${name}-clarity-20260908.mjs`, import.meta.url), "utf8");
    assert.match(source, /const output = await mkdtemp\(/);
    assert.match(source, /const browserTargetId = page.createdTargetId/);
    assert.doesNotMatch(source, /targetsBefore|ownTargetCandidates/);
    assert.match(source, /target\.id === browserTargetId/);
  });
}

test("sound proof claims restoration only after successful readback", async () => {
  const source = await readFile(new URL("../../scripts/verify-practice-sound-clarity-20260908.mjs", import.meta.url), "utf8");
  assert.match(source, /assert\(restored, "Original local sound preferences were not restored"\)/);
  assert.doesNotMatch(source, /localStorageRestored: true/);
  assert.ok(source.indexOf("const localStorageRestored = await restorePreferences()") < source.indexOf('await writeFile(path.join(output, "proof.json")'));
  assert.match(source, /assert\(!tapDisabled/);
  assert.match(source, /if \(initial.enabled === "false"\)/);
});
