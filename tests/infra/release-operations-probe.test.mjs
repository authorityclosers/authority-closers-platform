import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import test from "node:test";
import { verifyOperationsSurface } from "../../scripts/verify-release-operations-probe.mjs";

function fixture(surface, change = () => {}) {
  let clock = 0;
  const requests = [];
  const phases = [];
  const get = async (path, options) => {
    requests.push({ path, options });
    const port = surface === "admin" ? 3001 : 3002;
    let response =
      options.wireHost === "untrusted.invalid"
        ? {
            status: 421,
            headers: { "cache-control": "no-store" },
            body: "",
          }
        : {
            status: 307,
            headers: {
              "cache-control": "no-store",
              location: `https://${options.wireHost}/login`,
            },
            body: "",
          };
    if (path === "/healthz" && options.wireHost === `127.0.0.1:${port}`)
      response = {
        status: 200,
        headers: { "cache-control": "no-store" },
        body: JSON.stringify({
          status: "ok",
          service: `authority-closers-${surface}`,
        }),
      };
    if (path === "/login")
      response = {
        status: 200,
        headers: { "content-type": "text/html; charset=utf-8" },
        body: '<form method="post"><input type="password" disabled=""/><link href="/_next/static/main.css"/><script src="/_next/static/main.js"></script></form>',
      };
    if (path.startsWith("/_next/static/"))
      response = {
        status: 200,
        headers: {
          "content-type": path.endsWith(".css")
            ? "text/css"
            : "application/javascript",
        },
        body: "compiled-output",
      };
    if (path === "/v1/me")
      response = {
        status: surface === "admin" ? 403 : 404,
        headers: { "cache-control": "no-store" },
        body: "unavailable",
      };
    if (
      surface === "admin" &&
      (path.startsWith("/studio/programs") || path.startsWith("/catalog"))
    )
      response =
        options.method === "POST"
          ? {
              status: 405,
              headers: { "cache-control": "no-store", allow: "GET, HEAD" },
              body: "",
            }
          : {
              status: 302,
              headers: {
                "cache-control": "no-store",
                location: "https://coach.authorityclosers.com/studio/programs",
              },
              body: "",
            };
    change(response, path, options);
    return response;
  };
  return {
    requests,
    phases,
    get,
    now: () => clock,
    delay: async (time) => {
      clock += time;
    },
    phase: (value) => {
      phases.push(value);
    },
  };
}

for (const surface of ["admin", "coach"]) {
  test(`${surface}: requires actual healthy/login/compiled-asset responses without auth claims`, async () => {
    const f = fixture(surface);
    const proof = await verifyOperationsSurface(surface, f);
    assert.equal(proof.api_auth_exercised, false);
    assert.equal(proof.compiled_assets, 2);
    assert.ok(proof.checks.includes("compiled-js-css"));
    assert.deepEqual(f.phases, [
      "bootstrap",
      "readiness",
      "public-health",
      "forwarded-health",
      "anonymous-pages",
      "production-login",
      "compiled-assets",
      "api-denial",
      ...(surface === "admin" ? ["admin-coach-redirect"] : []),
    ]);
    assert.equal(
      proof.checks.includes("anonymous-api-denied"),
      surface === "admin",
    );
    assert.equal(
      proof.checks.includes("development-api-unavailable"),
      surface === "coach",
    );
    assert.ok(f.requests.some(({ path }) => path === "/_next/static/main.js"));
    assert.ok(f.requests.some(({ path }) => path === "/_next/static/main.css"));
    assert.ok(
      f.requests.every(
        ({ options }) => !options.cookie && !options.authorization,
      ),
    );
    assert.ok(
      f.requests
        .filter(({ options }) => !options.wireHost.startsWith("127.0.0.1:"))
        .every(({ options }) => options.forwardedProto === "https"),
    );
  });
}

