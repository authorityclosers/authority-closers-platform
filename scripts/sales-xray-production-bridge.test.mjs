import assert from "node:assert/strict";
import http from "node:http";
import test from "node:test";

import {
  createServer,
  PRODUCTION_UPSTREAM_ORIGIN,
  resolveApiRoute,
  validateBridgeConfig,
} from "./sales-xray-production-bridge.mjs";

const sessionValue = "a".repeat(43);

async function freePort() {
  const probe = http.createServer();
  await new Promise((resolve, reject) => {
    probe.once("error", reject);
    probe.listen(0, "127.0.0.1", resolve);
  });
  const port = probe.address().port;
  await new Promise((resolve, reject) => probe.close((error) => (error ? reject(error) : resolve())));
  return port;
}

function response(body, init = {}) {
  const headers = new Headers(init.headers);
  if (!headers.has("content-type")) headers.set("content-type", "application/json");
  return new Response(body, { ...init, headers });
}

function cookieFrom(responseValue) {
  const header = responseValue.headers.get("set-cookie") ?? "";
  const match = /^ac_sales_xray_dev_session=([^;]+)/.exec(header);
  assert.ok(match, `expected local session cookie, received: ${header}`);
  return `ac_sales_xray_dev_session=${match[1]}`;
}

async function startTestBridge(fetcher) {
  const port = await freePort();
  const browserOrigin = `http://salesxray.localhost:${port}`;
  const innerOrigin = "http://127.0.0.1:3116";
  const created = createServer({ browserOrigin, innerOrigin, fetcher });
  await new Promise((resolve, reject) => {
    created.server.once("error", reject);
    created.server.listen(port, "127.0.0.1", resolve);
  });
  return {
    ...created,
    port,
    browserOrigin,
    browserHost: new URL(browserOrigin).host,
    close: () => new Promise((resolve, reject) => created.server.close((error) => (error ? reject(error) : resolve()))),
  };
}

async function request(bridge, path, init = {}) {
  const headers = new Headers(init.headers);
  return fetch(`${bridge.browserOrigin}${path}`, { ...init, headers, redirect: "manual" });
}

test("production destination is pinned and Sales Xray route surface is narrow", () => {
  assert.throws(
    () => validateBridgeConfig({ upstreamOrigin: "https://api.authorityclosers.com" }),
    /pinned/,
  );
  assert.deepEqual(resolveApiRoute("GET", "/v1/me/workspaces"), {
    kind: "api",
    auth: "session",
  });
  assert.deepEqual(resolveApiRoute("GET", "/v1/conversation/acquisition/submissions/1adde9e9-42c8-4a53-bf01-31acd3a240c1/report"), { kind: "api" });
  assert.deepEqual(resolveApiRoute("GET", "/v1/admin/people/directory"), { kind: "blocked" });
  assert.deepEqual(resolveApiRoute("GET", "/v1/me/workspaces?tenant_id=other"), { kind: "blocked" });
});

