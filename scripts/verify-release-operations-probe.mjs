// Executed through stdin inside an exact, isolated release container. No API/session access.
import assert from "node:assert/strict";
import { request } from "node:http";

const MAX_BYTES = 4 * 1024 * 1024;
const assetPath =
  /^\/_next\/static\/(?!.*(?:\/\.\.?\/|\/\/))[A-Za-z0-9_./-]+\.(?:css|js)$/;

export function loopbackGet(port) {
  return (
    path,
    {
      wireHost,
      method = "GET",
      forwardedHost,
      forwardedProto,
      timeout = 4000,
    } = {},
  ) =>
    new Promise((resolve, reject) => {
      const headers = { host: wireHost, accept: "*/*" };
      if (forwardedHost) headers["x-forwarded-host"] = forwardedHost;
      if (forwardedProto) headers["x-forwarded-proto"] = forwardedProto;
      const call = request(
        { hostname: "127.0.0.1", port, path, method, headers },
        (response) => {
          const chunks = [];
          let length = 0;
          response.on("data", (chunk) => {
            length += chunk.length;
            if (length > MAX_BYTES)
              call.destroy(new Error("Runtime response limit exceeded"));
            else chunks.push(chunk);
          });
          response.on("error", reject);
          response.on("end", () =>
            resolve({
              status: response.statusCode,
              headers: response.headers,
              body: Buffer.concat(chunks).toString("utf8"),
            }),
          );
        },
      );
      // Includes DNS/connect, response headers and an indefinitely trickling body.
      const deadline = setTimeout(
        () => call.destroy(new Error("Runtime request deadline exceeded")),
        timeout,
      );
      call.on("close", () => clearTimeout(deadline));
      call.on("error", reject);
      call.end();
    });
}

function privateResponse(response) {
  assert.match(
    response.headers["cache-control"] ?? "",
    /(?:^|[ ,])no-store(?:$|[ ,])/,
  );
  assert.equal(response.headers["set-cookie"], undefined);
}

