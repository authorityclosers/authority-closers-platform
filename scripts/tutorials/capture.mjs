#!/usr/bin/env node
// Sales X-Ray tutorial capture: drives headless Chromium on ac against the dev server's review fixtures
// (fictional data, no sign-in) and records each storyboard segment as a short clip plus labelled stills.
//
//   node capture.mjs survey <out> <route>[,<route>...] [--device phone|desktop]   screenshots + element list
//   node capture.mjs shoot  <storyboard.json> <out> [--device phone|desktop] [--only seg,seg]
//   node capture.mjs cards  <cards.json> <out>          1920x1080 PNG per card (title, end, frames)
//
// Run from the repo root as acdev so `playwright` resolves, with
// LD_LIBRARY_PATH=$SXTUT_OUT/lib (Chrome's few missing desktop libraries, unpacked, nothing installed).
// One browser at a time; an in-script watchdog kills everything after SXTUT_WATCHDOG_S seconds (default 900).
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const BASE = process.env.SXTUT_BASE || "http://127.0.0.1:3026";
const CHROME =
  process.env.SXTUT_CHROME ||
  `${process.env.HOME}/.cache/ms-playwright/chromium-1208/chrome-linux64/chrome`;
const WATCHDOG_S = Number(process.env.SXTUT_WATCHDOG_S || 900);

export const DEVICES = {
  // Phone: a 390x844 Android-class viewport at 3x (1170x2532 frames).
  phone: {
    viewport: { width: 390, height: 844 },
    deviceScaleFactor: 3,
    isMobile: true,
    hasTouch: true,
  },
  // Desktop: 1440x900 at 2x (2880x1800 frames).
  desktop: {
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 2,
    isMobile: false,
    hasTouch: false,
  },
};

// A soft ring where the finger or mouse lands, so viewers can follow taps. Pointer events only; no layout change.
const TAP_RING = `
(() => {
  if (window.__sxTapRing) return; window.__sxTapRing = true;
  const style = document.createElement('style');
  style.textContent = '@keyframes sxtap{0%{transform:translate(-50%,-50%) scale(.4);opacity:.9}100%{transform:translate(-50%,-50%) scale(1.6);opacity:0}}' +
    '.sx-tap{position:fixed;width:44px;height:44px;border-radius:50%;pointer-events:none;z-index:2147483647;' +
    'background:rgba(20,184,166,.28);border:2px solid rgba(13,148,136,.9);animation:sxtap .7s ease-out forwards}' +
    '.sx-hl{position:fixed;pointer-events:none;z-index:2147483646;border-radius:14px;border:3px solid rgba(13,148,136,.95);' +
    'box-shadow:0 0 0 9999px rgba(15,23,42,.28);transition:all .35s ease}';
  document.documentElement.appendChild(style);
  addEventListener('pointerdown', (e) => {
    const d = document.createElement('div'); d.className = 'sx-tap';
    d.style.left = e.clientX + 'px'; d.style.top = e.clientY + 'px';
    document.documentElement.appendChild(d); setTimeout(() => d.remove(), 800);
  }, true);
})();`;

function watchdog(browserRef) {
  const t = setTimeout(async () => {
    console.error(`watchdog: ${WATCHDOG_S}s passed; closing the browser`);
    try {
      await browserRef.b?.close();
    } catch {}
    process.exit(3);
  }, WATCHDOG_S * 1000);
  t.unref();
}

async function launch() {
  return chromium.launch({
    executablePath: CHROME,
    headless: true,
    args: [
      "--no-sandbox",
      "--disable-dev-shm-usage",
      "--hide-scrollbars",
      "--force-color-profile=srgb",
      "--font-render-hinting=none",
      "--disable-gpu-vsync",
    ],
  });
}

async function newPage(browser, device, theme = "light") {
  const ctx = await browser.newContext({
    ...DEVICES[device],
    colorScheme: theme,
    locale: "en-IN",
    timezoneId: "Asia/Kolkata",
    reducedMotion: "no-preference",
  });
  await ctx.addInitScript(TAP_RING);
  const page = await ctx.newPage();
  return { ctx, page };
}

// Some fixture screens keep polling, so "network idle" may never come: wait for the DOM, then idle up to 8 s.
async function open(page, url) {
  await page.goto(BASE + url, {
    waitUntil: "domcontentloaded",
    timeout: 90000,
  });
  await page.waitForLoadState("networkidle", { timeout: 8000 }).catch(() => {});
  await page
    .evaluate(() => document.fonts && document.fonts.ready)
    .catch(() => {});
}

