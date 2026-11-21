// The screen guard (owner, 21 Nov 2026: Home, Leads and the bottom panel stay exactly as they are). Home, the Leads
// page and the phone's bottom tab bar, from the review fixtures (fictional data, no API origin, no credentials), at
// 390x844 and 1440x900, light and dark, compared pixel by pixel with the PNGs in scripts/ci/guard-baselines/. Any
// pixel whose red, green, blue or alpha differs by more than 8 fails the run, as does a size change. wb-ci's visual
// job runs it after the screenshots.
//
//   node scripts/ci/wb_guard_screens.mjs <output-dir> [--update] [--baselines <dir>] [--only <frame-prefix>]
//
// --update writes the baselines instead of comparing. With no baseline PNGs at all it records them in
// <output-dir>/baselines/ and passes, saying so: baselines come from a GitHub runner, never from ac. A deliberate
// change to these screens is re-recorded the same way (wb-ci run, download, commit the PNGs).
//
// The output: report.md (also the step summary), guard.json, and for each failing frame its current render and a
// diff image (changed pixels red over a faded baseline).
import {
  appendFile,
  mkdir,
  readdir,
  readFile,
  writeFile,
} from "node:fs/promises";
import { cpus } from "node:os";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { chromium } from "playwright";
import { fixtureServer, local, origin as fixtureOrigin } from "./wb_matrix.mjs";

/** A channel may differ by this much (anti-aliasing noise); anything more is a changed pixel. */
export const TOLERANCE = 8;
/** Changed pixels allowed per frame. */
export const ALLOWED = 0;
/** Fresh renders of a frame that differs, before it counts as changed. */
export const RETRIES = 2;
/**
 * The same pixels on every runner: GitHub's runners come with different CPUs, and Skia's CPU-specific fast paths
 * anti-alias an edge a step apart on each (the Leads logo's rim was 9 off between two runs, 21 Nov 2026). These
 * turn the fast paths off and pin the colour profile, as Chromium's own pixel tests do.
 */
export const CHROMIUM_ARGS = [
  "--disable-skia-runtime-opts",
  "--force-color-profile=srgb",
];
/** How long a page settles after its ready mark before the shots (Home's read-health card comes at 8 s). */
export const SETTLE_MS = 9000;

const NAV = 'nav[aria-label="Mobile Sales Xray navigation"]';
const PHONE = { width: 390, height: 844 };
const DESKTOP = { width: 1440, height: 900 };
const SCHEMES = ["light", "dark"];

/** The guarded screens: whole-viewport renders of Home and Leads, and the tab bar alone on three pages. */
export const SCREENS = [
  {
    key: "home-owner",
    route: "/review-fixture/home",
    ready: "main",
    sizes: [PHONE, DESKTOP],
  },
  {
    key: "home-seller",
    route: "/review-fixture/home?role=seller",
    ready: "main",
    sizes: [PHONE, DESKTOP],
  },
  {
    key: "leads",
    route: "/review-fixture/leads",
    ready: "[data-lead-row]",
    readyWide: "main",
    sizes: [PHONE, DESKTOP],
  },
  {
    key: "tabbar-home",
    route: "/review-fixture/home",
    ready: NAV,
    element: NAV,
    sizes: [PHONE],
  },
  {
    key: "tabbar-leads",
    route: "/review-fixture/leads",
    ready: NAV,
    element: NAV,
    sizes: [PHONE],
  },
  {
    key: "tabbar-shell",
    route: "/review-fixture/shell",
    ready: NAV,
    element: NAV,
    sizes: [PHONE],
  },
];

export function guardFrames(screens = SCREENS) {
  return screens.flatMap((screen) =>
    screen.sizes.flatMap((size) =>
      SCHEMES.map((scheme) => ({
        ...screen,
        size,
        scheme,
        name: `${screen.key}-${size.width}-${scheme}`,
      })),
    ),
  );
}

/**
 * Runs in the browser: decodes two PNG data URLs on a canvas and counts the pixels where any channel differs by
 * more than `tolerance`. Returns the sizes, the count and a diff PNG (data URL) when they differ.
 */