export async function verifyOperationsSurface(
  surface,
  {
    get,
    delay = (milliseconds) =>
      new Promise((resolve) => setTimeout(resolve, milliseconds)),
    now = () => performance.now(),
    phase = () => {},
  } = {},
) {
  phase("bootstrap");
  assert.ok(["admin", "coach"].includes(surface), "Unknown operations surface");
  const port = surface === "admin" ? 3001 : 3002;
  get ??= loopbackGet(port);
  const host = `${surface}.authorityclosers.com`;
  const internal = `127.0.0.1:${port}`;
  const publicGet = (path, options = {}) =>
    get(path, { wireHost: host, forwardedProto: "https", ...options });
  const checks = [];
  const deadline = now() + 12000;
  let ready = false;
  phase("readiness");
  while (now() < deadline) {
    try {
      const health = await get("/healthz", {
        wireHost: internal,
        timeout: 1000,
      });
      if (health.status === 200) {
        assert.deepEqual(JSON.parse(health.body), {
          status: "ok",
          service: `authority-closers-${surface}`,
        });
        privateResponse(health);
        ready = true;
        break;
      }
    } catch {
      /* Bounded cold start only; no endpoint fallback. */
    }
    await delay(100);
  }
  assert.equal(
    ready,
    true,
    "Original standalone server did not become healthy",
  );
  checks.push("loopback-health");

  const deny = async (path, options = {}) => {
    const response = await publicGet(path, options);
    assert.equal(response.status, 307, "Anonymous page was not denied");
    const location = new URL(response.headers.location);
    assert.equal(location.origin, `https://${host}`);
    assert.equal(location.pathname, "/login");
    assert.equal(location.search, "");
    assert.equal(location.hash, "");
    privateResponse(response);
  };
  phase("public-health");
  await deny("/healthz");
  checks.push("public-health-denied");
  phase("forwarded-health");
  const forwarded = await publicGet("/healthz", {
    wireHost: "untrusted.invalid",
    forwardedHost: internal,
  });
  assert.equal(forwarded.status, 421);
  assert.equal(forwarded.headers.location, undefined);
  privateResponse(forwarded);
  checks.push("forwarded-health-denied");
  phase("anonymous-pages");
  for (const path of surface === "admin"
    ? ["/", "/platform", "/people?private=synthetic"]
    : ["/", "/studio/programs", "/people?private=synthetic"])
    await deny(path);
  checks.push("anonymous-pages-denied");

  phase("production-login");
  const login = await publicGet("/login");
  assert.equal(login.status, 200, "Compiled production login did not render");
  assert.match(login.headers["content-type"] ?? "", /^text\/html(?:;|$)/i);
  assert.match(login.body, /<form\b[^>]*\bmethod="post"/i);
  assert.match(
    login.body,
    /<input\b[^>]*\btype="password"[^>]*\bdisabled(?:="")?(?:\s|\/|>)/i,
  );
  assert.doesNotMatch(
    login.body,
    /name="tenant_id"|Sign in locally|Local sandbox|staging-authenticated/,
  );
  assert.equal(login.headers["set-cookie"], undefined);
  checks.push("production-login");
  phase("compiled-assets");
  const assets = [
    ...new Set(
      [...login.body.matchAll(/(?:src|href)="([^\"]+)"/g)]
        .map((match) => match[1])
        .filter(
          (path) =>
            path.startsWith("/_next/static/") &&
            /\.(?:js|css)(?:[?#]|$)/.test(path),
        ),
    ),
  ];
  assert.ok(
    assets.length >= 2 && assets.length <= 64,
    "Compiled asset inventory is unavailable or unbounded",
  );
  assert.ok(
    assets.some((path) => path.endsWith(".js")) &&
      assets.some((path) => path.endsWith(".css")),
  );
  for (const path of assets) {
    assert.match(
      path,
      assetPath,
      "Compiled asset URL is not an exact local static path",
    );
    assert.ok(
      path
        .split("/")
        .slice(1)
        .every((part) => part && part !== "." && part !== ".."),
      "Compiled asset path contains ambiguous segments",
    );
    const asset = await publicGet(path);
    assert.equal(
      asset.status,
      200,
      "Compiled asset is missing from the release image",
    );
    assert.match(
      asset.headers["content-type"] ?? "",
      path.endsWith(".css")
        ? /^text\/css(?:;|$)/i
        : /^(?:text|application)\/(?:javascript|ecmascript)(?:;|$)/i,
    );
    assert.ok(asset.body.trim().length > 0);
    assert.doesNotMatch(asset.body, /^\s*(?:<!doctype|<html)/i);
    assert.equal(asset.headers["set-cookie"], undefined);
  }
  checks.push("compiled-js-css");
  phase("api-denial");
  const api = await publicGet("/v1/me");
  assert.equal(
    api.status,
    surface === "admin" ? 403 : 404,
    surface === "admin"
      ? "Anonymous API request was not denied by middleware"
      : "Development transport became available in production",
  );
  privateResponse(api);
  // Admin's middleware ends this request before its development route executes.
  checks.push(
    surface === "admin"
      ? "anonymous-api-denied"
      : "development-api-unavailable",
  );

  if (surface === "admin") {
    phase("admin-coach-redirect");
    for (const [path, destination] of [
      ["/studio/programs", "/studio/programs"],
      ["/catalog", "/studio/programs"],
    ]) {
      const redirect = await publicGet(
        path + "?private=synthetic-must-not-transfer",
      );
      assert.equal(redirect.status, 302);
      assert.equal(
        redirect.headers.location,
        "https://coach.authorityclosers.com" + destination,
      );
      privateResponse(redirect);
      const unsafe = await publicGet(path, { method: "POST" });
      assert.equal(unsafe.status, 405);
      assert.equal(unsafe.headers.location, undefined);
      assert.equal(unsafe.headers.allow, "GET, HEAD");
      privateResponse(unsafe);
    }
    checks.push("coach-redirect-no-query-or-write-replay");
  }
  return {
    surface,
    checks,
    compiled_assets: assets.length,
    api_auth_exercised: false,
  };
}

if (process.env.AC_RELEASE_IMAGE_PROBE === "1") {
  const requestedSurface = process.argv[2];
  const surface = ["admin", "coach"].includes(requestedSurface)
    ? requestedSurface
    : "unknown";
  let activePhase = "bootstrap";
  try {
    assert.equal(process.platform, "linux");
    assert.ok(
      process.getuid && process.getuid() !== 0,
      "Release process must be non-root",
    );
    assert.equal(process.env.NODE_ENV, "production");
    assert.equal(process.env.HOSTNAME, "127.0.0.1");
    const result = await verifyOperationsSurface(surface, {
      phase: (next) => {
        activePhase = next;
      },
    });
    result.checks.unshift("non-root-linux-node");
    process.stdout.write(JSON.stringify(result));
  } catch {
    process.stderr.write(
      `AC_RELEASE_PROBE_FAILURE=${surface}:${activePhase}\n`,
    );
    process.exitCode = 1;
  }
}
