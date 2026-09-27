import assert from "node:assert/strict";
import http from "node:http";
import test from "node:test";

import {
  createServer,
  MAX_REVIEW_REQUEST_BODY_BYTES,
  PRODUCTION_UPSTREAM_ORIGIN,
} from "./sales-xray-production-bridge.mjs";
import { REVIEW_LIMITS } from "./sales-xray-review-store.mjs";
import { createReviewService } from "./sales-xray-review-service.mjs";

const callId = "11111111-1111-4111-8111-111111111111";
const otherCallId = "33333333-3333-4333-8333-333333333333";
const recordingId = "22222222-2222-4222-8222-222222222222";
const sourceHash = "a".repeat(64);

test("browser-local observation links are session scoped and never fetch the VPS", async () => {
  let upstreamReads = 0;
  const service = createReviewService({
    upstreamOrigin: PRODUCTION_UPSTREAM_ORIGIN,
    fetcher: async () => {
      upstreamReads += 1;
      throw new Error("local observation must not read the upstream API");
    },
  });
  const observation = {
    phase: "upload.file.selected",
    privacy_open: true,
    consent_checked: true,
    report_language: "mr-Deva+en",
    verification: "session-present",
    file_name: "Actual call.wav",
    file_size_bytes: 24576,
  };
  const captured = await service.handle({
    pathname: "/__review/api/local/observe",
    search: "",
    method: "POST",
    session: "owner",
    headers: {},
    body: { observation },
  });
  assert.equal(captured.status, 200);
  const catalog = await service.handle({
    pathname: "/__review/api/local/catalog",
    search: "",
    method: "GET",
    session: "owner",
    headers: {},
  });
  assert.equal(catalog.status, 200);
  assert.equal(catalog.body.frames.length, 1);
  const id = catalog.body.frames[0].id;
  const frame = await service.handle({
    pathname: `/__review/api/local/frames/${id}`,
    search: "",
    method: "GET",
    session: "owner",
    headers: {},
  });
  assert.equal(frame.status, 200);
  assert.deepEqual(frame.body.observation, observation);
  assert.equal(
    (
      await service.handle({
        pathname: `/__review/api/local/frames/${id}`,
        search: "",
        method: "GET",
        session: "other",
        headers: {},
      })
    ).status,
    404,
  );
  assert.equal(
    (
      await service.handle({
        pathname: "/__review/api/local/observe",
        search: "",
        method: "POST",
        session: "owner",
        headers: {},
        body: { observation: { ...observation, filename: "private.wav" } },
      })
    ).status,
    400,
  );
  assert.equal(upstreamReads, 0);
});

test("a failed older access read cannot erase a newer capture", async () => {
  let rejectOld;
  const old = new Promise((_, reject) => {
    rejectOld = reject;
  });
  let reads = 0;
  const service = createReviewService({
    upstreamOrigin: PRODUCTION_UPSTREAM_ORIGIN,
    fetcher: async () =>
      ++reads === 1
        ? old
        : new Response(
            JSON.stringify(progress({ submission_id: otherCallId })),
            { headers: { "content-type": "application/json" } },
          ),
  });
  const request = (call_id) =>
    service.handle({
      pathname: "/__review/api/start",
      search: "",
      method: "POST",
      session: "owner",
      headers: {},
      body: { call_id },
    });
  const pending = request(callId);
  assert.equal((await request(otherCallId)).status, 200);
  const epoch = service.store.scope("owner").epoch;
  rejectOld(new Error("old network timeout"));
  assert.equal((await pending).status, 503);
  assert.equal(service.store.scope("owner").epoch, epoch);
  assert.equal(service.store.catalog("owner").callId, otherCallId);
  service.store.reset("owner");
});
const sessionValue = "a".repeat(43);

function progress(overrides = {}) {
  return {
    submission_id: callId,
    recording_id: recordingId,
    source_sha256: sourceHash,
    state: "active",
    local_state: "completed",
    has_report: false,
    automatic_progression: true,
    stages: [{ stage: "C2", state: "running" }],
    ...overrides,
  };
}