export async function comparePngs([baseline, current, tolerance]) {
  const decode = async (url) => {
    const image = new Image();
    image.src = url;
    await image.decode();
    const canvas = document.createElement("canvas");
    canvas.width = image.naturalWidth;
    canvas.height = image.naturalHeight;
    const context = canvas.getContext("2d", { willReadFrequently: true });
    context.drawImage(image, 0, 0);
    return {
      width: canvas.width,
      height: canvas.height,
      data: context.getImageData(0, 0, canvas.width, canvas.height).data,
    };
  };
  const a = await decode(baseline);
  const b = await decode(current);
  const sizes = { baseline: [a.width, a.height], current: [b.width, b.height] };
  if (a.width !== b.width || a.height !== b.height)
    return { ...sizes, sizeMismatch: true, changed: null };
  const canvas = document.createElement("canvas");
  canvas.width = a.width;
  canvas.height = a.height;
  const context = canvas.getContext("2d");
  const out = context.createImageData(a.width, a.height);
  let changed = 0;
  let box = null;
  for (let i = 0; i < a.data.length; i += 4) {
    let differs = false;
    for (let c = 0; c < 4; c++)
      if (Math.abs(a.data[i + c] - b.data[i + c]) > tolerance) differs = true;
    if (differs) {
      changed++;
      const x = (i / 4) % a.width;
      const y = Math.floor(i / 4 / a.width);
      box = box
        ? [
            Math.min(box[0], x),
            Math.min(box[1], y),
            Math.max(box[2], x),
            Math.max(box[3], y),
          ]
        : [x, y, x, y];
      out.data.set([255, 0, 0, 255], i);
    } else {
      const grey = (a.data[i] + a.data[i + 1] + a.data[i + 2]) / 3;
      const faded = 255 - (255 - grey) * 0.25;
      out.data.set([faded, faded, faded, 255], i);
    }
  }
  let diff = null;
  if (changed) {
    context.putImageData(out, 0, 0);
    diff = canvas.toDataURL("image/png");
  }
  return { ...sizes, sizeMismatch: false, changed, box, diff };
}

const dataUrl = (buffer) =>
  `data:image/png;base64,${buffer.toString("base64")}`;

function argument(name) {
  const at = process.argv.indexOf(name);
  return at > 0 ? process.argv[at + 1] : undefined;
}

async function pngsIn(dir) {
  try {
    return (await readdir(dir)).filter((name) => name.endsWith(".png"));
  } catch {
    return [];
  }
}

