#!/usr/bin/env node
// Sales X-Ray tutorial capture: drives headless Chromium on ac against the dev server's review fixtures
// (fictional data, no sign-in) and records each storyboard segment as a short clip plus labelled stills.
//
//   node capture.mjs survey <out> <route>[,<route>...] [--device phone|desktop]   screenshots + element list
//   node capture.mjs shoot  <storyboard.json> <out> [--device phone|desktop] [--only seg,seg]
//   node capture.mjs take   <v2-storyboard.json> <out> [--only shot,shot]   v2: one clip per shot, beat and
//                                                      event times (taps, highlights) with target boxes
//   node capture.mjs cards  <cards.json> <out>          1920x1080 PNG per card (title, end, frames)
//   node capture.mjs motion <motion.json> <out>         frame-exact MP4 of an HTML/CSS animation per card
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
  // Tablet: a 1280x800 landscape viewport at 2x (2560x1600 frames), touch on.
  tablet: {
    viewport: { width: 1280, height: 800 },
    deviceScaleFactor: 2,
    isMobile: false,
    hasTouch: true,
  },
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
  // v2 reel phone: a 9:16 screen (390x693 at 3x, 1170x2079 frames) that fills a 1080x1920 reel and
  // sits in the 16:9 tutorials' phone frame.
  reel: {
    viewport: { width: 390, height: 693 },
    deviceScaleFactor: 3,
    isMobile: true,
    hasTouch: true,
  },
  // v2 computer: a 16:9 window (1280x720 at 2x, 2560x1440 frames) for the YouTube tutorials.
  wide: {
    viewport: { width: 1280, height: 720 },
    deviceScaleFactor: 2,
    isMobile: false,
    hasTouch: false,
  },
  // Device frames (owner, 25 Oct 2026: better phones and devices): a modern phone screen at 9:19.5
  // (360x780 at 3x, 1080x2340 frames) and a 16:10 laptop screen (1280x800 at 2x, 2560x1600).
  phone2: {
    viewport: { width: 360, height: 780 },
    deviceScaleFactor: 3,
    isMobile: true,
    hasTouch: true,
  },
  laptop: {
    viewport: { width: 1280, height: 800 },
    deviceScaleFactor: 2,
    isMobile: false,
    hasTouch: false,
  },
};