function upstreamResponse(value, status = 200, headers = {}) {
  const responseHeaders = new Headers(headers);
  if (!responseHeaders.has("content-type"))
    responseHeaders.set("content-type", "application/json");
  return new Response(
    value === null || typeof value === "string" ? value : JSON.stringify(value),
    { status, headers: responseHeaders },
  );
}

async function freePort() {
  const probe = http.createServer();
  await new Promise((resolve, reject) => {
    probe.once("error", reject);
    probe.listen(0, "127.0.0.1", resolve);
  });
  const port = probe.address().port;
  await new Promise((resolve, reject) =>
    probe.close((error) => (error ? reject(error) : resolve())),
  );
  return port;
}

async function startBridge(fetcher, { analysisReadOnly = true } = {}) {
  const port = await freePort();
  const browserOrigin = `http://salesxray.localhost:${port}`;
  const created = createServer({
    browserOrigin,
    innerOrigin: "http://127.0.0.1:3116",
    fetcher,
    analysisReadOnly,
  });
  await new Promise((resolve, reject) => {
    created.server.once("error", reject);
    created.server.listen(port, "127.0.0.1", resolve);
  });
  return {
    ...created,
    browserOrigin,
    browserHost: new URL(browserOrigin).host,
    close: () =>
      new Promise((resolve, reject) =>
        created.server.close((error) => (error ? reject(error) : resolve())),
      ),
  };
}

function request(bridge, pathname, init = {}) {
  const headers = new Headers(init.headers);
  return fetch(`${bridge.browserOrigin}${pathname}`, {
    ...init,
    headers,
    redirect: "manual",
  });
}

function cookieFrom(response) {
  const value = /^ac_sales_xray_dev_session=([^;]+)/.exec(
    response.headers.get("set-cookie") ?? "",
  );
  assert.ok(value, "login should return an opaque local session handle");
  return `ac_sales_xray_dev_session=${value[1]}`;
}

function handleFrom(cookie) {
  return cookie.slice("ac_sales_xray_dev_session=".length);
}

async function login(bridge, cookie) {
  const response = await request(bridge, "/v1/auth/password/login", {
    method: "POST",
    headers: {
      origin: bridge.browserOrigin,
      "content-type": "application/json",
      ...(cookie ? { cookie } : {}),
    },
    body: JSON.stringify({
      email: "owner@example.invalid",
      password: "synthetic",
    }),
  });
  assert.equal(response.status, 200);
  return cookieFrom(response);
}

async function startCapture(bridge, cookie, id = callId) {
  return request(bridge, "/__review/api/start", {
    method: "POST",
    headers: {
      origin: bridge.browserOrigin,
      cookie,
      "content-type": "application/json",
    },
    body: JSON.stringify({ call_id: id }),
  });
}