function locate(page, t) {
  if (!t) return null;
  let loc;
  if (t.role)
    loc = page.getByRole(t.role, { name: t.name, exact: t.exact ?? false });
  else if (t.label) loc = page.getByLabel(t.label, { exact: t.exact ?? false });
  else if (t.placeholder) loc = page.getByPlaceholder(t.placeholder);
  else if (t.text) loc = page.getByText(t.text, { exact: t.exact ?? false });
  else if (t.css) loc = page.locator(t.css);
  else throw new Error(`bad target ${JSON.stringify(t)}`);
  return t.nth === undefined ? loc.first() : loc.nth(t.nth);
}

async function highlight(page, loc, on) {
  if (!on) {
    await page.evaluate(() =>
      document.querySelectorAll(".sx-hl").forEach((n) => n.remove()),
    );
    return;
  }
  const box = await loc.boundingBox();
  if (!box) return;
  await page.evaluate((b) => {
    let n = document.querySelector(".sx-hl");
    if (!n) {
      n = document.createElement("div");
      n.className = "sx-hl";
      document.documentElement.appendChild(n);
    }
    Object.assign(n.style, {
      left: b.x - 6 + "px",
      top: b.y - 6 + "px",
      width: b.width + 12 + "px",
      height: b.height + 12 + "px",
    });
  }, box);
}

async function act(page, a, device, stills) {
  if (a.optional) {
    // Things that may or may not be on screen (a one-time tip): try briefly, carry on without.
    try {
      await locate(page, a.target).waitFor({ state: "visible", timeout: 2500 });
    } catch {
      return;
    }
  }
  const loc = locate(page, a.target);
  switch (a.do) {
    case "goto":
      await open(page, a.url);
      await page.waitForTimeout(a.ms ?? 900);
      break;
    case "tap":
      await loc.scrollIntoViewIfNeeded();
      await page.waitForTimeout(a.before ?? 450);
      if (device === "phone") await loc.tap();
      else {
        await loc.hover();
        await page.waitForTimeout(200);
        await loc.click();
      }
      await page.waitForTimeout(a.ms ?? 1100);
      break;
    case "type":
      await loc.click();
      await page.keyboard.type(a.text, { delay: a.delay ?? 55 });
      await page.waitForTimeout(a.ms ?? 600);
      break;
    case "fill":
      await loc.fill(a.text);
      await page.waitForTimeout(a.ms ?? 600);
      break;
    case "hide":
      // Only for messages the dev fixtures add ("Sample data only."); never for product UI.
      await loc.evaluate((el) => {
        el.style.visibility = "hidden";
      });
      break;
    case "scrollto":
      // Brings a heading to the top of the screen, leaving room above it (sticky bars included);
      // `offset` leaves more room, to show what sits just above the anchor.
      await loc.evaluate((el, offset) => {
        el.scrollIntoView({ block: "start" });
        window.scrollBy(0, -offset);
      }, a.offset ?? 96);
      await page.waitForTimeout(a.ms ?? 600);
      break;
    case "select":
      // Native <select> menus do not open in headless Chromium; pick the option directly.
      await loc.selectOption({ label: a.option });
      await page.waitForTimeout(a.ms ?? 1200);
      break;
    case "paste": {
      // A real paste event with rows on the clipboard, as when a seller pastes from Sheets.
      await loc.click();
      await page.waitForTimeout(a.before ?? 300);
      await page.evaluate((text) => {
        const data = new DataTransfer();
        data.setData("text/plain", text);
        const paste = new ClipboardEvent("paste", {
          clipboardData: data,
          bubbles: true,
          cancelable: true,
        });
        document.activeElement?.dispatchEvent(paste);
      }, a.text);
      await page.waitForTimeout(a.ms ?? 1400);
      break;
    }
    case "press":
      await page.keyboard.press(a.key);
      await page.waitForTimeout(a.ms ?? 700);
      break;
    case "scroll": {
      const steps = a.steps ?? 12;
      for (let i = 0; i < steps; i++) {
        await page.mouse.wheel(0, (a.dy ?? 600) / steps);
        await page.waitForTimeout(30);
      }
      await page.waitForTimeout(a.ms ?? 700);
      break;
    }
    case "hover":
      await loc.hover();
      await page.waitForTimeout(a.ms ?? 700);
      break;
    case "highlight":
      await highlight(page, loc, true);
      await page.waitForTimeout(a.ms ?? 1200);
      break;
    case "unhighlight":
      await highlight(page, null, false);
      await page.waitForTimeout(a.ms ?? 300);
      break;
    case "wait":
      await page.waitForTimeout(a.ms ?? 1000);
      break;
    case "still":
      stills.push({ label: a.label, at: Date.now() });
      break;
    default:
      throw new Error(`unknown action ${a.do}`);
  }
}