for (const defect of [
  "missing-js",
  "html-css",
  "empty-asset",
  "foreign-path",
  "traversal",
  "no-css",
  "dev-login",
  "enabled-password",
  "get-form",
  "health-leak",
  "forwarded-health",
  "protected-open",
  "redirect-host",
  "cacheable",
  "api-open",
  "cookie",
  "query-leak",
  "unsafe-replay",
]) {
  test(`rejects ${defect} in emitted runtime responses`, async () => {
    const f = fixture("admin", (r, path, options) => {
      if (defect === "missing-js" && path.endsWith(".js")) r.status = 404;
      if (defect === "html-css" && path.endsWith(".css"))
        r.headers["content-type"] = "text/html";
      if (defect === "empty-asset" && path.endsWith(".js")) r.body = "";
      if (defect === "foreign-path" && path === "/login")
        r.body = r.body.replace(
          "/_next/static/main.js",
          "https://outside.invalid/main.js",
        );
      if (defect === "traversal" && path === "/login")
        r.body = r.body.replace("main.js", "../main.js");
      if (defect === "no-css" && path === "/login")
        r.body = r.body.replace("main.css", "font.woff");
      if (defect === "dev-login" && path === "/login")
        r.body += "Sign in locally";
      if (defect === "enabled-password" && path === "/login")
        r.body = r.body.replace(' disabled=""', "");
      if (defect === "get-form" && path === "/login")
        r.body = r.body.replace('method="post"', 'method="get"');
      if (
        defect === "health-leak" &&
        path === "/healthz" &&
        options.wireHost === "admin.authorityclosers.com"
      )
        r.status = 200;
      if (defect === "forwarded-health" && options.forwardedHost)
        r.status = 200;
      if (defect === "protected-open" && path === "/platform") r.status = 200;
      if (defect === "redirect-host" && path === "/platform")
        r.headers.location = "http://internal:8080/login";
      if (defect === "cacheable" && path === "/platform")
        delete r.headers["cache-control"];
      if (defect === "api-open" && path === "/v1/me") r.status = 200;
      if (defect === "cookie" && path === "/login")
        r.headers["set-cookie"] = ["synthetic=1"];
      if (defect === "query-leak" && r.status === 302)
        r.headers.location += "?private=synthetic-must-not-transfer";
      if (defect === "unsafe-replay" && options.method === "POST")
        r.status = 302;
    });
    await assert.rejects(verifyOperationsSurface("admin", f));
  });
}

test("startup never becoming healthy has a finite deadline and no alternate dev path", async () => {
  const f = fixture("coach", (r) => {
    r.status = 503;
  });
  await assert.rejects(
    verifyOperationsSurface("coach", f),
    /did not become healthy/,
  );
  assert.equal(f.requests.length, 120);
  assert.ok(f.requests.every(({ path }) => path === "/healthz"));
});

test("cold startup can retry before real compiled response checks", async () => {
  let count = 0;
  const f = fixture("coach", (r, path, options) => {
    if (
      path === "/healthz" &&
      options.wireHost === "127.0.0.1:3002" &&
      ++count < 3
    )
      r.status = 503;
  });
  const proof = await verifyOperationsSurface("coach", f);
  assert.equal(count, 3);
  assert.equal(proof.compiled_assets, 2);
});

test("standalone probe never echoes an unrecognized surface argument", () => {
  const source = readFileSync(
    new URL(
      "../../scripts/verify-release-operations-probe.mjs",
      import.meta.url,
    ),
    "utf8",
  );
  const hostile = "https://synthetic-never-print.invalid/\nsecret";
  const result = spawnSync(
    process.execPath,
    ["--input-type=module", "-", hostile],
    {
      input: source,
      encoding: "utf8",
      env: {
        AC_RELEASE_IMAGE_PROBE: "1",
        PATH: process.env.PATH,
      },
    },
  );
  assert.equal(result.status, 1);
  assert.equal(result.stdout, "");
  assert.equal(result.stderr, "AC_RELEASE_PROBE_FAILURE=unknown:bootstrap\n");
  assert.doesNotMatch(result.stderr, /synthetic-never-print|https:|secret/);
});