test("review routes are opt-in, exact, local-only, and hardened", async () => {
  const upstreamCalls = [];
  const fetcher = async (target, init = {}) => {
    upstreamCalls.push({ url: new URL(target), init });
    return upstreamResponse({ ok: true });
  };
  const normal = await startBridge(fetcher, { analysisReadOnly: false });
  try {
    assert.equal((await request(normal, "/__review/")).status, 404);
    assert.equal((await request(normal, "/__review/api/catalog")).status, 404);
    assert.equal(
      (await request(normal, "/__review/api/local/catalog")).status,
      404,
    );
    assert.equal(upstreamCalls.length, 0, "disabled review paths never proxy");
  } finally {
    await normal.close();
  }

  const bridge = await startBridge(fetcher);
  try {
    const page = await request(bridge, "/__review/");
    assert.equal(page.status, 200);
    assert.match(
      page.headers.get("content-security-policy"),
      /frame-ancestors 'none'/,
    );
    assert.equal(page.headers.get("x-frame-options"), "DENY");
    assert.equal(page.headers.get("cache-control"), "no-store");
    const controlsHtml = await page.text();
    assert.match(controlsHtml, /State workbench/);
    assert.match(
      controlsHtml,
      /Inspect the mounted app using paused local examples or observations from this browser and calls you own/,
    );
    assert.match(controlsHtml, /Local test states/);

    const script = await request(bridge, "/__review/controls.js");
    assert.equal(script.status, 200);
    assert.match(
      script.headers.get("content-security-policy"),
      /script-src 'self'/,
    );
    assert.equal(script.headers.get("x-frame-options"), "DENY");
    assert.equal(script.headers.get("cache-control"), "no-store");

    for (const path of [
      "/__review/?cache=1",
      "/__review/controls.js?v=1",
      "/__review/unlisted.js",
    ])
      assert.equal((await request(bridge, path)).status, 404, path);
    assert.equal(
      (
        await request(bridge, "/__review/", {
          method: "HEAD",
          headers: { origin: bridge.browserOrigin },
        })
      ).status,
      405,
    );
    assert.equal(
      (
        await request(bridge, "/__review/controls.js", {
          method: "POST",
          headers: { origin: bridge.browserOrigin },
        })
      ).status,
      405,
    );
    assert.equal(
      (
        await request(bridge, "/__review/api/catalog", {
          method: "POST",
          headers: { origin: bridge.browserOrigin },
        })
      ).status,
      404,
    );
    assert.equal((await request(bridge, "/__review/api/reset")).status, 404);
    assert.equal((await request(bridge, "/__review/api/catalog")).status, 401);
    assert.equal(
      (await request(bridge, "/__review/api/local/catalog")).status,
      401,
    );

    const crossOrigin = await request(bridge, "/__review/api/start", {
      method: "POST",
      headers: {
        origin: "http://attacker.invalid",
        "content-type": "application/json",
      },
      body: JSON.stringify({ call_id: callId }),
    });
    assert.equal(crossOrigin.status, 403);
    const credential = await request(bridge, "/__review/", {
      headers: { authorization: "Bearer never-forwarded" },
    });
    assert.equal(credential.status, 400);
    assert.equal(
      upstreamCalls.length,
      0,
      "anonymous and rejected requests do not fetch upstream",
    );
  } finally {
    await bridge.close();
  }
});

test("capture reads only the selected authenticated submission and blocks analysis writes", async () => {
  const upstreamCalls = [];
  const bridge = await startBridge(async (target, init = {}) => {
    const url = new URL(target);
    upstreamCalls.push({ url, init });
    if (url.pathname === "/v1/auth/password/login")
      return upstreamResponse({ authenticated: true }, 200, {
        "set-cookie": `__Host-ac_session=${sessionValue}; Path=/; Secure; HttpOnly; SameSite=Lax`,
      });
    const submission =
      /^\/v1\/conversation\/acquisition\/submissions\/([0-9a-f-]{36})$/.exec(
        url.pathname,
      );
    if (submission)
      return upstreamResponse(progress({ submission_id: submission[1] }));
    return upstreamResponse({ ok: true });
  });
  try {
    const cookie = await login(bridge);
    const beforeWrite = upstreamCalls.length;
    const quote = await request(bridge, "/v1/conversation/intake/quote", {
      method: "POST",
      headers: {
        origin: bridge.browserOrigin,
        cookie,
        "content-type": "application/json",
      },
      body: "{}",
    });
    assert.equal(quote.status, 404);
    assert.equal(
      upstreamCalls.length,
      beforeWrite,
      "analysis mutations are denied before fetch",
    );

    const start = await startCapture(bridge, cookie);
    assert.equal(start.status, 200);
    const catalog = await start.json();
    assert.equal(catalog.callId, callId);
    assert.equal(catalog.frames.length, 1);
    const upstream = upstreamCalls.at(-1);
    assert.equal(upstream.url.origin, PRODUCTION_UPSTREAM_ORIGIN);
    assert.equal(
      upstream.url.pathname,
      `/v1/conversation/acquisition/submissions/${callId}`,
    );
    assert.equal(upstream.init.method, "GET");
    assert.equal(
      upstream.init.headers.get("origin"),
      PRODUCTION_UPSTREAM_ORIGIN,
    );
    assert.equal(
      upstream.init.headers.get("cookie"),
      `__Host-ac_session=${sessionValue}`,
    );
    assert.equal(upstream.init.headers.get("authorization"), null);
    assert.equal(upstream.init.redirect, "manual");
    assert.equal(upstream.init.credentials, "omit");
    assert.equal(upstream.init.cache, "no-store");

    const reset = await request(bridge, "/__review/api/reset", {
      method: "POST",
      headers: {
        origin: bridge.browserOrigin,
        cookie,
        "content-type": "application/json",
      },
      body: "{}",
    });
    assert.equal(reset.status, 200);
    assert.deepEqual(await reset.json(), { reset: true });
    assert.equal(
      upstreamCalls.length,
      beforeWrite + 1,
      "reset never makes an upstream request",
    );
  } finally {
    await bridge.close();
  }
});