// CDP screencast -> JPEG frames with timestamps -> constant 30 fps H.264 (ffmpeg concat with per-frame durations).
async function startRecording(page, dir, device) {
  fs.mkdirSync(dir, { recursive: true });
  const cdp = await page.context().newCDPSession(page);
  const frames = [];
  const { width, height } = DEVICES[device].viewport;
  const scale = DEVICES[device].deviceScaleFactor;
  cdp.on("Page.screencastFrame", async (f) => {
    const n = frames.length;
    const file = path.join(dir, `f${String(n).padStart(5, "0")}.jpg`);
    fs.writeFileSync(file, Buffer.from(f.data, "base64"));
    frames.push({ file, t: f.metadata.timestamp });
    try {
      await cdp.send("Page.screencastFrameAck", { sessionId: f.sessionId });
    } catch {}
  });
  await cdp.send("Page.startScreencast", {
    format: "jpeg",
    quality: 92,
    maxWidth: width * scale,
    maxHeight: height * scale,
    everyNthFrame: 1,
  });
  return {
    async stop() {
      await cdp.send("Page.stopScreencast");
      await new Promise((r) => setTimeout(r, 250));
      frames.push({ file: frames.at(-1)?.file, t: Date.now() / 1000 });
      return frames;
    },
  };
}

function encode(frames, outFile) {
  const list = path.join(path.dirname(frames[0].file), "frames.txt");
  const lines = [];
  for (let i = 0; i < frames.length - 1; i++) {
    lines.push(
      `file '${path.basename(frames[i].file)}'`,
      `duration ${Math.max(0.001, frames[i + 1].t - frames[i].t).toFixed(4)}`,
    );
  }
  lines.push(`file '${path.basename(frames.at(-2).file)}'`);
  fs.writeFileSync(list, lines.join("\n") + "\n");
  return new Promise((res, rej) => {
    const p = spawn(
      "nice",
      [
        "-n",
        "19",
        "ionice",
        "-c3",
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        list,
        "-vf",
        "fps=30,scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "16",
        "-threads",
        "2",
        "-movflags",
        "+faststart",
        outFile,
      ],
      { stdio: "inherit" },
    );
    p.on("exit", (c) => (c === 0 ? res() : rej(new Error(`ffmpeg ${c}`))));
  });
}

async function survey(out, routes, device) {
  const ref = {};
  watchdog(ref);
  const browser = (ref.b = await launch());
  fs.mkdirSync(out, { recursive: true });
  for (const dev of device ? [device] : ["phone", "desktop"]) {
    const { ctx, page } = await newPage(browser, dev);
    for (const r of routes) {
      const slug =
        r.replace(/[^a-z0-9]+/gi, "-").replace(/^-|-$/g, "") || "root";
      try {
        await open(page, r);
        await page.waitForTimeout(1200);
        await page.screenshot({
          path: path.join(out, `${dev}-${slug}.jpg`),
          type: "jpeg",
          quality: 70,
          scale: "css",
          fullPage: dev === "phone",
        });
        const els = await page.evaluate(() => {
          const pick = [
            ...document.querySelectorAll(
              "button,a,[role=tab],[role=button],input,textarea,select,h1,h2,h3,[role=switch],[role=checkbox]",
            ),
          ];
          return pick
            .filter((e) => {
              const b = e.getBoundingClientRect();
              return b.width > 0 && b.height > 0;
            })
            .slice(0, 120)
            .map((e) => {
              const b = e.getBoundingClientRect();
              return `${e.tagName.toLowerCase()}${e.getAttribute("role") ? "[" + e.getAttribute("role") + "]" : ""} "${(e.getAttribute("aria-label") || e.innerText || e.getAttribute("placeholder") || "").trim().replace(/\s+/g, " ").slice(0, 60)}" @${Math.round(b.x)},${Math.round(b.y)} ${Math.round(b.width)}x${Math.round(b.height)}`;
            });
        });
        fs.writeFileSync(
          path.join(out, `${dev}-${slug}.txt`),
          els.join("\n") + "\n",
        );
        console.log(`${dev} ${r}: ok, ${els.length} elements`);
      } catch (e) {
        console.log(`${dev} ${r}: FAILED ${e.message.split("\n")[0]}`);
      }
    }
    await ctx.close();
  }
  await browser.close();
}

