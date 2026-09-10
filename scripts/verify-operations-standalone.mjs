// Anonymous production-artifact proof only. Never opens a real API or creates a session.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { request } from "node:http";
import { cp, mkdir, realpath, writeFile } from "node:fs/promises";
import { dirname, join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const surface = process.argv[2];
assert.ok(["admin", "coach"].includes(surface), "Choose admin or coach");
const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const app = join(root, "apps", `${surface}-web`);
const standalone = join(app, ".next", "standalone", "apps", `${surface}-web`);
const compiled = join(app, ".next");
const port = surface === "admin" ? 3211 : 3212;
const servicePort = surface === "admin" ? 3001 : 3002;
const host = `${surface}.authorityclosers.com`;
const proof = { surface, source: "local-production-build", checks: [], mutations: 0 };

// Copy only generated static assets, like Dockerfile.web does. Refuse a link
// escaping this app's build tree; never remove/rewrite source or the .next/dev tree.
for (const path of [compiled, standalone, join(standalone, ".next")]) {
  const actual = await realpath(path);
  assert.ok(actual.startsWith(app + sep), "Build path must stay inside this app");
}
await cp(join(compiled, "static"), join(standalone, ".next", "static"), { recursive: true });
const environment = {
  NODE_ENV: "production",
  NODE_OPTIONS: "--max-old-space-size=512",
  NEXT_TELEMETRY_DISABLED: "1",
  PORT: String(port),
  HOSTNAME: "127.0.0.1",
  AC_INTERNAL_API_HOST: "api.production.ac.internal.invalid",
  AC_INTERNAL_API_URL: "http://api.production.ac.internal.invalid:8000",
  AC_COACH_APP_URL: "https://coach.authorityclosers.com",
  // A stale development flag must not unlock a production-built process.
  AC_DEV_LOCAL_SANDBOX_ENABLED: "true",
};
for (const key of ["SystemRoot", "WINDIR", "TEMP", "TMP", "PATH"]) {
  if (process.env[key]) environment[key] = process.env[key];
}
const child = spawn(process.execPath, [join(standalone, "server.js")], {
  cwd: standalone,
  env: environment,
  windowsHide: true,
  stdio: ["ignore", "pipe", "pipe"],
});
let exited = false;
let startupError = "";
let startupCode = "";
child.stderr.on("data", (chunk) => { startupError = (startupError + chunk.toString()).slice(-4096); });
child.stdout.on("data", (chunk) => { startupError = (startupError + chunk.toString()).slice(-4096); });
child.on("exit", (code) => { exited = true; startupCode = String(code); });
child.on("error", (error) => { exited = true; startupCode = error.code ?? "spawn-failed"; });
const delay = (ms) => new Promise((done) => setTimeout(done, ms));
function get(path, { wireHost = host, method = "GET" } = {}) {
  return new Promise((done, fail) => {
    const req = request({ hostname: "127.0.0.1", port, path, method, headers: { Host: wireHost } }, (res) => {
      const bytes = [];
      let size = 0;
      res.on("data", (chunk) => {
        size += chunk.length;
        if (size > 4 * 1024 * 1024) req.destroy(new Error("Response exceeded proof limit"));
        else bytes.push(chunk);
      });
      res.on("error", fail);
      res.on("end", () => done({ status: res.statusCode, headers: res.headers, body: Buffer.concat(bytes).toString("utf8") }));
    });
    req.setTimeout(5000, () => req.destroy(new Error("Local proof timed out")));
    req.on("error", fail);
    req.end();
  });
}
try {
  let ready = false;
  for (let i = 0; i < 80; i += 1) {
    assert.equal(exited, false, "Standalone process exited before readiness: " +
      startupCode + " " + (startupError.match(/Cannot find module [^\r\n]+|ERR_[A-Z_]+|[A-Za-z]*Error: [^\r\n]+/g) ?? ["unclassified startup failure (" + startupError.length + " log characters)"]).join("; "));
    try {
      const response = await get("/healthz", { wireHost: `127.0.0.1:${servicePort}` });
      if (response.status === 200) { ready = true; break; }
    } catch { /* This newly started child may not be listening yet. */ }
    await delay(100);
  }
  assert.ok(ready, "Standalone health did not become ready");
  proof.checks.push("loopback-only-health");
  for (const path of ["/", "/people", "/healthz"]) {
    const response = await get(path);
    assert.equal(response.status, 307, path);
    assert.equal(response.headers.location, "/login");
    assert.equal(response.headers["cache-control"], "no-store");
  }
  proof.checks.push("anonymous-pages-denied-including-public-health");
  const login = await get("/login");
  assert.equal(login.status, 200);
  assert.match(login.body, /type="password"/);
  assert.doesNotMatch(login.body, /name="tenantId"|Local sandbox|Sign in locally/);
  const assets = [...new Set([...login.body.matchAll(/(?:src|href)="(\/_next\/static\/[^"?]+)"/g)].map((m) => m[1]))];
  assert.ok(assets.some((asset) => asset.endsWith(".css")), "Compiled stylesheet missing");
  assert.ok(assets.some((asset) => asset.endsWith(".js")), "Compiled client code missing");
  for (const asset of assets) assert.equal((await get(asset)).status, 200, "Compiled asset unavailable");
  proof.checks.push(`production-login-and-${assets.length}-static-assets`);
  if (surface === "admin") {
    const moved = await get("/studio/programs?private=must-not-transfer");
    assert.equal(moved.status, 302);
    assert.equal(moved.headers.location, "https://coach.authorityclosers.com/studio/programs");
    assert.equal(moved.headers["cache-control"], "no-store");
    assert.equal((await get("/studio/programs", { method: "POST" })).status, 405);
    proof.checks.push("coach-redirect-strips-query-and-refuses-write-replay");
  }
  const output = join(root, "docs", "evidence", "standalone", `${surface}-20260908.json`);
  await mkdir(dirname(output), { recursive: true });
  await writeFile(output, JSON.stringify(proof, null, 2) + "\n");
  console.log(JSON.stringify(proof));
} finally {
  if (!exited) {
    child.kill(); // Only the exact child started above; never discovers/kills other services.
    await Promise.race([new Promise((done) => child.once("exit", done)), delay(3000)]);
    assert.ok(exited, "The proof child did not exit; inspect its exact process before retrying");
  }
}