// A soft ring where the finger or mouse lands, so viewers can follow taps, and a highlight frame, both in
// brand B (Mint on Deep teal). On computer screens a pointer arrow follows the mouse. Pointer events only;
// no layout change.
const TAP_RING = `
(() => {
  if (window.__sxTapRing) return; window.__sxTapRing = true;
  // The script runs before the page has a root element, so the style goes in when first needed.
  const css = '@keyframes sxtap{0%{transform:translate(-50%,-50%) scale(.35);opacity:1}100%{transform:translate(-50%,-50%) scale(1.7);opacity:0}}' +
    '.sx-tap{position:fixed;width:46px;height:46px;border-radius:50%;pointer-events:none;z-index:2147483647;' +
    'background:rgba(61,235,176,.38);border:3px solid #0B4A44;box-shadow:0 0 0 3px rgba(61,235,176,.55);animation:sxtap .75s ease-out forwards}' +
    '.sx-hl{position:fixed;pointer-events:none;z-index:2147483646;border-radius:14px;border:3px solid #3DEBB0;' +
    'box-shadow:0 0 0 2px #0B4A44,0 0 0 9999px rgba(12,26,24,.30);transition:all .35s ease}' +
    '.sx-cursor{position:fixed;left:0;top:0;width:26px;height:26px;pointer-events:none;z-index:2147483647;' +
    'transform:translate(-3px,-2px);display:none}';
  window.__sxStyle = () => {
    if (document.getElementById('sx-overlay-style') || !document.documentElement) return;
    const style = document.createElement('style');
    style.id = 'sx-overlay-style';
    style.textContent = css;
    (document.head || document.documentElement).appendChild(style);
  };
  document.addEventListener('DOMContentLoaded', () => window.__sxStyle());
  // An open modal sheet sits in the browser's top layer, above any z-index: draw inside the topmost one,
  // correcting for a transformed sheet (fixed children are then placed relative to it).
  window.__sxHost = () => {
    let open = [];
    try { open = [...document.querySelectorAll('dialog[open], :popover-open')]; } catch (_) {
      open = [...document.querySelectorAll('dialog[open]')];
    }
    return open.length ? open[open.length - 1] : document.documentElement;
  };
  window.__sxPlace = (el, x, y) => {
    window.__sxStyle();
    const host = window.__sxHost();
    const p = document.createElement('div');
    p.style.cssText = 'position:fixed;left:0;top:0;width:0;height:0;pointer-events:none';
    host.appendChild(p);
    const r = p.getBoundingClientRect();
    p.remove();
    if (el.parentElement !== host) host.appendChild(el);
    el.style.left = (x - r.left) + 'px'; el.style.top = (y - r.top) + 'px';
  };
  addEventListener('pointerdown', (e) => {
    const d = document.createElement('div'); d.className = 'sx-tap';
    window.__sxPlace(d, e.clientX, e.clientY);
    setTimeout(() => d.remove(), 850);
  }, true);
  addEventListener('mousemove', (e) => {
    if (window.__sxNoCursor) return;
    let c = document.querySelector('.sx-cursor');
    if (!c) {
      window.__sxStyle();
      c = document.createElement('div'); c.className = 'sx-cursor';
      c.innerHTML = '<svg viewBox="0 0 26 26" width="26" height="26"><path d="M3 2l17 10.5-7.4 1.6 4.3 8.3-3.3 1.6-4.2-8.4L3 21z" fill="#0C1A18" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>';
      document.documentElement.appendChild(c);
    }
    c.style.display = 'block';
    c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px';
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

// `scale` forces the browser's own pixel ratio: without it the screencast sends CSS-size frames (390 px
// wide for a phone), with it the full 3x frames that a 1080x1920 reel needs.
async function launch(scale) {
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
      ...(scale ? [`--force-device-scale-factor=${scale}`] : []),
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
    // The tap ring and highlight frame are an injected style sheet; a strict page policy must not drop it.
    bypassCSP: true,
  });
  // Touch screens show the tap ring only; the pointer arrow is for computer screens.
  if (DEVICES[device].hasTouch)
    await ctx.addInitScript("window.__sxNoCursor = true;");
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
    const host = window.__sxHost ? window.__sxHost() : document.documentElement;
    if (!n || n.parentElement !== host) {
      n?.remove();
      n = document.createElement("div");
      n.className = "sx-hl";
    }
    Object.assign(n.style, {
      width: b.width + 12 + "px",
      height: b.height + 12 + "px",
    });
    if (window.__sxPlace) window.__sxPlace(n, b.x - 6, b.y - 6);
    else {
      document.documentElement.appendChild(n);
      Object.assign(n.style, { left: b.x - 6 + "px", top: b.y - 6 + "px" });
    }
  }, box);
}

// Returns what the viewer sees happen ({do, t, box}: epoch seconds, target box in CSS px) for the v2
// editor's zooms and sync, or null for actions that change nothing on screen.
async function act(page, a, device, stills) {
  if (a.optional && a.do !== "hide") {
    // Things that may or may not be on screen (a one-time tip): try briefly, carry on without.
    try {
      await locate(page, a.target).waitFor({ state: "visible", timeout: 2500 });
    } catch {
      return null;
    }
  }
  const loc = locate(page, a.target);
  let ev = null;
  const mark = (box) => {
    ev = {
      do: a.do,
      t: Date.now() / 1000,
      box: box ? { x: box.x, y: box.y, w: box.width, h: box.height } : null,
    };
    if (a.zoom !== undefined) ev.zoom = a.zoom;
    if (a.key) ev.key = true;
  };
  const touch = DEVICES[device].hasTouch;
  // Scroll the target into view before measuring it, so the camera aims where it really is.
  const seen = async () => {
    await loc.scrollIntoViewIfNeeded().catch(() => {});
    return loc.boundingBox();
  };
  switch (a.do) {
    case "goto":
      mark(null);
      await open(page, a.url);
      await page.waitForTimeout(a.ms ?? 900);
      break;
    case "tap": {
      await loc.scrollIntoViewIfNeeded();
      await page.waitForTimeout(a.before ?? 450);
      const box = await loc.boundingBox();
      if (touch) {
        mark(box);
        await loc.tap();
      } else {
        // Glide the pointer in so the arrow travels to the button instead of jumping.
        if (box)
          await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, {
            steps: 16,
          });
        await page.waitForTimeout(160);
        mark(box);
        await loc.click();
      }
      await page.waitForTimeout(a.ms ?? 1100);
      break;
    }
    case "type":
      mark(await seen());
      await loc.click();
      await page.keyboard.type(a.text, { delay: a.delay ?? 55 });
      await page.waitForTimeout(a.ms ?? 600);
      break;
    case "fill":
      mark(await seen());
      await loc.fill(a.text);
      await page.waitForTimeout(a.ms ?? 600);
      break;
    case "hide":
      // Fixture-only messages ("Sample data only.") and the usage lines the owner keeps out of
      // tutorials (analysis minutes left, minutes per call). Hides the smallest wrapper around
      // just that text, icon included, and keeps it hidden when the page redraws.
      await page.evaluate(
        ({ needle, collapse }) => {
          const apply = () => {
            const walker = document.createTreeWalker(
              document.body,
              NodeFilter.SHOW_TEXT,
            );
            for (let t = walker.nextNode(); t; t = walker.nextNode()) {
              if (!t.nodeValue || !t.nodeValue.includes(needle)) continue;
              let node = t.parentElement;
              while (
                node.parentElement &&
                node.parentElement !== document.body &&
                node.parentElement.textContent.trim() ===
                  node.textContent.trim()
              )
                node = node.parentElement;
              if (collapse) node.style.display = "none";
              else node.style.visibility = "hidden";
            }
          };
          apply();
          new MutationObserver(apply).observe(document.body, {
            childList: true,
            subtree: true,
            characterData: true,
          });
        },
        { needle: a.target.text, collapse: !!a.collapse },
      );
      await page.waitForTimeout(a.ms ?? 200);
      break;
    case "scrollto":
      // Brings a heading to the top of the screen, leaving `offset` px above it (sticky bars
      // included). parent=true scrolls the anchor's own scroller (a panel), not the window.
      mark(null);
      await loc.evaluate(
        (el, { offset, parent }) => {
          el.scrollIntoView({ block: "start" });
          let box = null;
          if (parent) {
            box = el.parentElement;
            while (box) {
              const oy = getComputedStyle(box).overflowY;
              if (
                box.scrollHeight > box.clientHeight &&
                (oy === "auto" || oy === "scroll")
              )
                break;
              box = box.parentElement;
            }
          }
          (box || window).scrollBy(0, -offset);
        },
        { offset: a.offset ?? 96, parent: !!a.parent },
      );
      await page.waitForTimeout(a.ms ?? 600);
      break;
    case "frost":
      // Headless Chromium draws no backdrop blur, so text shows through glass bars; give every
      // blurred element a near-opaque fill in the page's own theme, close to the blur on a phone.
      // Sheets and bars that open later get the same fill (one pass per animation frame at most).
      await page.evaluate(() => {
        const apply = () => {
          const bg = getComputedStyle(document.body).backgroundColor.match(
            /\d+/g,
          ) || [255, 255, 255];
          const dark =
            bg.slice(0, 3).reduce((s, v) => s + Number(v), 0) < 3 * 96;
          const fill = dark ? "rgba(22,22,24,0.97)" : "rgba(248,249,251,0.97)";
          for (const el of document.querySelectorAll("body *")) {
            if (el.dataset.sxFrost) continue;
            // A dimmed backdrop behind a sheet covers the screen; it stays see-through.
            const r = el.getBoundingClientRect();
            if (r.width * r.height > 0.7 * innerWidth * innerHeight) continue;
            const cs = getComputedStyle(el);
            const blur = cs.backdropFilter || cs.webkitBackdropFilter;
            if (blur && blur !== "none") {
              el.style.backgroundColor = fill;
              el.dataset.sxFrost = "1";
            }
          }
        };
        apply();
        if (window.__sxFrost) return;
        window.__sxFrost = true;
        let queued = false;
        new MutationObserver(() => {
          if (queued) return;
          queued = true;
          requestAnimationFrame(() => {
            queued = false;
            apply();
          });
        }).observe(document.body, { childList: true, subtree: true });
      });
      await page.waitForTimeout(a.ms ?? 150);
      break;
    case "marketing":
      // Store screenshots only: the fixtures' demo names ("Asha Fictional") become realistic made-up
      // ones, initial avatars get colours, and the empty account avatar gets the user's initials.
      await page.evaluate(
        ({ names, me }) => {
          const pairs = Object.entries(names).sort(
            (x, y) => y[0].length - x[0].length,
          );
          const palette = [
            "#0f766e",
            "#0e7490",
            "#7c3aed",
            "#c2410c",
            "#be185d",
            "#15803d",
            "#1d4ed8",
            "#b45309",
          ];
          // Two capital letters are avatar initials: swap only a text that is exactly them.
          const initials = pairs.filter(([from]) => /^[A-Z]{2}$/.test(from));
          const words = pairs.filter(([from]) => !/^[A-Z]{2}$/.test(from));
          // Phone numbers keep only their first two and last three digits: +91 98XXX XX210.
          const mask = (s) =>
            s.replace(
              /(\+91[\s-]?)?\b([6-9]\d)(\d{3})[\s-]?(\d{2})(\d{3})\b/g,
              (_m, cc, a, _b, _c, d) => `${cc || ""}${a}XXX XX${d}`,
            );
          // Fixture people the map doesn't name ("Rohan Sample", "Pooja Fictional") get a realistic
          // surname, the same one every time for the same first name.
          const surnames = [
            "Kale",
            "Jadhav",
            "Pawar",
            "Shinde",
            "Deshpande",
            "Gaikwad",
            "More",
            "Salunkhe",
            "Chavan",
            "Sawant",
            "Pande",
            "Kamat",
            "Rane",
            "Wagh",
            "Bapat",
          ];
          const surname = (first) =>
            surnames[
              [...first].reduce(
                (h, c) => (h * 31 + c.charCodeAt(0)) % 9973,
                7,
              ) % surnames.length
            ];
          const people = (s) =>
            s.replace(
              /\b([A-Z][a-z]{2,}) (?:Sample|Fictional|Example)\b/g,
              (_m, first) => `${first} ${surname(first)}`,
            );
          const swap = (s) => {
            const hit = initials.find(([from]) => s.trim() === from);
            if (hit) return s.replace(hit[0], hit[1]);
            return mask(
              people(
                words.reduce((t, [from, to]) => t.split(from).join(to), s),
              ),
            );
          };
          const round = (el) => {
            const r = el.getBoundingClientRect();
            const radius =
              parseFloat(getComputedStyle(el).borderTopLeftRadius) || 0;
            return (
              r.width >= 20 &&
              r.width <= 80 &&
              Math.abs(r.width - r.height) < 3 &&
              radius >= r.width / 2 - 2
            );
          };
          const apply = () => {
            const walker = document.createTreeWalker(
              document.body,
              NodeFilter.SHOW_TEXT,
            );
            for (let t = walker.nextNode(); t; t = walker.nextNode()) {
              const next = swap(t.nodeValue || "");
              if (next !== t.nodeValue) t.nodeValue = next;
            }
            for (const el of document.querySelectorAll("input, textarea")) {
              const next = swap(el.value || "");
              if (next !== el.value) el.value = next;
              // Sample numbers in empty fields are masked too (an attribute change; no loop).
              const hint = el.getAttribute("placeholder");
              if (hint && swap(hint) !== hint)
                el.setAttribute("placeholder", swap(hint));
            }
            for (const el of document.querySelectorAll("body *")) {
              if (el.dataset.sxAvatar || !round(el)) continue;
              const text = el.textContent.trim();
              if (/^[A-Z]{2}$/.test(text)) {
                const hash = [...text].reduce(
                  (h, c) => h * 31 + c.charCodeAt(0),
                  7,
                );
                el.style.background = palette[Math.abs(hash) % palette.length];
                el.style.color = "#fff";
                el.dataset.sxAvatar = "1";
              } else if (
                !text &&
                !el.querySelector("img,svg") &&
                el.getBoundingClientRect().top < 80
              ) {
                el.style.background = "linear-gradient(135deg,#2dd4bf,#0f766e)";
                el.style.display = "grid";
                el.style.placeItems = "center";
                el.style.color = "#fff";
                el.style.font = "700 15px system-ui, sans-serif";
                el.textContent = me;
                el.dataset.sxAvatar = "1";
              }
            }
          };
          apply();
          new MutationObserver(apply).observe(document.body, {
            childList: true,
            subtree: true,
            characterData: true,
          });
        },
        { names: a.names || {}, me: a.me || "" },
      );
      await page.waitForTimeout(a.ms ?? 300);
      break;
    case "glow":
      // One highlighted element per store shot: a teal ring and soft glow. `up` lifts it to a
      // parent; card=true climbs to the first wide element with its own background or border.
      await loc.evaluate(
        (el, { up, card }) => {
          let n = el;
          for (let i = 0; i < up && n.parentElement; i++) n = n.parentElement;
          const isCard = (e) => {
            const cs = getComputedStyle(e);
            const clear =
              cs.backgroundColor === "rgba(0, 0, 0, 0)" ||
              cs.backgroundColor === "transparent";
            return (
              e.getBoundingClientRect().width > 220 &&
              (!clear || parseFloat(cs.borderTopWidth) > 0)
            );
          };
          while (card && n.parentElement && !isCard(n)) n = n.parentElement;
          n.style.boxShadow =
            "0 0 0 4px #2dd4bf, 0 0 40px 12px rgba(45,212,191,.55)";
          n.style.position = n.style.position || "relative";
          n.style.zIndex = "5";
        },
        { up: a.up ?? 0, card: !!a.card },
      );
      await page.waitForTimeout(a.ms ?? 200);
      break;
    case "select":
      // Native <select> menus do not open in headless Chromium; pick the option directly.
      mark(await seen());
      await loc.selectOption({ label: a.option });
      await page.waitForTimeout(a.ms ?? 1200);
      break;
    case "paste": {
      // A real paste event with rows on the clipboard, as when a seller pastes from Sheets.
      mark(await seen());
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
      mark(null);
      await page.keyboard.press(a.key);
      await page.waitForTimeout(a.ms ?? 700);
      break;
    case "scroll": {
      mark(null);
      const steps = a.steps ?? 12;
      for (let i = 0; i < steps; i++) {
        await page.mouse.wheel(0, (a.dy ?? 600) / steps);
        await page.waitForTimeout(30);
      }
      await page.waitForTimeout(a.ms ?? 700);
      break;
    }
    case "hover":
      mark(await seen());
      await loc.hover();
      await page.waitForTimeout(a.ms ?? 700);
      break;
    case "highlight":
      mark(await seen());
      if (a.ring !== false) await highlight(page, loc, true);
      await page.waitForTimeout(a.ms ?? 1200);
      break;
    case "focus":
      // v2: point the camera at something without drawing a frame round it.
      mark(await seen());
      await page.waitForTimeout(a.ms ?? 900);
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
  return ev;
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
    try {
      fs.writeFileSync(file, Buffer.from(f.data, "base64"));
    } catch {
      return; // the shot failed and its folder is gone; late frames are dropped
    }
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
          fullPage: DEVICES[dev].isMobile,
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

// v2: a shot is one continuous recording (its setup runs first, unrecorded) made of beats; a beat is one
// narration line and the actions seen while it plays. The manifest gives each beat's start and end and
// each visible event's time and target box, in seconds and pixels of the clip.
async function take(boardFile, out, only) {
  const board = JSON.parse(fs.readFileSync(boardFile, "utf8"));
  const ref = {};
  watchdog(ref);
  // One browser per pixel ratio (phone 3x, computer 2x), each launched when first needed.
  const browsers = new Map();
  const browserFor = async (device) => {
    const k = DEVICES[device].deviceScaleFactor;
    if (!browsers.has(k)) browsers.set(k, (ref.b = await launch(k)));
    return browsers.get(k);
  };
  const manifestFile = path.join(out, `take-${board.id}.json`);
  const previous = fs.existsSync(manifestFile)
    ? JSON.parse(fs.readFileSync(manifestFile, "utf8")).shots
    : [];
  const shots = new Map(previous.map((s) => [s.id, s]));
  let failed = 0;
  for (const shot of board.shots) {
    if (!DEVICES[shot.device]) continue; // step cards are drawn, not recorded
    if (only && !only.includes(shot.id)) continue;
    const dir = path.join(out, "frames", shot.id);
    fs.rmSync(dir, { recursive: true, force: true });
    const { ctx, page } = await newPage(
      await browserFor(shot.device),
      shot.device,
      shot.theme || "light",
    );
    try {
      shots.set(shot.id, await takeShot(board, shot, page, dir, out));
    } catch (e) {
      failed += 1;
      console.log(`${shot.id}: FAILED ${String(e.message).split("\n")[0]}`);
    } finally {
      fs.rmSync(dir, { recursive: true, force: true });
      await ctx.close();
    }
  }
  fs.writeFileSync(
    manifestFile,
    JSON.stringify(
      {
        tutorial: board.id,
        base: BASE,
        taken_at: new Date().toISOString(),
        shots: board.shots
          .filter((s) => DEVICES[s.device])
          .map((s) => s.id)
          .filter((id) => shots.has(id))
          .map((id) => shots.get(id)),
      },
      null,
      1,
    ),
  );
  for (const b of browsers.values()) await b.close();
  if (failed) process.exit(1);
}

// Owner rules on what the picture shows (tutorials never show prices, costs or usage minutes): the
// visible text inside the screen, checked after every action. The editor refuses a take with any of
// these. Waiting times on chats and leads ("3 min") are not usage and may show.
async function onScreenRules(page) {
  return page.evaluate(() => {
    const seen = [];
    const rule =
      /₹|\bRs\.?\s?\d|\bINR\b|\bminutes? (?:left|remaining|used|included|of analysis)|\bmins? left\b|\bper min(?:ute)?\b|\/\s?min\b|analysis minutes|\bcredits?\b/i;
    const walker = document.createTreeWalker(
      document.body,
      NodeFilter.SHOW_TEXT,
    );
    for (let t = walker.nextNode(); t; t = walker.nextNode()) {
      const s = t.nodeValue || "";
      if (!rule.test(s)) continue;
      const el = t.parentElement;
      const r = el.getBoundingClientRect();
      const cs = getComputedStyle(el);
      const shown =
        r.width > 0 &&
        r.height > 0 &&
        r.bottom > 0 &&
        r.top < innerHeight &&
        cs.visibility !== "hidden" &&
        el.closest("[hidden],[aria-hidden=true]") === null &&
        el.checkVisibility?.({ opacityProperty: true }) !== false;
      if (shown) seen.push(s.trim().slice(0, 60));
    }
    return seen;
  });
}

async function takeShot(board, shot, page, dir, out) {
  for (const a of shot.setup || []) await act(page, a, shot.device, []);
  await page.waitForTimeout(shot.settle_ms ?? 400);
  const rec = await startRecording(page, dir, shot.device);
  await page.waitForTimeout(shot.lead_ms ?? 300);
  const beats = [];
  for (const beat of shot.beats) {
    const b = { id: beat.id, t0: Date.now() / 1000, events: [] };
    for (const a of beat.actions || []) {
      const ev = await act(page, a, shot.device, []);
      if (ev) b.events.push(ev);
      b.warnings = [
        ...new Set([...(b.warnings || []), ...(await onScreenRules(page))]),
      ];
    }
    b.t1 = Date.now() / 1000;
    if (!b.warnings.length) delete b.warnings;
    else
      console.log(`${shot.id}/${beat.id}: ON SCREEN ${b.warnings.join(" | ")}`);
    beats.push(b);
  }
  await page.waitForTimeout(shot.tail_ms ?? 400);
  const frames = await rec.stop();
  if (frames.length < 3)
    throw new Error(`only ${frames.length} frames captured`);
  const clip = path.join(out, "clips", `${board.id}--${shot.id}.mp4`);
  fs.mkdirSync(path.dirname(clip), { recursive: true });
  await encode(frames, clip);
  const zero = frames[0].t;
  const k = DEVICES[shot.device].deviceScaleFactor;
  const rel = (t) => Math.max(0, Number((t - zero).toFixed(3)));
  const px = (box) =>
    box && {
      x: Math.round(box.x * k),
      y: Math.round(box.y * k),
      w: Math.round(box.w * k),
      h: Math.round(box.h * k),
    };
  const seconds = rel(frames.at(-1).t);
  console.log(
    `${shot.id} ${shot.device}: ${frames.length - 1} frames, ${seconds.toFixed(1)} s`,
  );
  return {
    id: shot.id,
    device: shot.device,
    clip: path.relative(out, clip),
    width: DEVICES[shot.device].viewport.width * k,
    height: DEVICES[shot.device].viewport.height * k,
    seconds,
    beats: beats.map((b) => ({
      id: b.id,
      t0: rel(b.t0),
      t1: rel(b.t1),
      events: b.events.map((e) => ({ ...e, t: rel(e.t), box: px(e.box) })),
    })),
  };
}

// v2 motion graphics: every CSS animation on the card is paused and stepped frame by frame, so a busy
// server still gives smooth 30 fps. Spec: [{name, html, width, height, seconds, fps?}] -> <out>/<name>.mp4
async function motion(specFile, out) {
  const specs = JSON.parse(fs.readFileSync(specFile, "utf8"));
  const ref = {};
  watchdog(ref);
  const browser = (ref.b = await launch());
  fs.mkdirSync(out, { recursive: true });
  for (const c of specs) {
    const page = await browser.newPage({
      viewport: { width: c.width ?? 1920, height: c.height ?? 1080 },
      deviceScaleFactor: 1,
    });
    await page.setContent(c.html, { waitUntil: "load" });
    await page.evaluate(() => document.fonts.ready);
    await page.evaluate(() =>
      Promise.all(
        [...document.images].map((i) =>
          i.complete ? null : i.decode().catch(() => null),
        ),
      ),
    );
    const fps = c.fps ?? 30;
    const n = Math.round((c.seconds ?? 3) * fps);
    const dir = path.join(out, `${c.name}-frames`);
    fs.rmSync(dir, { recursive: true, force: true });
    fs.mkdirSync(dir, { recursive: true });
    for (let i = 0; i < n; i++) {
      await page.evaluate(
        (ms) => {
          for (const an of document.getAnimations()) {
            an.pause();
            an.currentTime = ms;
          }
        },
        (i * 1000) / fps,
      );
      await page.screenshot({
        path: path.join(dir, `f${String(i).padStart(5, "0")}.jpg`),
        type: "jpeg",
        quality: 94,
      });
    }
    await page.close();
    await encodeSequence(dir, fps, path.join(out, `${c.name}.mp4`));
    fs.rmSync(dir, { recursive: true, force: true });
    console.log(`motion ${c.name}: ${n} frames`);
  }
  await browser.close();
}

function encodeSequence(dir, fps, outFile) {
  return new Promise((res, rej) => {
    const p = spawn(
      "nice",
      [
        ...["-n", "19", "ionice", "-c3", "ffmpeg", "-y", "-loglevel", "error"],
        ...["-framerate", String(fps), "-i", path.join(dir, "f%05d.jpg")],
        ...[
          "-c:v",
          "libx264",
          "-preset",
          "medium",
          "-crf",
          "15",
          "-threads",
          "2",
        ],
        ...["-pix_fmt", "yuv420p", "-movflags", "+faststart", outFile],
      ],
      { stdio: "inherit" },
    );
    p.on("exit", (c) => (c === 0 ? res() : rej(new Error(`ffmpeg ${c}`))));
  });
}

async function cards(specFile, out) {
  // Each card: {name, html, width?, height?, scale?, transparent?, jpeg?}; 1920x1080 at 1x by default.
  const specs = JSON.parse(fs.readFileSync(specFile, "utf8"));
  const ref = {};
  watchdog(ref);
  const browser = (ref.b = await launch());
  for (const c of specs) {
    const page = await browser.newPage({
      viewport: { width: c.width ?? 1920, height: c.height ?? 1080 },
      deviceScaleFactor: c.scale ?? 1,
    });
    await page.setContent(c.html, { waitUntil: "load" });
    await page.evaluate(() => document.fonts.ready);
    await page.evaluate(() =>
      Promise.all(
        [...document.images].map((i) =>
          i.complete ? null : i.decode().catch(() => null),
        ),
      ),
    );
    const file = path.join(out, `${c.name}.${c.jpeg ? "jpg" : "png"}`);
    await page.screenshot(
      c.jpeg
        ? { path: file, type: "jpeg", quality: 92 }
        : { path: file, type: "png", omitBackground: !!c.transparent },
    );
    await page.close();
  }
  await browser.close();
  console.log(`cards: ${specs.length}`);
}

// Storyboard help: run each spec's setup, then save a small screenshot and the list of buttons, tabs,
// fields and headings with their boxes. [{name, device, setup}] -> <out>/<name>.jpg and .txt
async function probe(specFile, out) {
  const specs = JSON.parse(fs.readFileSync(specFile, "utf8"));
  const ref = {};
  watchdog(ref);
  const browser = (ref.b = await launch());
  fs.mkdirSync(out, { recursive: true });
  for (const s of specs) {
    const { ctx, page } = await newPage(browser, s.device, s.theme || "light");
    try {
      // dump: every text the page showed along the way (to find names a video would show).
      const seenText = new Set();
      for (const a of s.setup || []) {
        await act(page, a, s.device, []);
        if (s.dump)
          for (const line of (
            await page.evaluate(() => document.body.innerText)
          ).split("\n"))
            if (line.trim()) seenText.add(line.trim());
      }
      if (s.dump)
        fs.writeFileSync(
          path.join(out, `${s.name}.text.txt`),
          [...seenText].join("\n") + "\n",
        );
      await page.waitForTimeout(s.settle_ms ?? 700);
      await page.screenshot({
        path: path.join(out, `${s.name}.jpg`),
        type: "jpeg",
        quality: 70,
        scale: "css",
      });
      const els = await page.evaluate(() =>
        [
          ...document.querySelectorAll(
            "button,a,[role=tab],[role=button],[role=radio],[role=option],input,textarea,select,h1,h2,h3,label,[role=switch],[role=checkbox],[role=dialog]",
          ),
        ]
          .filter((e) => {
            const b = e.getBoundingClientRect();
            return b.width > 0 && b.height > 0;
          })
          .slice(0, 160)
          .map((e) => {
            const b = e.getBoundingClientRect();
            const name = (
              e.getAttribute("aria-label") ||
              e.innerText ||
              e.getAttribute("placeholder") ||
              ""
            )
              .trim()
              .replace(/\s+/g, " ")
              .slice(0, 70);
            const role = e.getAttribute("role");
            return `${e.tagName.toLowerCase()}${role ? "[" + role + "]" : ""} "${name}" @${Math.round(b.x)},${Math.round(b.y)} ${Math.round(b.width)}x${Math.round(b.height)}`;
          }),
      );
      fs.writeFileSync(path.join(out, `${s.name}.txt`), els.join("\n") + "\n");
      const overlay = await page.evaluate(() => {
        const n = document.querySelector(".sx-hl");
        if (!n) return `no frame; helpers ${typeof window.__sxHost}`;
        const r = n.getBoundingClientRect();
        const cs = getComputedStyle(n);
        return `frame in <${n.parentElement.tagName.toLowerCase()}> at ${Math.round(r.x)},${Math.round(r.y)} ${Math.round(r.width)}x${Math.round(r.height)} pos=${cs.position} border=${cs.borderTopWidth} ${cs.borderTopColor} vis=${cs.visibility} op=${cs.opacity}`;
      });
      console.log(`${s.name}: ok, ${els.length} elements; ${overlay}`);
    } catch (e) {
      console.log(`${s.name}: FAILED ${String(e.message).split("\n")[0]}`);
    } finally {
      await ctx.close();
    }
  }
  await browser.close();
}

// Full-resolution screenshots of screens (phone 1170x2532, desktop 2880x1800): [{name, device, setup}].
async function stills(specFile, out) {
  const specs = JSON.parse(fs.readFileSync(specFile, "utf8"));
  const ref = {};
  watchdog(ref);
  const browser = (ref.b = await launch());
  fs.mkdirSync(out, { recursive: true });
  let failed = 0;
  for (const s of specs) {
    const { ctx, page } = await newPage(browser, s.device, s.theme || "light");
    try {
      for (const a of s.setup || []) await act(page, a, s.device, []);
      await page.waitForTimeout(s.settle_ms ?? 700);
      await page.screenshot({
        path: path.join(out, `${s.name}.png`),
        type: "png",
        scale: "device",
      });
      console.log(`${s.name}: ok`);
    } catch (e) {
      failed += 1;
      console.log(`${s.name}: FAILED ${String(e.message).split("\n")[0]}`);
    } finally {
      await ctx.close();
    }
  }
  await browser.close();
  if (failed) process.exit(1);
}

const [, , mode, a1, a2, ...rest] = process.argv;
const flag = (n) => {
  const i = rest.indexOf(`--${n}`);
  return i >= 0 ? rest[i + 1] : undefined;
};
if (mode === "survey") await survey(a1, a2.split(","), flag("device"));
else if (mode === "shoot")
  await shoot(a1, a2, flag("device"), flag("only")?.split(","));
else if (mode === "take") await take(a1, a2, flag("only")?.split(","));
else if (mode === "cards") await cards(a1, a2);
else if (mode === "motion") await motion(a1, a2);
else if (mode === "stills") await stills(a1, a2);
else if (mode === "probe") await probe(a1, a2);
else {
  console.error(
    "usage: capture.mjs survey <out> <routes> | shoot|take <board.json> <out> | cards|motion|stills <spec.json> <out>",
  );
  process.exit(2);
}
process.exit(0);