async function shoot(boardFile, out, deviceFilter, only) {
  const board = JSON.parse(fs.readFileSync(boardFile, "utf8"));
  const ref = {};
  watchdog(ref);
  const browser = (ref.b = await launch());
  // Re-shooting some segments (--only, --device) keeps the others from the last run.
  const manifestFile = path.join(out, `capture-${board.id}.json`);
  const previous = fs.existsSync(manifestFile)
    ? JSON.parse(fs.readFileSync(manifestFile, "utf8")).segments
    : [];
  const shots = new Map(previous.map((s) => [s.id, s]));
  let failed = 0;
  for (const seg of board.segments) {
    if (!DEVICES[seg.device]) continue; // title and end cards are drawn by the build step
    if (deviceFilter && seg.device !== deviceFilter) continue;
    if (only && !only.includes(seg.id)) continue;
    const dir = path.join(out, "frames", seg.id);
    fs.rmSync(dir, { recursive: true, force: true });
    const { ctx, page } = await newPage(
      browser,
      seg.device,
      seg.theme || "light",
    );
    try {
      shots.set(seg.id, await shootSegment(board, seg, page, dir, out));
    } catch (e) {
      failed += 1;
      console.log(
        `${seg.id} ${seg.device}: FAILED ${String(e.message).split("\n")[0]}`,
      );
    } finally {
      fs.rmSync(dir, { recursive: true, force: true });
      await ctx.close();
    }
  }
  const order = board.segments.map((s) => s.id);
  fs.writeFileSync(
    manifestFile,
    JSON.stringify(
      {
        tutorial: board.id,
        base: BASE,
        shot_at: new Date().toISOString(),
        segments: order
          .filter((id) => shots.has(id))
          .map((id) => shots.get(id)),
      },
      null,
      1,
    ),
  );
  await browser.close();
  if (failed) process.exit(1);
}

async function shootSegment(board, seg, page, dir, out) {
  // Setup steps (navigation to the starting screen) are not recorded.
  for (const a of seg.setup || []) await act(page, a, seg.device, []);
  const rec = await startRecording(page, dir, seg.device);
  const t0 = Date.now();
  const stillFiles = [];
  for (const a of seg.actions || []) {
    await act(page, a, seg.device, []);
    if (a.do === "still") {
      const file = path.join(
        out,
        "stills",
        `${board.id}--${seg.id}--${a.label}.png`,
      );
      fs.mkdirSync(path.dirname(file), { recursive: true });
      await page.screenshot({ path: file, type: "png", scale: "device" });
      stillFiles.push({
        label: a.label,
        file: path.relative(out, file),
        t: (Date.now() - t0) / 1000,
      });
    }
  }
  await page.waitForTimeout(seg.tail_ms ?? 500);
  const frames = await rec.stop();
  const clip = path.join(
    out,
    "clips",
    `${board.id}--${seg.id}--${seg.device}.mp4`,
  );
  fs.mkdirSync(path.dirname(clip), { recursive: true });
  if (frames.length < 3)
    throw new Error(`only ${frames.length} frames captured`);
  await encode(frames, clip);
  const seconds = (Date.now() - t0) / 1000;
  console.log(
    `${seg.id} ${seg.device}: ${frames.length - 1} frames, ${seconds.toFixed(1)} s`,
  );
  return {
    id: seg.id,
    device: seg.device,
    clip: path.relative(out, clip),
    seconds,
    frames: frames.length - 1,
    stills: stillFiles,
  };
}

async function cards(specFile, out) {
  const specs = JSON.parse(fs.readFileSync(specFile, "utf8"));
  const ref = {};
  watchdog(ref);
  const browser = (ref.b = await launch());
  const page = await browser.newPage({
    viewport: { width: 1920, height: 1080 },
    deviceScaleFactor: 1,
  });
  for (const c of specs) {
    await page.setContent(c.html, { waitUntil: "load" });
    await page.evaluate(() => document.fonts.ready);
    await page.screenshot({
      path: path.join(out, `${c.name}.png`),
      type: "png",
      omitBackground: !!c.transparent,
    });
  }
  await browser.close();
  console.log(`cards: ${specs.length}`);
}

const [, , mode, a1, a2, ...rest] = process.argv;
const flag = (n) => {
  const i = rest.indexOf(`--${n}`);
  return i >= 0 ? rest[i + 1] : undefined;
};
if (mode === "survey") await survey(a1, a2.split(","), flag("device"));
else if (mode === "shoot")
  await shoot(a1, a2, flag("device"), flag("only")?.split(","));
else if (mode === "cards") await cards(a1, a2);
else {
  console.error(
    "usage: capture.mjs survey <out> <routes> | shoot <board.json> <out>",
  );
  process.exit(2);
}
process.exit(0);
