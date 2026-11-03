// Design-quality capture stage (orchestrator's order, 3 Nov 2026): for every screen of the seller and owner grids, at 360 and 393 px with touch, light and dark:
// a full-page picture and a 5-second scroll recording, saved into a dated folder with one manifest per run, plus four measurable design rules read off the same page:
//   edge-mask     a mask-image or fade gradient on a row that scrolls sideways (phone)
//   boxed         page content narrower than the viewport minus 32 px while another background colour shows at the sides (phone)
//   dead-row      a row holding one control under half the row's width, while the row above leaves more than 40% of its width free (phone)
//   label-heading a one-word heading that does nothing, directly above controls (phone, not the page's h1)
// Dev only, sandbox people only, read-only (every write is refused). The rules are reported in the manifest; filing them as MINOR layout rows is a separate switch (lib/design-rules.json "file": true) turned on after a replay.
const fs = require("fs");
const path = require("path");
const { spawnSync } = require("child_process");
const cfg = require("./config.cjs");
const session = require("./session.cjs");

const ROOT_OUT = process.env.QA_CAPTURES || "/var/qa-captures";
const FFMPEG = process.env.QA_FFMPEG || "/home/acdev/.cache/ms-playwright/ffmpeg-1011/ffmpeg-linux";
const KEEP_RUNS = Number(process.env.QA_CAPTURE_KEEP || 6);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const slug = (text) => text.replace(/[^a-z0-9]+/gi, "_").replace(/^_|_$/g, "").slice(0, 70) || "root";

// ---- the four rules, run in the page: lib/design-rules.cjs ----
const { DESIGN_SCAN } = require("./design-rules.cjs");

// ---- page helpers --------------------------------------------------------------------------------------------------
const LOADING_WORDS = /\b(Counting|Loading|Syncing|Checking|Fetching)\b[^.\n]{0,40}(…|\.\.\.)/i;
async function settledPage(tab) {
  await session.settle(tab, 14000).catch(() => null);
  let prev = -1;
  for (let i = 0; i < 10; i++) {
    const t = await tab.page.evaluate(() => ((document.querySelector("main") || document.body).innerText || "").trim()).catch(() => "");
    if (t.length >= 25 && t.length === prev && !LOADING_WORDS.test(t)) return true;
    prev = t.length;
    await sleep(800);
  }
  return false;
}

// the tallest thing that scrolls: the page, or an inner scroller (the app scrolls inside its shell on some screens)
const SCROLLER = () => {
  const root = document.scrollingElement || document.documentElement;
  if (root.scrollHeight > root.clientHeight + 20) return { inner: false, h: root.scrollHeight, view: root.clientHeight };
  let best = null;
  for (const e of document.querySelectorAll("body *")) {
    const cs = getComputedStyle(e);
    if (cs.overflowY !== "auto" && cs.overflowY !== "scroll") continue;
    if (e.scrollHeight <= e.clientHeight + 20 || e.clientHeight < innerHeight * 0.5) continue;
    if (!best || e.scrollHeight > best.scrollHeight) best = e;
  }
  return best ? { inner: true, h: best.scrollHeight, view: best.clientHeight, top: best.getBoundingClientRect().top } : { inner: false, h: root.scrollHeight, view: root.clientHeight };
};
const SCROLL_FOR = (ms) => new Promise((resolve) => {
  const root = document.scrollingElement || document.documentElement;
  let sc = root;
  if (root.scrollHeight <= root.clientHeight + 20) {
    sc = null;
    for (const e of document.querySelectorAll("body *")) {
      const cs = getComputedStyle(e);
      if ((cs.overflowY === "auto" || cs.overflowY === "scroll") && e.scrollHeight > e.clientHeight + 20 && e.clientHeight >= innerHeight * 0.5 && (!sc || e.scrollHeight > sc.scrollHeight)) sc = e;
    }
  }
  if (!sc) return resolve(0);
  const total = sc.scrollHeight - sc.clientHeight;
  const t0 = performance.now();
  const step = () => {
    const t = Math.min(1, (performance.now() - t0) / ms);
    sc.scrollTop = total * t;
    if (t < 1) requestAnimationFrame(step); else resolve(total);
  };
  step();
});