/** One frame, rendered the same way every time: frozen clock, no motion, no caret, fonts and images settled. */
async function render(browser, origin, frame, notes = []) {
  const context = await browser.newContext({
    viewport: frame.size,
    deviceScaleFactor: 1,
    colorScheme: frame.scheme,
    isMobile: frame.size.width < 768,
    hasTouch: frame.size.width < 768,
    locale: "en-GB",
    timezoneId: "UTC",
    reducedMotion: "reduce",
    serviceWorkers: "block",
    acceptDownloads: false,
  });
  try {
    // The app is dark by its own key, not by the browser setting.
    await context.addInitScript((theme) => {
      try {
        window.localStorage.setItem("sales-xray:theme", theme);
      } catch {
        /* storage blocked: the page stays on its default */
      }
    }, frame.scheme);
    // Same-origin reads only; nothing leaves the runner (the fixtures answer their own /v1 reads in the page).
    await context.route("**/*", local);
    const page = await context.newPage();
    // What went wrong in the page, for the report (paths and first lines only: the data is fictional).
    page.on("pageerror", (error) =>
      notes.push(
        `error: ${String(error.message).split("\n")[0].slice(0, 120)}`,
      ),
    );
    page.on("console", (message) => {
      if (message.type() === "error")
        notes.push(`console: ${message.text().split("\n")[0].slice(0, 120)}`);
    });
    page.on("response", (response) => {
      if (response.status() >= 400)
        notes.push(`${response.status()} ${new URL(response.url()).pathname}`);
    });
    page.setDefaultTimeout(15000);
    await page.clock.setFixedTime(new Date("2026-10-03T12:00:00Z"));
    // The lead desk keeps reading (pollers), so the page never goes network-idle: wait for its own mark.
    await page.goto(origin + frame.route, {
      waitUntil: "load",
      timeout: 90000,
    });
    await page
      .locator(
        frame.size.width >= 768
          ? (frame.readyWide ?? frame.ready)
          : frame.ready,
      )
      .first()
      .waitFor({ state: "visible", timeout: 30000 });
    // [data-capture-skip] is what the app leaves out of its own captures (bug-report/capture.ts): the notice cards,
    // the report button, the feedback prompt. They come and go with timing (a dev-server hydration mismatch against
    // the frozen clock raises "Something glitched" in some runs and not others), so the guard leaves them out too.
    await page.addStyleTag({
      content:
        "*,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important}" +
        "nextjs-portal,[data-capture-skip]{display:none!important}",
    });
    await page.evaluate(async () => {
      if (document.activeElement instanceof HTMLElement)
        document.activeElement.blur();
      await document.fonts.ready;
      await Promise.all(
        [...document.images].map((image) =>
          image.decode().catch(() => undefined),
        ),
      );
    });
    await page.mouse.move(0, 0);
    // Two stable renders in a row (late data, a font swap) before the shot that counts.
    // The shell can mount the tab bar again after its first render: an element shot retries on a detached node.
    const once = () =>
      frame.element
        ? page
            .locator(frame.element)
            .first()
            .screenshot({ animations: "disabled", caret: "hide" })
        : page.screenshot({ animations: "disabled", caret: "hide" });
    const shoot = async () => {
      for (let attempt = 1; ; attempt++) {
        try {
          return await once();
        } catch (error) {
          if (attempt >= 5) throw error;
          await page.waitForTimeout(300);
        }
      }
    };
    // Past Home's 8 s mark, when a read still missing or failed brings its corner card: the shot is the
    // page's settled state, not a race with that timer.
    await page.waitForTimeout(SETTLE_MS);
    let last = await shoot();
    for (let tries = 0; tries < 6; tries++) {
      await page.waitForTimeout(400);
      const next = await shoot();
      if (next.equals(last)) return next;
      last = next;
    }
    return last;
  } finally {
    await context.close();
  }
}