test("browser-local observation capture and inspection never reach the upstream API", async () => {
  const upstreamCalls = [];
  const bridge = await startBridge(async (target, init = {}) => {
    const url = new URL(target);
    upstreamCalls.push({ path: url.pathname, method: init.method });
    if (url.pathname === "/v1/auth/password/login")
      return upstreamResponse({ authenticated: true }, 200, {
        "set-cookie": `__Host-ac_session=${sessionValue}; Path=/; Secure; HttpOnly; SameSite=Lax`,
      });
    return upstreamResponse({ ok: true });
  });
  try {
    const cookie = await login(bridge);
    assert.equal(upstreamCalls.length, 1);
    const observation = {
      phase: "upload.file.selected",
      privacy_open: true,
      consent_checked: false,
      report_language: "en",
      verification: "session-present",
      file_name: "Review sample.wav",
      file_size_bytes: 1024,
    };
    const captured = await request(bridge, "/__review/api/local/observe", {
      method: "POST",
      headers: {
        origin: bridge.browserOrigin,
        cookie,
        "content-type": "application/json",
      },
      body: JSON.stringify({ observation }),
    });
    assert.equal(captured.status, 200);
    const { id } = await captured.json();
    const catalog = await request(bridge, "/__review/api/local/catalog", {
      headers: { cookie },
    });
    assert.equal(catalog.status, 200);
    const listed = await catalog.json();
    assert.equal(listed.frames.length, 1);
    assert.equal(listed.frames[0].id, id);
    assert.equal("observation" in listed.frames[0], false);
    const frame = await request(bridge, `/__review/api/local/frames/${id}`, {
      headers: { cookie },
    });
    assert.equal(frame.status, 200);
    assert.deepEqual((await frame.json()).observation, observation);
    assert.equal(upstreamCalls.length, 1);

    const invalid = await request(bridge, "/__review/api/local/observe", {
      method: "POST",
      headers: {
        origin: bridge.browserOrigin,
        cookie,
        "content-type": "application/json",
      },
      body: JSON.stringify({
        observation: { ...observation, file_contents: "private audio bytes" },
      }),
    });
    assert.equal(invalid.status, 400);
    assert.equal(upstreamCalls.length, 1);

    const cleared = await request(bridge, "/__review/api/reset", {
      method: "POST",
      headers: {
        origin: bridge.browserOrigin,
        cookie,
        "content-type": "application/json",
      },
      body: "{}",
    });
    assert.equal(cleared.status, 200);
    assert.deepEqual(
      await (
        await request(bridge, "/__review/api/local/catalog", {
          headers: { cookie },
        })
      ).json(),
      { expiresAt: null, frames: [] },
    );
    assert.equal(upstreamCalls.length, 1);
  } finally {
    await bridge.close();
  }
});

