// Headroom guard: the robot shares ac with production and the builders. It waits while a release cut runs, while
// memory or CPU is under pressure, and while a PAUSE file exists; STOP ends the run.
const fs = require("fs");
const path = require("path");
const cfg = require("./config.cjs");

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const read = (file) => {
  try {
    return fs.readFileSync(file, "utf8");
  } catch {
    return "";
  }
};

function pressure(kind) {
  const line = read(`/proc/pressure/${kind}`).split("\n").find((l) => l.startsWith("some")) || "";
  const m = /avg10=([\d.]+)/.exec(line);
  return m ? Number(m[1]) : 0;
}

// Dev API latency: a small signed-in read every 20 s straight to the API (as the dev site's host). The robot
// pauses itself while the middle of the last three answers takes over 2 s (orchestrator, 1 Nov 2026).
const latency = [];
function startLatencyProbe(cookieOf, cb = () => {}) {
  const http = require("http");
  const once = async () => {
    const t0 = Date.now();
    try {
      const cookie = await cookieOf();
      await new Promise((resolve, reject) => {
        const req = http.get({ host: "127.0.0.1", port: Number(process.env.QA_API_PORT || 8101), path: "/v1/bug-reports/mine", headers: { host: process.env.QA_DEV_HOST || "salesxray-dev.authorityclosers.com", cookie, accept: "application/json" }, timeout: 10000 }, (res) => {
          res.resume();
          res.on("end", resolve);
        });
        req.on("timeout", () => req.destroy(new Error("timeout")));
        req.on("error", reject);
      });
      latency.push(Date.now() - t0);
    } catch {
      latency.push(10000);
    }
    if (latency.length > 3) latency.shift();
    cb(latency[latency.length - 1]);
  };
  once();
  setInterval(once, 20000).unref();
  startDevProbe(cookieOf);
}
// Dev pages compiling: a signed-in GET of /dashboard through the proxy every 30 s. When someone's edit breaks the build,
// every page answers 500 with the build error; the robot then waits and files nothing (orchestrator, 1 Nov 2026).
const dev = { ok: true, why: "" };
function startDevProbe(cookieOf) {
  const http = require("http");
  const once = async () => {
    try {
      const cookie = await cookieOf();
      const res = await new Promise((resolve, reject) => {
        const req = http.get({ host: "127.0.0.1", port: Number(new URL(cfg.PROXY).port || 3098), path: "/dashboard", headers: { cookie, accept: "text/html" }, timeout: 90000 }, (r) => {
          let body = "";
          r.on("data", (c) => {
            if (body.length < 400000) body += c;
          });
          r.on("end", () => resolve({ status: r.statusCode, body }));
        });
        req.on("timeout", () => req.destroy(new Error("timeout")));
        req.on("error", reject);
      });
      if (res.status >= 500) {
        const build = /Build Error|Failed to compile|Module build failed|CssSyntaxError|Parsing css source code failed|Syntax error/i.exec(res.body);
        dev.ok = false;
        dev.why = build ? `build error (${build[0]})` : `HTTP ${res.status}`;
      } else {
        dev.ok = true;
        dev.why = "";
      }
    } catch (error) {
      dev.ok = false;
      dev.why = String((error && error.message) || error).slice(0, 60);
    }
  };
  once();
  setInterval(once, 30000).unref();
}
const v1Median = () => (latency.length ? [...latency].sort((a, b) => a - b)[Math.floor(latency.length / 2)] : 0);

function snapshot() {
  const mem = read("/proc/meminfo");
  const kb = (key) => Number((new RegExp(`${key}:\\s+(\\d+)`).exec(mem) || [0, 0])[1]);
  return {
    cut: fs.existsSync(cfg.CUT_FLAG),
    load1: Number(read("/proc/loadavg").split(" ")[0]) || 0,
    cpuPsi: pressure("cpu"),
    memPsi: pressure("memory"),
    memAvailableMb: Math.round(kb("MemAvailable") / 1024),
    swapFreeMb: Math.round(kb("SwapFree") / 1024),
    pause: fs.existsSync(path.join(cfg.STATE, "PAUSE")),
    stop: fs.existsSync(path.join(cfg.STATE, "STOP")),
    v1ms: v1Median(),
    devOk: dev.ok,
    devWhy: dev.why,
  };
}

function verdict(s) {
  const L = cfg.LIMITS;
  if (s.stop) return "stop";
  // A release cut pauses the robot only while the box is tight (orchestrator, 31 Oct 2026).
  if (s.cut && (s.cpuPsi > L.cutCpuPsiMax || s.load1 > L.cutLoadMax)) return "release cut running and the box is tight";
  if (s.pause) return "PAUSE file";
  if (!s.devOk) return `dev pages not compiling (${s.devWhy})`;
  if (s.v1ms > 2000) return `dev /v1 slow (${s.v1ms} ms)`;
  if (s.memAvailableMb < L.memAvailableMinMb) return `memory available ${s.memAvailableMb} MB`;
  if (s.memPsi > L.memPressureMax) return `memory pressure ${s.memPsi}`;
  if (s.cpuPsi > L.cpuPressureMax) return `cpu pressure ${s.cpuPsi}`;
  if (s.load1 > L.loadMax) return `load ${s.load1}`;
  return null;
}

// Resolves when it is polite to work; returns "stop" when told to end. `log` says why it waits, once per change.
async function headroom(log = () => {}, maxWaitMs = 6 * 3600 * 1000) {
  const start = Date.now();
  let last = null;
  for (;;) {
    const s = snapshot();
    const why = verdict(s);
    if (why === "stop") return "stop";
    if (!why) {
      if (last) log(`resuming (waited ${Math.round((Date.now() - start) / 1000)} s)`);
      return "go";
    }
    if (why !== last) log(`waiting: ${why}`);
    last = why;
    if (Date.now() - start > maxWaitMs) return "timeout";
    await sleep(why.startsWith("release cut") || why === "PAUSE file" ? 30000 : 15000);
  }
}

module.exports = { headroom, snapshot, verdict, sleep, startLatencyProbe };