async function main() {
  const output = resolve(process.argv[2] ?? "wb-guard");
  const baselines = resolve(
    argument("--baselines") ?? "scripts/ci/guard-baselines",
  );
  const only = argument("--only");
  const update = process.argv.includes("--update");
  await mkdir(output, { recursive: true });
  const frames = guardFrames().filter(
    (frame) => !only || frame.name.startsWith(only),
  );
  const have = await pngsIn(baselines);
  const record = update || have.length === 0;
  const target = update ? baselines : resolve(output, "baselines");
  if (record) await mkdir(target, { recursive: true });

  const origin = fixtureOrigin;
  const { stop } = await fixtureServer();
  const rows = [];
  let browser;
  try {
    browser = await chromium.launch({ args: CHROMIUM_ARGS });
    // Compile each route once, so no frame is the compile.
    const warm = await browser.newPage();
    for (const route of new Set(frames.map((frame) => frame.route)))
      await warm
        .goto(origin + route, { waitUntil: "load", timeout: 180000 })
        .catch(() => undefined);
    await warm.waitForTimeout(2000);
    await warm.close();
    const judge = await browser.newPage();
    for (const frame of frames) {
      const row = {
        frame: frame.name,
        route: frame.route,
        size: `${frame.size.width}x${frame.size.height}`,
      };
      try {
        const notes = [];
        const shot = await render(browser, origin, frame, notes);
        if (notes.length) row.notes = [...new Set(notes)].slice(0, 8);
        if (record) {
          await writeFile(resolve(target, `${frame.name}.png`), shot);
          row.result = "recorded";
        } else {
          let baseline = null;
          try {
            baseline = await readFile(resolve(baselines, `${frame.name}.png`));
          } catch {
            /* missing below */
          }
          if (!baseline) {
            row.result = "no baseline";
            await writeFile(resolve(output, `${frame.name}.current.png`), shot);
          } else {
            // A render that differs is drawn again from scratch, up to RETRIES more times, and passes only on an
            // exact match: a real change differs every time; a rounded edge that landed a fraction of a pixel
            // off once (21 Nov 2026: the Leads top bar's pills, 28 rim pixels, one run in two) does not.
            let current = shot;
            let found = null;
            for (let attempt = 0; ; attempt++) {
              const next = await judge.evaluate(comparePngs, [
                dataUrl(baseline),
                dataUrl(current),
                TOLERANCE,
              ]);
              if (
                !found ||
                (next.changed ?? Infinity) < (found.changed ?? Infinity)
              )
                found = { ...next, shot: current };
              if (
                (!next.sizeMismatch && next.changed <= ALLOWED) ||
                attempt >= RETRIES
              )
                break;
              current = await render(browser, origin, frame);
              row.retries = attempt + 1;
            }
            row.changed = found.changed;
            row.sizes = { baseline: found.baseline, current: found.current };
            row.box = found.box ?? null;
            if (found.sizeMismatch) row.result = "size changed";
            else if (found.changed > ALLOWED) row.result = "changed";
            else row.result = "same";
            if (row.result !== "same") {
              await writeFile(
                resolve(output, `${frame.name}.current.png`),
                found.shot,
              );
              if (found.diff)
                await writeFile(
                  resolve(output, `${frame.name}.diff.png`),
                  Buffer.from(found.diff.split(",")[1], "base64"),
                );
            }
          }
        }
      } catch (error) {
        row.result = "error";
        row.error = String(error?.message ?? error)
          .split("\n")[0]
          .slice(0, 160);
      }
      rows.push(row);
      process.stdout.write(
        `${row.frame}: ${row.result}${row.changed ? ` (${row.changed} px)` : ""}${row.retries ? ` after ${row.retries} more render(s)` : ""}${row.error ? ` ${row.error}` : ""}\n${(row.notes ?? []).map((note) => `  ${note}\n`).join("")}`,
      );
    }
  } finally {
    await browser?.close();
    stop();
  }
  const bad = rows.filter((row) => !["same", "recorded"].includes(row.result));
  const lines = [
    "## Screen guard: Home, Leads and the phone tab bar",
    "",
    record
      ? `Recorded ${rows.filter((row) => row.result === "recorded").length} of ${frames.length} baselines in ${update ? "scripts/ci/guard-baselines" : "the artifact (baselines/)"}: nothing was compared.`
      : bad.length
        ? `**${bad.length} of ${frames.length} frames changed.** These screens must not change by a pixel (owner, 21 Nov 2026). The artifact has each one's render and diff (changed pixels in red). A deliberate change is re-recorded: \`node scripts/ci/wb_guard_screens.mjs <dir> --update\` on a runner, then commit the PNGs.`
        : `All ${frames.length} frames match their baselines pixel for pixel (any channel off by more than ${TOLERANCE} counts).`,
    "",
    "| frame | size | result | changed px | page notes |",
    "|---|---|---|---|---|",
    ...rows.map(
      (row) =>
        `| ${row.frame} | ${row.size} | ${row.result}${row.retries ? ` (${row.retries} more renders)` : ""}${row.error ? `: ${row.error}` : ""} | ${row.changed ?? "-"} | ${(row.notes ?? []).join("; ").replaceAll("|", "/") || "-"} |`,
    ),
    "",
  ].join("\n");
  await writeFile(resolve(output, "report.md"), lines);
  await writeFile(
    resolve(output, "guard.json"),
    JSON.stringify(
      {
        schema: "wb-guard/1",
        cpu: cpus()[0]?.model ?? null,
        tolerance: TOLERANCE,
        allowed: ALLOWED,
        record,
        rows,
      },
      null,
      1,
    ),
  );
  if (process.env.GITHUB_STEP_SUMMARY)
    await appendFile(process.env.GITHUB_STEP_SUMMARY, lines);
  console.log(lines);
  process.exit(bad.length ? 1 : 0);
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) await main();