test("login and logout purge review frames before and after identity changes", async () => {
  let bridge;
  let activeHandle;
  const bridgeStore = () => bridge.bridge.reviewService.store;
  bridge = await startBridge(async (target) => {
    const url = new URL(target);
    if (url.pathname === "/v1/auth/password/login") {
      assert.equal(
        activeHandle ? bridgeStore().scope(activeHandle) : null,
        null,
        "login starts only after existing review history is purged",
      );
      return upstreamResponse({ authenticated: true }, 200, {
        "set-cookie": `__Host-ac_session=${sessionValue}; Path=/; Secure; HttpOnly; SameSite=Lax`,
      });
    }
    if (url.pathname === "/v1/auth/logout") {
      assert.equal(bridgeStore().scope(activeHandle), null);
      return new Response(null, { status: 204 });
    }
    if (url.pathname === `/v1/conversation/acquisition/submissions/${callId}`)
      return upstreamResponse(progress());
    return upstreamResponse({ ok: true });
  });
  try {
    const firstCookie = await login(bridge);
    const firstHandle = handleFrom(firstCookie);
    activeHandle = firstHandle;
    assert.equal((await startCapture(bridge, firstCookie)).status, 200);

    const secondCookie = await login(bridge, firstCookie);
    const secondHandle = handleFrom(secondCookie);
    assert.notEqual(secondHandle, firstHandle);
    assert.equal(bridgeStore().scope(firstHandle), null);
    assert.equal(bridgeStore().scope(secondHandle), null);

    activeHandle = secondHandle;
    assert.equal((await startCapture(bridge, secondCookie)).status, 200);
    const logout = await request(bridge, "/v1/auth/logout", {
      method: "POST",
      headers: {
        origin: bridge.browserOrigin,
        cookie: secondCookie,
      },
    });
    assert.equal(logout.status, 204);
    assert.equal(bridgeStore().scope(secondHandle), null);
    assert.match(logout.headers.get("set-cookie") ?? "", /Max-Age=0/);
  } finally {
    await bridge.close();
  }
});

test("review frames stay session-bound and are purged on source change or revocation", async () => {
  let source = sourceHash;
  let denied = false;
  let workspaceDenied = false;
  const bridge = await startBridge(async (target) => {
    const url = new URL(target);
    if (url.pathname === "/v1/auth/password/login")
      return upstreamResponse({ authenticated: true }, 200, {
        "set-cookie": `__Host-ac_session=${sessionValue}; Path=/; Secure; HttpOnly; SameSite=Lax`,
      });
    if (url.pathname === `/v1/conversation/acquisition/submissions/${callId}`) {
      if (denied) return upstreamResponse({ detail: "denied" }, 403);
      return upstreamResponse(progress({ source_sha256: source }));
    }
    if (url.pathname === "/v1/me/workspaces" && workspaceDenied)
      return upstreamResponse({ detail: "membership denied" }, 403);
    return upstreamResponse({ ok: true });
  });
  try {
    const firstCookie = await login(bridge);
    const secondCookie = await login(bridge);
    const started = await startCapture(bridge, firstCookie);
    assert.equal(started.status, 200);
    const firstCatalog = await started.json();
    const frameId = firstCatalog.frames[0].id;

    const crossSession = await request(
      bridge,
      `/__review/api/frames/${frameId}`,
      {
        headers: { cookie: secondCookie },
      },
    );
    assert.equal(crossSession.status, 404);
    const ownFrame = await request(bridge, `/__review/api/frames/${frameId}`, {
      headers: { cookie: firstCookie },
    });
    assert.equal(ownFrame.status, 200);

    source = "b".repeat(64);
    const changed = await request(bridge, "/__review/api/catalog", {
      headers: { cookie: firstCookie },
    });
    assert.equal(changed.status, 403);
    assert.equal(
      (
        await request(bridge, "/__review/api/catalog", {
          headers: { cookie: firstCookie },
        })
      ).status,
      404,
      "source changes purge rather than reconstruct prior history",
    );

    source = sourceHash;
    assert.equal((await startCapture(bridge, firstCookie)).status, 200);
    workspaceDenied = true;
    const membershipDenied = await request(bridge, "/v1/me/workspaces", {
      headers: { cookie: firstCookie },
    });
    assert.equal(membershipDenied.status, 403);
    assert.equal(
      bridge.bridge.reviewService.store.scope(handleFrom(firstCookie)),
      null,
      "a current membership denial purges its captured epoch",
    );
    assert.equal(
      (
        await request(bridge, "/__review/api/catalog", {
          headers: { cookie: firstCookie },
        })
      ).status,
      404,
    );
    workspaceDenied = false;
    assert.equal((await startCapture(bridge, firstCookie)).status, 200);
    denied = true;
    const revoked = await request(bridge, "/__review/api/catalog", {
      headers: { cookie: firstCookie },
    });
    assert.equal(revoked.status, 403);
    assert.equal(
      (
        await request(bridge, "/__review/api/catalog", {
          headers: { cookie: firstCookie },
        })
      ).status,
      404,
      "a failed live access read purges captured history",
    );
  } finally {
    await bridge.close();
  }
});

