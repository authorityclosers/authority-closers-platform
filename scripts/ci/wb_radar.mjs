// The bug radar on a GitHub-hosted runner (`wb-ci --radar [screen|route ...]`; the orchestrator for the owner,
// 26 Oct 2026: spot the UI bugs the owner finds by hand, 100-200x faster, on every build). Every review fixture
// (fictional data, no API origin, no credentials) at 320, 360, 390 and 1280 px, 100% and 130% text and light and dark
// is checked in the page (wb_radar_lib.mjs: overflow, overlap, cut labels, small taps, faint text, centred cards,
// console errors and failed requests), then every safe control is tapped once at 390 px (dead taps, tabs that don't
// switch, errors after a tap, sheets off-screen). Findings get stable keys, a severity and a cropped screenshot.
//
//   node scripts/ci/wb_radar.mjs run <part-dir> [.wb-ci/request.json] [--shard i/n]   one shard's pages
//   node scripts/ci/wb_radar.mjs merge <dir> [.wb-ci/request.json]                   parts -> report.md, radar.json
//
// A part is part-<i>.json plus crops/<id>.jpg and pages/<screen>.jpg. Merge reads every part in <dir> (the parts
// downloaded into one folder), dedupes keys across states and groups them by root cause.
import { mkdir, readdir, readFile, writeFile } from "node:fs/promises";
import { join, relative, resolve } from "node:path";
import { SCREENS, textZoom } from "./wb_matrix_lib.mjs";
import {
  ANDROID_PROFILE,
  CRAWL,
  CRAWL_SIZE,
  RADAR_SIZES,
  chooseTaps,
  cropBox,
  dedupe,
  findingKey,
  groupFindings,
  helperScript,
  normalizeMessage,
  pickRadarScreens,
  radarArm,
  radarChanged,
  radarCovered,
  radarFocusHit,
  screenLoads,
  radarMark,
  radarObserve,
  radarScan,
  radarScrollRestore,
  radarScrollSave,
  radarTargets,
  radarUnfocus,
  reportMarkdown,
  sameTarget,
  shardOf,
  shortId,
  stateTag,
} from "./wb_radar_lib.mjs";

// Debugging against a fixture server already running (a laptop's `next dev` with AC_SALES_XRAY_REVIEW=1):
// WB_RADAR_ORIGIN=http://127.0.0.1:3000 WB_RADAR_WORKERS=1 node scripts/ci/wb_radar.mjs run out req.json
const WORKERS = Number(process.env.WB_RADAR_WORKERS) || 3;
// The browser side (Playwright and the matrix's fixture server) loads only for `run`; `merge` needs plain Node.
let matrix;
let origin;
const CROPS = 600; // per shard
const FIXTURES = "apps/sales-xray-web/app/review-fixture";
// Dev-server noise, not the app: hot reload, source maps, the dev overlay.
const DEV_NOISE =
  /\/_next\/webpack-hmr|__nextjs|\.hot-update\.|\/favicon\.ico|\[HMR\]|\[Fast Refresh\]|Download the React DevTools/;