test("password login maps only the opaque upstream cookie to an ephemeral local handle", async () => {
  const calls = [];
  const innerOrigin = "http://127.0.0.1:3116";
  const bridge = await startTestBridge(async (target, init = {}) => {
    calls.push({ target: new URL(target), init });
    const url = new URL(target);
    if (url.origin === innerOrigin) return response("<html>local app</html>", { headers: { "content-type": "text/html" } });
    if (url.pathname === "/v1/auth/password/login") {
      return response(JSON.stringify({ authenticated: true }), {
        status: 200,
        headers: {
          "set-cookie": `__Host-ac_session=${sessionValue}; Path=/; Secure; HttpOnly; SameSite=Lax`,
        },
      });
    }
    if (url.pathname === "/v1/auth/logout") return new Response(null, { status: 204 });
    return response(JSON.stringify({ ok: true }));
  });
  try {
    const login = await request(bridge, "/v1/auth/password/login", {
      method: "POST",
      headers: { origin: bridge.browserOrigin, "content-type": "application/json" },
      body: JSON.stringify({ email: "owner@example.invalid", password: "not-recorded" }),
    });
    assert.equal(login.status, 200);
    const localCookie = cookieFrom(login);
    assert.ok(!login.headers.get("set-cookie").includes(sessionValue));
    assert.equal(calls[0].target.origin, PRODUCTION_UPSTREAM_ORIGIN);
    assert.equal(calls[0].init.headers.get("origin"), PRODUCTION_UPSTREAM_ORIGIN);
    assert.equal(calls[0].init.headers.get("cookie"), null);
    assert.equal(calls[0].init.headers.get("authorization"), null);

    const workspaces = await request(bridge, "/v1/me/workspaces", {
      headers: { cookie: localCookie },
    });
    assert.equal(workspaces.status, 200);
    assert.equal(calls[1].init.headers.get("cookie"), `__Host-ac_session=${sessionValue}`);
    assert.equal(calls[1].init.headers.get("origin"), PRODUCTION_UPSTREAM_ORIGIN);

    const inner = await request(bridge, "/login", { headers: { cookie: localCookie } });
    assert.equal(inner.status, 200);
    assert.equal(calls[2].target.origin, innerOrigin);
    assert.equal(calls[2].init.headers.get("cookie"), null);
    assert.equal(inner.headers.get("x-ac-dev-data-mode"), "production-live");

    const logout = await request(bridge, "/v1/auth/logout", {
      method: "POST",
      headers: { origin: bridge.browserOrigin, cookie: localCookie },
    });
    assert.equal(logout.status, 204);
    assert.match(logout.headers.get("set-cookie") ?? "", /Max-Age=0/);
    assert.equal(calls[3].init.headers.get("cookie"), `__Host-ac_session=${sessionValue}`);
  } finally {
    await bridge.close();
  }
});

test("the bridge rejects copied credentials and cross-origin state changes", async () => {
  let upstreamCalls = 0;
  const bridge = await startTestBridge(async () => {
    upstreamCalls += 1;
    return response(JSON.stringify({ ok: true }));
  });
  try {
    const copiedCookie = await request(bridge, "/v1/me/workspaces", {
      headers: { cookie: `__Host-ac_session=${sessionValue}` },
    });
    assert.equal(copiedCookie.status, 400);
    const authorization = await request(bridge, "/v1/me/workspaces", {
      headers: { authorization: "Bearer never-forwarded" },
    });
    assert.equal(authorization.status, 400);
    const crossOrigin = await request(bridge, "/v1/context", {
      method: "POST",
      headers: { origin: "https://evil.example", "content-type": "application/json" },
      body: JSON.stringify({ tenant_id: "other" }),
    });
    assert.equal(crossOrigin.status, 403);
    assert.equal(upstreamCalls, 0);
  } finally {
    await bridge.close();
  }
});

test("OAuth is explicitly mapped to canonical production, never locally cookie-mapped", async () => {
  let upstreamCalls = 0;
  const bridge = await startTestBridge(async () => {
    upstreamCalls += 1;
    return response("should not be called");
  });
  try {
    const start = await request(bridge, "/v1/auth/google/start?action=authenticate&surface=admin&return_path=%2Funsafe", { headers: { accept: "text/html" } });
    assert.equal(start.status, 303);
    assert.equal(start.headers.get("location"), `${PRODUCTION_UPSTREAM_ORIGIN}/v1/auth/google/start?action=authenticate&surface=sales_xray&return_path=%2F`);
    const callback = await request(bridge, "/v1/auth/google/callback?code=opaque&state=opaque", { headers: { accept: "text/html" } });
    assert.equal(callback.status, 303);
    assert.equal(callback.headers.get("location"), `${PRODUCTION_UPSTREAM_ORIGIN}/v1/auth/google/callback?code=opaque&state=opaque`);
    assert.equal(upstreamCalls, 0);
  } finally {
    await bridge.close();
  }
});