test("review bodies and upstream progress responses are bounded", async () => {
  let hugeResponse = false;
  const upstreamCalls = [];
  const bridge = await startBridge(async (target, init = {}) => {
    const url = new URL(target);
    upstreamCalls.push({ url, init });
    if (url.pathname === "/v1/auth/password/login")
      return upstreamResponse({ authenticated: true }, 200, {
        "set-cookie": `__Host-ac_session=${sessionValue}; Path=/; Secure; HttpOnly; SameSite=Lax`,
      });
    if (url.pathname === `/v1/conversation/acquisition/submissions/${callId}`) {
      if (hugeResponse)
        return new Response("{" + " ".repeat(REVIEW_LIMITS.responseBytes), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      return upstreamResponse(progress());
    }
    return upstreamResponse({ ok: true });
  });
  try {
    const cookie = await login(bridge);
    const beforeOversize = upstreamCalls.length;
    const oversized = await request(bridge, "/__review/api/start", {
      method: "POST",
      headers: {
        origin: bridge.browserOrigin,
        cookie,
        "content-type": "application/json",
      },
      body: "x".repeat(MAX_REVIEW_REQUEST_BODY_BYTES + 1),
    });
    assert.equal(oversized.status, 413);
    assert.equal(upstreamCalls.length, beforeOversize);

    assert.equal((await startCapture(bridge, cookie)).status, 200);
    hugeResponse = true;
    const bounded = await request(bridge, "/__review/api/catalog", {
      headers: { cookie },
    });
    assert.equal(bounded.status, 403);
    assert.equal(
      (await request(bridge, "/__review/api/catalog", { headers: { cookie } }))
        .status,
      404,
    );
  } finally {
    await bridge.close();
  }
});

test("context changes purge before and after, block concurrent review, and invalidate stale reads", async () => {
  let bridge;
  let holdNextRead = false;
  let releaseRead;
  let readStarted;
  const heldRead = new Promise((resolve) => {
    releaseRead = resolve;
  });
  const reviewReadStarted = new Promise((resolve) => {
    readStarted = resolve;
  });
  let holdContext = false;
  let releaseContext;
  let contextStarted;
  const heldContext = new Promise((resolve) => {
    releaseContext = resolve;
  });
  const contextRequestStarted = new Promise((resolve) => {
    contextStarted = resolve;
  });
  const bridgeRef = () => bridge.bridge.reviewService.store;
  bridge = await startBridge(async (target) => {
    const url = new URL(target);
    if (url.pathname === "/v1/auth/password/login")
      return upstreamResponse({ authenticated: true }, 200, {
        "set-cookie": `__Host-ac_session=${sessionValue}; Path=/; Secure; HttpOnly; SameSite=Lax`,
      });
    if (url.pathname === `/v1/conversation/acquisition/submissions/${callId}`) {
      if (holdNextRead) {
        holdNextRead = false;
        readStarted();
        return heldRead;
      }
      return upstreamResponse(progress());
    }
    if (url.pathname === "/v1/context") {
      contextStarted();
      return heldContext;
    }
    return upstreamResponse({ ok: true });
  });
  try {
    const cookie = await login(bridge);
    const localHandle = handleFrom(cookie);
    assert.equal((await startCapture(bridge, cookie)).status, 200);
    const priorEpoch = bridgeRef().scope(localHandle).epoch;

    holdNextRead = true;
    const staleRead = request(bridge, "/__review/api/catalog", {
      headers: { cookie },
    });
    await reviewReadStarted;

    const contextChange = request(bridge, "/v1/context", {
      method: "POST",
      headers: {
        origin: bridge.browserOrigin,
        cookie,
        "content-type": "application/json",
      },
      body: JSON.stringify({ workspace_id: "synthetic-workspace" }),
    });
    await contextRequestStarted;
    assert.equal(
      bridgeRef().scope(localHandle),
      null,
      "context purges before upstream completes",
    );
    const whileTransitioning = await request(bridge, "/__review/api/catalog", {
      headers: { cookie },
    });
    assert.equal(whileTransitioning.status, 409);

    releaseContext(upstreamResponse({ ok: true }));
    assert.equal((await contextChange).status, 200);
    assert.equal(
      bridgeRef().scope(localHandle),
      null,
      "context remains purged afterward",
    );

    releaseRead(upstreamResponse(progress()));
    assert.equal(
      (await staleRead).status,
      403,
      "an old epoch cannot restore a cleared capture",
    );
    assert.equal(bridgeRef().scope(localHandle), null);
    assert.notEqual(bridgeRef().scope(localHandle)?.epoch, priorEpoch);
  } finally {
    releaseContext?.(upstreamResponse({ ok: true }));
    releaseRead?.(upstreamResponse(progress()));
    await bridge.close();
  }
});

test("a late membership denial cannot purge a newer capture epoch", async () => {
  let bridge;
  let holdDenial = false;
  let releaseDenial;
  let denialStarted;
  const heldDenial = new Promise((resolve) => {
    releaseDenial = resolve;
  });
  const denialRequestStarted = new Promise((resolve) => {
    denialStarted = resolve;
  });
  bridge = await startBridge(async (target) => {
    const url = new URL(target);
    if (url.pathname === "/v1/auth/password/login")
      return upstreamResponse({ authenticated: true }, 200, {
        "set-cookie": `__Host-ac_session=${sessionValue}; Path=/; Secure; HttpOnly; SameSite=Lax`,
      });
    if (url.pathname === "/v1/me/workspaces" && holdDenial) {
      holdDenial = false;
      denialStarted();
      return heldDenial;
    }
    const submission =
      /^\/v1\/conversation\/acquisition\/submissions\/([0-9a-f-]{36})$/.exec(
        url.pathname,
      );
    if (submission)
      return upstreamResponse(progress({ submission_id: submission[1] }));
    return upstreamResponse({ ok: true });
  });
  try {
    const cookie = await login(bridge);
    const localHandle = handleFrom(cookie);
    assert.equal((await startCapture(bridge, cookie)).status, 200);
    const oldEpoch = bridge.bridge.reviewService.store.scope(localHandle).epoch;

    holdDenial = true;
    const denial = request(bridge, "/v1/me/workspaces", {
      headers: { cookie },
    });
    await denialRequestStarted;
    assert.equal((await startCapture(bridge, cookie, otherCallId)).status, 200);
    const newEpoch = bridge.bridge.reviewService.store.scope(localHandle).epoch;
    assert.notEqual(newEpoch, oldEpoch);

    releaseDenial(upstreamResponse({ detail: "membership revoked" }, 403));
    assert.equal((await denial).status, 403);
    assert.equal(
      bridge.bridge.reviewService.store.scope(localHandle).epoch,
      newEpoch,
    );
    const stillAvailable = await request(bridge, "/__review/api/catalog", {
      headers: { cookie },
    });
    assert.equal(stillAvailable.status, 200);
    assert.equal((await stillAvailable.json()).callId, otherCallId);
  } finally {
    releaseDenial?.(upstreamResponse({ detail: "membership revoked" }, 403));
    await bridge.close();
  }
});

test("the loopback check runs before any review handler or upstream request", async () => {
  let upstreamCalls = 0;
  const created = createServer({
    analysisReadOnly: true,
    fetcher: async () => {
      upstreamCalls += 1;
      return upstreamResponse({ ok: true });
    },
  });
  const fakeResponse = {
    headersSent: false,
    writeHead(status, headers) {
      this.status = status;
      this.headers = headers;
      this.headersSent = true;
    },
    end(body) {
      this.body = body?.toString() ?? "";
    },
  };
  await created.bridge.handle(
    {
      socket: { remoteAddress: "192.0.2.44" },
      headers: { host: "salesxray.localhost:3016" },
      method: "GET",
      url: "/__review/",
    },
    fakeResponse,
  );
  assert.equal(fakeResponse.status, 403);
  assert.equal(upstreamCalls, 0);
});