/** Every fixture page the app has: app/review-fixture/<path>/page.tsx (no dynamic segments). */
async function fixturePaths(root = FIXTURES) {
  const found = [];
  const walk = async (dir) => {
    for (const entry of await readdir(dir, { withFileTypes: true })) {
      if (entry.isDirectory() && !/^[_[(]/.test(entry.name))
        await walk(join(dir, entry.name));
      else if (entry.name === "page.tsx")
        found.push(
          `/review-fixture/${relative(root, dir).replaceAll("\\", "/")}`.replace(
            /\/$/,
            "",
          ),
        );
    }
  };
  await walk(root);
  return found;
}

async function readRequest(path) {
  try {
    return JSON.parse(await readFile(path, "utf8"));
  } catch {
    return {};
  }
}

/** A fresh, isolated page for one state: the app's theme choice, the helpers, same-origin reads only. */
async function openPage(
  browser,
  screen,
  { size, theme, zoom, android },
  sandboxed,
) {
  const { local, step } = matrix;
  const context = await browser.newContext({
    // The Android app profile: the app's user agent, so the page draws its in-app version.
    ...(android ? { userAgent: android.userAgent } : {}),
    viewport: {
      width: Math.round(size.width / zoom),
      height: Math.round(size.height / zoom),
    },
    deviceScaleFactor: zoom,
    colorScheme: theme,
    isMobile: !size.desktop,
    hasTouch: !size.desktop,
    locale: "en-GB",
    reducedMotion: "reduce",
    serviceWorkers: "block",
    acceptDownloads: false,
    // A real phone lets a tapped Copy write the clipboard; headless Chromium refuses unless granted.
    permissions: ["clipboard-read", "clipboard-write"],
  });
  await context.addInitScript((value) => {
    try {
      window.localStorage.setItem("sales-xray:theme", value);
    } catch {
      /* storage blocked: the page stays on its default */
    }
  }, theme);
  await context.addInitScript({ content: helperScript() });
  // The app hands the phone's font scale to the page before any script, as the real app does (in-app.ts).
  if (android)
    await context.addInitScript((scale) => {
      window.SXFontScale = scale;
    }, android.fontScale);
  await context.route("**/*", (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.origin !== origin || request.method() !== "GET") {
      sandboxed.add(request.url());
      return route.abort();
    }
    // The matrix's guard answers the fixtures' one review flag (it checks its own origin, so not for an override).
    return origin === matrix.origin ? local(route) : route.continue();
  });
  const page = await context.newPage();
  // A budget phone's CPU: 4x slower than the runner, from the first script on.
  if (android?.cpu)
    await (
      await context.newCDPSession(page)
    ).send("Emulation.setCPUThrottlingRate", { rate: android.cpu });
  const events = [];
  page.on("console", (message) => {
    if (message.type() !== "error") return;
    const text = message.text();
    const at = message.location()?.url ?? "";
    if (DEV_NOISE.test(text) || DEV_NOISE.test(at) || sandboxed.has(at)) return;
    // Chrome's own line for a failed load: the response and requestfailed handlers record it with its path.
    if (/^Failed to load resource/.test(text)) return;
    events.push({
      check: "console-error",
      message: normalizeMessage(text),
      severity: /hydrat/i.test(text) ? "high" : "medium",
    });
  });
  page.on("pageerror", (error) =>
    events.push({
      check: "page-error",
      message: normalizeMessage(error.message),
      severity: "high",
    }),
  );
  page.on("requestfailed", (request) => {
    if (sandboxed.has(request.url()) || DEV_NOISE.test(request.url())) return;
    // The app cancelled it (an AbortController on unmount or a newer search): not a failure.
    if (request.failure()?.errorText === "net::ERR_ABORTED") return;
    const path = new URL(request.url()).pathname;
    events.push({
      check: "request-failed",
      message: normalizeMessage(
        `${request.method()} ${path} ${request.failure()?.errorText ?? ""}`,
      ),
      severity: path.startsWith("/v1/") ? "low" : "medium",
    });
  });
  page.on("response", (response) => {
    const url = response.url();
    if (
      response.status() < 400 ||
      !url.startsWith(origin) ||
      DEV_NOISE.test(url)
    )
      return;
    const path = new URL(url).pathname;
    events.push({
      check: "request-failed",
      message: normalizeMessage(
        `${response.request().method()} ${path} ${response.status()}`,
      ),
      severity: path.startsWith("/v1/") ? "low" : "medium",
    });
  });
  try {
    await page.goto(origin + screen.path, {
      waitUntil: "networkidle",
      timeout: 90000,
    });
    await page.waitForTimeout(300);
    for (const item of screen.steps ?? []) await step(page, item);
  } catch (error) {
    await context.close().catch(() => undefined);
    throw error;
  }
  return { context, page, events };
}

/**
 * A page, tried twice: the first tap on a fixture can wait for next dev to compile a lazy chunk (the leads table
 * took over 20 s on the first baseline), and the second try finds it built.
 */
async function openPageTwice(...args) {
  try {
    return await openPage(...args);
  } catch {
    return await openPage(...args);
  }
}

/** A cropped, outlined screenshot of a finding's element(s), once per finding key a shard. */
async function crop(page, viewport, hit, file) {
  await page.evaluate(radarScrollSave);
  try {
    const box = hit ? await page.evaluate(radarFocusHit, hit) : null;
    await page.waitForTimeout(60);
    await page.screenshot({
      path: file,
      type: "jpeg",
      quality: 60,
      scale: "css",
      clip: cropBox(box, viewport),
    });
    return true;
  } catch {
    return false;
  } finally {
    await page.evaluate(radarUnfocus).catch(() => undefined);
    await page.evaluate(radarScrollRestore).catch(() => undefined);
  }
}

function shardArg(args) {
  const at = args.indexOf("--shard");
  if (at < 0) return [0, 1];
  const [index, count] = args[at + 1].split("/").map(Number);
  if (!(count >= 1 && index >= 0 && index < count))
    throw new Error(`bad --shard ${args[at + 1]}`);
  return [index, count];
}

async function run(args) {
  const { chromium } = await import("playwright");
  matrix = await import("./wb_matrix.mjs");
  const [output, requestPath = ".wb-ci/request.json"] = args.filter(
    (a, i) => !a.startsWith("--") && args[i - 1] !== "--shard",
  );
  const [index, count] = shardArg(args);
  const request = await readRequest(requestPath);
  const screens = shardOf(
    pickRadarScreens(request.routes ?? [], SCREENS, await fixturePaths()),
    index,
    count,
  );
  await mkdir(resolve(output, "crops"), { recursive: true });
  await mkdir(resolve(output, "pages"), { recursive: true });
  const started = Date.now();
  const sandboxed = new Set();
  const raw = [];
  const pages = new Map(
    screens.map(([key, screen]) => [
      key,
      {
        key,
        path: screen.path,
        loads: 0,
        failed: [],
        crawled: false,
        taps: 0,
        skipped: {},
      },
    ]),
  );
  const cropped = new Set();
  let crops = 0;
  const keep = async (page, viewport, finding) => {
    const key = findingKey(finding);
    if (cropped.has(key) || crops >= CROPS || finding.hit === undefined)
      return finding;
    cropped.add(key);
    const name = `crops/${shortId(key)}.jpg`;
    if (await crop(page, viewport, finding.hit, resolve(output, name))) {
      crops++;
      return { ...finding, crop: name };
    }
    return finding;
  };

  /** One load: measure 100% (and 130% text after), keep crops, record console and network events. */
  const sweep = async (browser, key, screen, load) => {
    const info = pages.get(key);
    let session;
    try {
      session = await openPageTwice(browser, screen, load, sandboxed);
      const { page } = session;
      const viewport = page.viewportSize();
      for (const state of load.states) {
        if (state.mode === "text" && state.scale !== 1) {
          await page.evaluate(textZoom, state.scale);
          await page.waitForTimeout(150);
        }
        const { findings } = await page.evaluate(radarScan, {
          phone: !load.size.desktop,
        });
        for (const f of findings) {
          const finding = {
            ...f,
            page: key,
            path: screen.path,
            state: stateTag(state),
          };
          raw.push(await keep(page, viewport, finding));
        }
      }
      // One whole page a screen (390, 100%, light) for the optional AI review and for people.
      if (
        load.size === CRAWL_SIZE &&
        load.theme === "light" &&
        load.zoom === 1
      ) {
        await page.evaluate(textZoom, 1 / 1.3);
        await page.evaluate(matrix.unclip);
        await page.waitForTimeout(150);
        await page
          .screenshot({
            path: resolve(output, `pages/${key}.jpg`),
            type: "jpeg",
            quality: 60,
            fullPage: true,
            scale: "css",
          })
          .catch(() => undefined);
      }
      for (const event of session.events)
        raw.push({
          ...event,
          page: key,
          path: screen.path,
          selector: event.message,
          label: "",
          detail: event.message,
          state: stateTag(load.states[0]),
        });
      info.loads++;
    } catch (error) {
      info.failed.push(
        `${stateTag(load.states[0])}: ${String(error?.message ?? error)
          .split("\n")[0]
          .slice(0, 200)}`,
      );
    } finally {
      await session?.context.close().catch(() => undefined);
    }
  };

  /** Tap every safe control once; reload after any tap that changed something. */
  const crawl = async (browser, key, screen, size, android = null) => {
    const info = pages.get(key);
    const load = {
      size,
      theme: "light",
      zoom: 1,
      ...(android ? { android } : {}),
      states: [
        {
          ...size,
          theme: "light",
          scale: android ? android.fontScale : 1,
          mode: android ? "android" : "app",
        },
      ],
    };
    const where = `${stateTag(load.states[0])} (taps)`;
    let session = null;
    let targets = [];
    const fresh = async () => {
      await session?.context.close().catch(() => undefined);
      session = await openPageTwice(browser, screen, load, sandboxed);
      session.flags = {
        popup: false,
        chooser: false,
        alert: false,
        download: false,
      };
      session.context.on("page", (other) => {
        session.flags.popup = true;
        other.close().catch(() => undefined);
      });
      session.page.on("filechooser", () => (session.flags.chooser = true));
      session.page.on("download", () => (session.flags.download = true));
      session.page.on("dialog", (dialog) => {
        session.flags.alert = true;
        dialog.dismiss().catch(() => undefined);
      });
      targets = await session.page.evaluate(radarTargets, { selector: CRAWL });
    };
    try {
      await fresh();
      const { chosen, skipped } = chooseTaps(targets);
      // Two crawls a page (the phone and the Android app): their counts add up.
      for (const [why, count] of Object.entries(skipped))
        info.skipped[why] = (info.skipped[why] ?? 0) + count;
      let dirty = false;
      for (const wanted of chosen) {
        if (dirty) {
          await fresh();
          dirty = false;
        }
        const target = targets.find((t) => sameTarget(t, wanted));
        if (!target) continue;
        const { page } = session;
        const viewport = page.viewportSize();
        const base = {
          page: key,
          path: screen.path,
          state: where,
          label: target.label,
          context: `tap "${target.label}"`,
        };
        // A finding about the tapped control, with a crop of it.
        const shot = async (finding) => {
          await page
            .evaluate((id) => {
              for (const el of document.querySelectorAll(
                '[data-radar-hit~="tap"]',
              ))
                el.removeAttribute("data-radar-hit");
              document
                .querySelector(`[data-radar-id="${id}"]`)
                ?.setAttribute("data-radar-hit", "tap");
            }, target.id)
            .catch(() => undefined);
          raw.push(await keep(page, viewport, { ...finding, hit: "tap" }));
        };
        // A sheet that opened by itself since the list was made covers this control: not a person's tap.
        if (await page.evaluate(radarCovered, target.id).catch(() => false)) {
          info.skipped.covered = (info.skipped.covered ?? 0) + 1;
          continue;
        }
        await page.evaluate(radarArm);
        await page.waitForTimeout(300);
        await page.evaluate(radarMark, target.id);
        session.events.length = 0;
        try {
          await page
            .locator(`[data-radar-id="${target.id}"]`)
            .click({ timeout: 2000 });
        } catch (error) {
          const line = String(error?.message ?? error)
            .split("\n")
            .find((text) => text.includes("intercepts pointer events"));
          if (line) {
            const tag = /<([a-z0-9-]+)/.exec(line)?.[1] ?? "element";
            const cls = /class="([^"]*)"/
              .exec(line)?.[1]
              ?.split(" ")[0]
              ?.replace(/-module__[A-Za-z0-9_-]{5,8}__/, "__");
            await shot({
              ...base,
              check: "tap-blocked",
              severity: "high",
              selector: target.selector,
              detail: `a ${tag}${cls ? ` (${cls})` : ""} is drawn over it, so a tap lands there instead`,
            });
          } else info.skipped.untappable = (info.skipped.untappable ?? 0) + 1;
          continue;
        }
        info.taps++;
        let changed = false;
        let navigated = false;
        const t0 = Date.now();
        while (Date.now() - t0 < 1000) {
          await page.waitForTimeout(100);
          try {
            changed = await page.evaluate(radarChanged);
          } catch {
            changed = navigated = true;
          }
          if (changed) break;
        }
        if (changed) await page.waitForTimeout(450);
        let seen = { navigated: true };
        try {
          seen = await page.evaluate(radarObserve, target.id);
        } catch {
          navigated = true;
        }
        navigated ||= !!seen.navigated;
        const flags = session.flags;
        const anything =
          changed ||
          navigated ||
          seen.scrolled ||
          seen.focused ||
          seen.checked ||
          flags.popup ||
          flags.chooser ||
          flags.alert ||
          flags.download;
        const left =
          navigated || (seen.url && !seen.url.startsWith("/review-fixture"));
        // A real tab ("tab") that does nothing is the owner's "Leads setup tabs don't switch"; a segmented switch
        // ("segment") may be a mode with no content of its own (a playback speed), so it ranks lower.
        const tab = target.tabLike === "tab";
        if (!anything && !target.selected)
          await shot({
            ...base,
            check: target.tabLike ? "tab-no-switch" : "dead-tap",
            severity: tab ? "high" : "medium",
            selector: target.selector,
            detail: target.tabLike
              ? "tapped a tab: it did not light up and nothing else changed"
              : "tapped: nothing changed in the page, the address, scroll or focus within 1 s",
          });
        else if (
          target.tabLike &&
          !target.selected &&
          !left &&
          !seen.contentChanged &&
          !seen.url &&
          !seen.scrolled // a strip that jumps to its section
        )
          await shot({
            ...base,
            check: "tab-no-switch",
            severity: tab && seen.selectedNow ? "high" : tab ? "medium" : "low",
            selector: target.selector,
            detail: seen.selectedNow
              ? "the tab lights up, but the content below stays the same"
              : "tapped a tab: the content below stays the same",
          });
        if (!left) {
          for (const event of session.events)
            raw.push({
              ...base,
              check: "tap-error",
              severity:
                event.severity === "high"
                  ? "high"
                  : event.check === "request-failed"
                    ? event.severity
                    : "medium",
              // One finding per control and message (several errors after one tap stay apart).
              selector: `${target.selector} ⇒ ${event.message}`,
              message: event.message,
              detail: event.message,
            });
          for (const sheet of seen.sheets ?? []) {
            if (sheet.off.length)
              raw.push(
                await keep(page, viewport, {
                  ...base,
                  check: "sheet-offscreen",
                  severity: "high",
                  selector: sheet.selector,
                  detail: `the sheet opened by "${target.label}" is ${sheet.off.join(", ")}`,
                  hit: null,
                }),
              );
            // The sheet's own layout, with the static checks.
            const { findings } = await page
              .evaluate(radarScan, {
                phone: !size.desktop,
                scope: `[data-radar-scope="${sheet.scope}"]`,
              })
              .catch(() => ({ findings: [] }));
            for (const f of findings)
              raw.push(
                await keep(page, viewport, {
                  ...f,
                  page: key,
                  path: screen.path,
                  state: where,
                  context: `sheet from "${target.label}"`,
                }),
              );
          }
        }
        dirty ||= anything;
      }
      info.crawled = true;
    } catch (error) {
      info.failed.push(
        `${where}: ${String(error?.message ?? error)
          .split("\n")[0]
          .slice(0, 200)}`,
      );
    } finally {
      await session?.context.close().catch(() => undefined);
    }
  };

  origin = process.env.WB_RADAR_ORIGIN || matrix.origin;
  const server = process.env.WB_RADAR_ORIGIN
    ? { stop: () => undefined }
    : await matrix.fixtureServer();
  const deadline = setTimeout(
    () => {
      server.stop();
      process.exit(1);
    },
    40 * 60 * 1000,
  );
  let browser;
  try {
    browser = await chromium.launch();
    // Compile each route once, so the first measured state isn't the compile.
    const warm = await browser.newPage();
    for (const [, screen] of screens)
      await warm
        .goto(origin + screen.path, {
          waitUntil: "networkidle",
          timeout: 180000,
        })
        .catch(() => undefined);
    await warm.close();
    // Crawls first: they take longest, so they don't straggle at the end.
    const jobs = [
      ...screens.flatMap(([key, screen]) => [
        { kind: "crawl", key, screen, size: CRAWL_SIZE },
        // The same taps as the Android app on a slow phone: a tap during hydration is lost there.
        ...(screen.android === false
          ? []
          : [
              {
                kind: "crawl",
                key,
                screen,
                size: ANDROID_PROFILE.size,
                android: ANDROID_PROFILE,
              },
            ]),
        ...(screen.desktop
          ? [
              {
                kind: "crawl",
                key,
                screen,
                size: RADAR_SIZES.find((size) => size.desktop),
              },
            ]
          : []),
      ]),
      ...screens.flatMap(([key, screen]) =>
        screenLoads(screen).map((load) => ({
          kind: "sweep",
          key,
          screen,
          load,
        })),
      ),
    ];
    let next = 0;
    const worker = async () => {
      while (next < jobs.length) {
        const job = jobs[next++];
        if (job.kind === "crawl")
          await crawl(browser, job.key, job.screen, job.size, job.android);
        else await sweep(browser, job.key, job.screen, job.load);
      }
    };
    await Promise.all(Array.from({ length: WORKERS }, worker));
  } finally {
    clearTimeout(deadline);
    await browser?.close();
    server.stop();
  }
  const part = {
    schema: "wb-radar-part/1",
    shard: `${index}/${count}`,
    source_sha: request.source_sha ?? null,
    elapsed_seconds: Math.round((Date.now() - started) / 1000),
    pages: [...pages.values()],
    findings: raw.map(({ hit, ...rest }) => rest),
  };
  await writeFile(resolve(output, `part-${index}.json`), JSON.stringify(part));
  const failed = part.pages.filter((p) => p.failed.length).length;
  console.log(
    `radar shard ${index}/${count}: ${part.pages.length} pages, ${raw.length} raw findings, ${crops} crops, ` +
      `${failed} pages with failures, ${part.elapsed_seconds}s`,
  );
  // A shard fails only when it could not run: over a quarter of its pages never loaded at all.
  process.exit(
    part.pages.filter((p) => !p.loads).length > part.pages.length / 4 ? 1 : 0,
  );
}