async function fullPagePicture(tab, file) {
  const page = tab.page;
  const sc = await page.evaluate(SCROLLER).catch(() => null);
  const vp = page.viewportSize();
  let restore = null;
  let height = vp.height;
  if (sc && sc.inner) {
    height = Math.min(7000, Math.round((sc.top || 0) + sc.h));
    restore = vp;
    await page.setViewportSize({ width: vp.width, height });
    await sleep(700);
  } else if (sc) height = Math.min(7000, sc.h);
  await page.screenshot({ path: file, fullPage: !(sc && sc.inner), type: "jpeg", quality: 80 });
  if (restore) await page.setViewportSize(restore).catch(() => null);
  return height;
}

function trim(src, dst, from, seconds) {
  if (!fs.existsSync(FFMPEG)) return { ok: false, err: "no ffmpeg" };
  // the browser's library path is not for the encoder
  const env = { ...process.env };
  delete env.LD_LIBRARY_PATH;
  // the recording has one key frame, at the start, so a stream copy cannot cut: re-encode, with the fastest settings (the default ones starve on this niced, quota-limited process)
  const r = spawnSync(FFMPEG, ["-y", "-loglevel", "error", "-ss", Math.max(0, from).toFixed(2), "-i", src, "-t", String(seconds), "-c:v", "libvpx", "-deadline", "realtime", "-cpu-used", "8", "-b:v", "400k", "-g", "25", "-an", dst], { timeout: 150000, env, encoding: "utf8" });
  const ok = r.status === 0 && fs.existsSync(dst) && fs.statSync(dst).size > 2000;
  return { ok, err: ok ? "" : `ffmpeg status ${r.status} ${String(r.stderr || r.error || "").split("\n")[0].slice(0, 120)}` };
}

function poolLead() {
  try {
    const f = process.env.QA_POOL || path.join(cfg.ROOT, "state", "qa-pool.json");
    return JSON.parse(fs.readFileSync(f, "utf8"))[0].id;
  } catch { return null; }
}

function pageList(role) {
  const { PAGES } = require("./attack.cjs");
  return PAGES[role] || [];
}