async function merge(args) {
  const [dir, requestPath = ".wb-ci/request.json"] = args;
  const request = await readRequest(requestPath);
  const parts = [];
  for (const name of await readdir(dir))
    if (/^part-\d+\.json$/.test(name))
      parts.push(JSON.parse(await readFile(join(dir, name), "utf8")));
  if (!parts.length) throw new Error(`no radar parts in ${dir}`);
  const findings = dedupe(parts.flatMap((p) => p.findings));
  const groups = groupFindings(findings);
  const pages = parts
    .flatMap((p) => p.pages)
    .sort((a, b) => a.key.localeCompare(b.key));
  const run = {
    schema: "wb-radar/1",
    source_sha: request.source_sha ?? parts[0].source_sha ?? null,
    shards: parts.map((p) => ({
      shard: p.shard,
      elapsed_seconds: p.elapsed_seconds,
    })),
    pages,
    findings,
    groups: groups.map(({ findings: mine, ...g }) => ({
      ...g,
      findings: mine.map((f) => f.key),
    })),
  };
  const text = reportMarkdown({ ...run, groups });
  await writeFile(join(dir, "report.md"), text);
  await writeFile(join(dir, "radar.json"), JSON.stringify(run, null, 1));
  if (process.env.GITHUB_STEP_SUMMARY)
    await writeFile(process.env.GITHUB_STEP_SUMMARY, text.slice(0, 900000), {
      flag: "a",
    });
  console.log(text.split("#### Every group")[0]);
}

const [command, ...rest] = process.argv.slice(2);
if (command === "run") await run(rest);
else if (command === "merge") await merge(rest);
else {
  console.error(
    "usage: wb_radar.mjs run <part-dir> [request.json] [--shard i/n] | merge <dir> [request.json]",
  );
  process.exit(2);
}