// ---- one run -----------------------------------------------------------------------------------------------------
async function captureRun({ role = "seller", sizes = ["360 px", "393 px"], themes = ["light", "dark"], routes = null, alias = null, gate = null, log = console.log, video = true } = {}) {
  const who = alias || (role === "owner" ? "owner" : "priya");
  const stamp = new Date().toISOString().replace(/[-:]/g, "").slice(0, 13).replace("T", "-");
  const dir = path.join(ROOT_OUT, `${stamp}-${role}`);
  fs.mkdirSync(path.join(dir, "shots"), { recursive: true });
  fs.mkdirSync(path.join(dir, "video"), { recursive: true });
  const tmp = fs.mkdtempSync(path.join(require("os").tmpdir(), "qa-cap-"));
  const lead = poolLead();
  const list = (routes || pageList(role)).map((r) => r.replace("{lead}", lead || "")).filter((r) => lead || !r.includes("lead="));
  const manifest = { run: path.basename(dir), role, alias: who, started: new Date().toISOString(), build: null, sizes, themes, entries: [], summary: {} };
  try { manifest.build = require("child_process").execSync("git -C /home/acdev/src/dev-live/authority-closers-platform rev-parse --short HEAD", { encoding: "utf8" }).trim(); } catch {}
  const save = () => fs.writeFileSync(path.join(dir, "manifest.json"), JSON.stringify(manifest, null, 1));
  let n = 0;
  for (const size of sizes) {
    for (const theme of themes) {
      for (const route of list) {
        if (gate && (await gate()) === "stop") { log("capture: the box is tight, stopping this run"); manifest.summary.stopped = true; break; }
        const id = `${slug(route)}__${size.replace(/\D/g, "")}__${theme}`;
        const entry = { id, route: route.replace(lead || "\u0000", "{lead}"), size, theme, alias: who, ok: false, rules: {} };
        manifest.entries.push(entry);
        let tab = null;
        let rec = null;
        try {
          // one visit: load, settle, read the rules, take the picture, then scroll for 5 s with the recording running; the loading part of the recording is cut off afterwards
          const t0 = Date.now();
          tab = await session.openTab({ alias: who, device: size, theme, state: "normal", videoDir: video ? tmp : undefined });
          const opened = Date.now();
          await tab.context.route("**/*", (rt) => (["GET", "HEAD", "OPTIONS"].includes(rt.request().method()) ? rt.fallback() : rt.abort("blockedbyclient")));
          const r = await session.go(tab, route, { wait: 40000 });
          if (!r.ok) { entry.note = `did not open: ${String(r.error).slice(0, 100)}`; log(`capture ${id}: ${entry.note}`); continue; }
          entry.settled = await settledPage(tab);
          entry.loadMs = Date.now() - t0;
          entry.url = await tab.page.evaluate(() => location.pathname + location.search).catch(() => route);
          const found = await tab.page.evaluate(DESIGN_SCAN).catch((e) => ({ error: String(e).slice(0, 100) }));
          entry.rules = { edgeMask: found.edgeMask || [], boxed: found.boxed || [], deadRow: found.deadRow || [], labelHeading: found.labelHeading || [] };
          if (found.labelSmall && found.labelSmall.length) entry.small = { labelHeadingSmall: found.labelSmall }; // not a finding: kept to see what the 20 px line leaves out
          if (found.error) entry.note = `rules: ${found.error}`;
          const shot = path.join("shots", `${id}.jpg`);
          entry.heightPx = await fullPagePicture(tab, path.join(dir, shot));
          entry.screenshot = shot;
          entry.ok = true;
          if (video) {
            await sleep(500);
            const from = (Date.now() - opened) / 1000;
            const total = await tab.page.evaluate(SCROLL_FOR, 5000).catch(() => 0);
            if (!total) await sleep(1800);
            await sleep(400);
            rec = { video: tab.page.video(), from, total };
          }
        } catch (error) {
          entry.note = `failed: ${String(error).split("\n")[0].slice(0, 120)}`;
        } finally {
          if (tab) await session.closeTab(tab).catch(() => null);
        }
        if (entry.ok && rec && rec.video) {
          try {
            const raw = path.join(tmp, `${id}.webm`);
            await rec.video.saveAs(raw).catch(() => null);
            const out = path.join(dir, "video", `${id}.webm`);
            if (fs.existsSync(raw)) {
              const t = trim(raw, out, rec.from - 0.5, rec.total ? 5.8 : 3);
              if (!t.ok) { fs.copyFileSync(raw, out); entry.videoNote = t.err; }
              fs.rmSync(raw, { force: true });
              entry.video = path.join("video", `${id}.webm`);
              entry.scrolled = rec.total ? Math.round(rec.total) : 0;
              entry.videoTrimmed = t.ok;
            }
          } catch (error) {
            entry.videoNote = `no recording: ${String(error).split("\n")[0].slice(0, 100)}`;
          }
        }
        n++;
        const hits = ["edgeMask", "boxed", "deadRow", "labelHeading"].filter((k) => entry.rules[k] && entry.rules[k].length).map((k) => `${k} ${entry.rules[k].length}`);
        log(`capture ${n} ${id}: ${entry.ok ? "ok" : entry.note}${hits.length ? " | " + hits.join(", ") : ""}`);
        if (n % 4 === 0) save();
      }
    }
  }
  manifest.finished = new Date().toISOString();
  const count = (k) => manifest.entries.reduce((a, e) => a + ((e.rules && e.rules[k]) || []).length, 0);
  manifest.summary = { ...manifest.summary, captures: manifest.entries.length, ok: manifest.entries.filter((e) => e.ok).length, videos: manifest.entries.filter((e) => e.video).length, edgeMask: count("edgeMask"), boxed: count("boxed"), deadRow: count("deadRow"), labelHeading: count("labelHeading") };
  save();
  fs.rmSync(tmp, { recursive: true, force: true });
  // keep the newest runs only (the disk on ac is tight); a run folder with a KEEP file stays
  try {
    const runs = fs.readdirSync(ROOT_OUT).filter((d) => /^\d{8}-\d{4}-(seller|owner)$/.test(d)).sort();
    for (const old of runs.slice(0, Math.max(0, runs.length - KEEP_RUNS))) if (!fs.existsSync(path.join(ROOT_OUT, old, "KEEP"))) fs.rmSync(path.join(ROOT_OUT, old), { recursive: true, force: true });
  } catch {}
  log(`capture run ${manifest.run}: ${JSON.stringify(manifest.summary)}`);
  return { dir, summary: manifest.summary };
}

module.exports = { captureRun, DESIGN_SCAN, pageList };
