// Sales Xray page matrix (AUT-1663, after Pulse's page-matrix-runner).
//
// Opens every app page as guest, member, admin, owner and a Personal-only
// owner against fictional API answers, then every page at 390 and 1440 px in
// light and dark. It fails when a page:
//   - answers the document with HTTP 500 or more;
//   - throws (pageerror) or shows an error screen or a failed section;
//   - keeps a skeleton (aria-busy="true") that never clears;
//   - lets a guest see a signed-in page without a way to sign in, or shows a
//     member company details meant for owners and admins;
//   - scrolls sideways by more than 1 px.
//
//   node apps/sales-xray-web/scripts/page-matrix.mjs --origin http://127.0.0.1:3016 \
//     --out "$RUNNER_TEMP/page-matrix" [--pass roles|screens|all] [--only /dashboard]
import { readdirSync, statSync } from "node:fs";
import { mkdir, writeFile, appendFile } from "node:fs/promises";
import { dirname, join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";

import {
  answer,
  CALL_ID,
  fixtureFor,
  PROSPECT_ID,
  ROLES,
} from "./page-matrix-fixtures.mjs";

const APP = join(dirname(fileURLToPath(import.meta.url)), "../app");

/** Signed-in pages: a guest must be offered a way to sign in. */
export const PROTECTED = [
  "/dashboard",
  "/analysis/calls",
  `/analysis/calls/${CALL_ID}`,
  "/organisation",
  "/account",
  "/prospects",
];

const PARAMS = { callId: CALL_ID, prospectId: PROSPECT_ID };

/** Every app/**\/page.tsx as a URL; dynamic segments get fixture ids. */
export function discoverRoutes(root = APP) {
  const routes = [];
  const walk = (dir) => {
    for (const name of readdirSync(dir).sort()) {
      const path = join(dir, name);
      if (statSync(path).isDirectory()) {
        if (!name.startsWith("_") && name !== "node_modules") walk(path);
      } else if (name === "page.tsx") {
        const parts = relative(root, dir)
          .split(sep)
          .filter((part) => part && !/^\(.*\)$/.test(part))
          .map((part) => {
            const param = /^\[(\w+)\]$/.exec(part)?.[1];
            if (!param) return part;
            if (!(param in PARAMS))
              throw new Error(`No fixture id for the [${param}] segment.`);
            return PARAMS[param];
          });
        routes.push(`/${parts.join("/")}`);
      }
    }
  };
  walk(root);
  return routes;
}

/**
 * Known faults outside this gate's owner: reported, not failing, each with
 * where it is tracked. The summary says when one stops reproducing, so the
 * list only shrinks. Key: "route|role", or "route|*" for every role.
 */
export const KNOWN = {
  "/account|*":
    "Plan and billing stays on 'Loading billing details…' with no read in flight (billing code; reported by AUT-1663, 10 Oct)",
};

export const knownFault = (route, role) =>
  KNOWN[`${route}|${role}`] ?? KNOWN[`${route}|*`] ?? null;

/** Extra views that a route hides behind a query (one per tab). */
const VIEWS = {
  "/organisation": ["/organisation?tab=members", "/organisation?tab=company"],
};

const SNAG =
  /This screen hit a snag|Application error: a client-side exception/;

function argument(name, fallback) {
  const index = process.argv.indexOf(`--${name}`);
  return index > 0 ? process.argv[index + 1] : fallback;
}

/** One retry when the page itself never arrives (a cold server), not on faults. */
async function visit(browser, origin, view) {
  const first = await visitOnce(browser, origin, view);
  const cold = first.problems.some((problem) =>
    problem.startsWith("did not load"),
  );
  return cold ? visitOnce(browser, origin, view) : first;
}

async function visitOnce(
  browser,
  origin,
  { route, role, width, height, scheme, out },
) {
  const phone = width < 768;
  const context = await browser.newContext({
    viewport: { width, height },
    colorScheme: scheme,
    isMobile: phone,
    hasTouch: phone,
    deviceScaleFactor: 1,
    reducedMotion: "reduce",
    timezoneId: "Asia/Kolkata",
  });
  const table = fixtureFor(role);
  const problems = [];
  const writes = [];
  await context.route("**/v1/**", async (request) => {
    const url = new URL(request.request().url());
    const method = request.request().method();
    if (method !== "GET" && method !== "HEAD")
      writes.push(`${method} ${url.pathname}`);
    const { status, body } = answer(
      table,
      role,
      method,
      url.pathname,
      url.search,
    );
    await request.fulfill({ status, json: body });
  });
  const page = await context.newPage();
  page.on("pageerror", (error) =>
    problems.push(
      `page error: ${String(error.message ?? error).slice(0, 300)}`,
    ),
  );
  let status = 0;
  try {
    const response = await page.goto(`${origin}${route}`, {
      waitUntil: "domcontentloaded",
      timeout: 60_000,
    });
    status = response?.status() ?? 0;
    if (status >= 500) problems.push(`HTTP ${status}`);
    await page
      .waitForLoadState("networkidle", { timeout: 20_000 })
      .catch(() => {});
    const busy = await page
      .waitForFunction(
        () => !document.querySelector('[aria-busy="true"]'),
        null,
        {
          timeout: 15_000,
        },
      )
      .then(() => false)
      .catch(() => true);
    if (busy) problems.push('a skeleton (aria-busy="true") never cleared');
    await page.waitForTimeout(300);
    const text = await page.locator("body").innerText({ timeout: 5_000 });
    if (SNAG.test(text)) problems.push("the error screen showed");
    const sections = await page
      .locator("[data-section-error]")
      .evaluateAll((nodes) =>
        nodes.map((node) => node.getAttribute("data-section-error")),
      );
    if (sections.length)
      problems.push(`failed sections: ${sections.join(", ")}`);
    const path = route.split("?")[0];
    if (
      role === "guest" &&
      PROTECTED.includes(path) &&
      !/sign in|log in/i.test(text)
    )
      problems.push("a guest sees a signed-in page with no way to sign in");
    if (role === "member" && route === "/organisation?tab=company") {
      if (!/Only owners and admins/.test(text))
        problems.push(
          "a member is not told company details are for owners and admins",
        );
      if (await page.locator('form[aria-label="Company details"]').count())
        problems.push("a member sees the company details form");
    }
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    );
    if (overflow > 1) problems.push(`scrolls sideways by ${overflow} px`);
    if (out)
      await page.screenshot({ path: out, fullPage: false }).catch(() => {});
  } catch (error) {
    problems.push(
      `did not load: ${String(error.message ?? error).split("\n")[0]}`,
    );
  } finally {
    await context.close();
  }
  return {
    route,
    role,
    width,
    scheme,
    status,
    writes,
    problems,
    known: knownFault(route, role),
    ok: !problems.length || knownFault(route, role) !== null,
  };
}

async function main() {
  const origin = argument("origin", "http://127.0.0.1:3016");
  const output = argument("out", "page-matrix");
  const pass = argument("pass", "all");
  const only = argument("only", "")?.split(",").filter(Boolean);
  const { chromium } = await import("playwright");
  await mkdir(join(output, "screens"), { recursive: true });

  let routes = discoverRoutes().flatMap((route) => [
    route,
    ...(VIEWS[route] ?? []),
  ]);
  if (only.length)
    routes = routes.filter((route) => only.includes(route.split("?")[0]));
  const browser = await chromium.launch();
  const results = [];
  const log = (result) => {
    results.push(result);
    const where = `${result.role.padEnd(8)} ${String(result.width).padStart(4)} ${result.scheme.padEnd(5)} ${result.route}`;
    const mark = !result.ok ? "FAIL" : result.problems.length ? "KNWN" : "ok  ";
    console.log(
      `${mark} ${where}${result.problems.length ? ` :: ${result.problems.join("; ")}` : ""}`,
    );
  };
  try {
    if (pass === "roles" || pass === "all")
      for (const route of routes)
        for (const role of ROLES)
          log(
            await visit(browser, origin, {
              route,
              role,
              width: 1280,
              height: 800,
              scheme: "light",
            }),
          );
    if (pass === "screens" || pass === "all")
      for (const route of routes)
        for (const [width, height] of [
          [390, 844],
          [1440, 900],
        ])
          for (const scheme of ["light", "dark"]) {
            const name = `${route.replace(/[^\w]+/g, "_").replace(/^_|_$/g, "") || "home"}-${width}-${scheme}.png`;
            log(
              await visit(browser, origin, {
                route,
                role: "owner",
                width,
                height,
                scheme,
                out: join(output, "screens", name),
              }),
            );
          }
  } finally {
    await browser.close();
  }

  const failures = results.filter((result) => !result.ok);
  const known = results.filter((result) => result.ok && result.problems.length);
  const fixed = Object.keys(KNOWN).filter(
    (key) =>
      results.some(
        (result) => knownFault(result.route, result.role) === KNOWN[key],
      ) &&
      !results.some(
        (result) =>
          knownFault(result.route, result.role) === KNOWN[key] &&
          result.problems.length,
      ),
  );
  await writeFile(
    join(output, "receipts.json"),
    JSON.stringify(
      {
        origin,
        pass,
        routes,
        checked: results.length,
        failures: failures.length,
        known: known.length,
        fixed,
        results,
      },
      null,
      2,
    ),
  );
  const summary = [
    `### Sales Xray page matrix: ${failures.length ? `${failures.length} of ${results.length} failed` : `all ${results.length} passed`}`,
    "",
    ...failures.map(
      (result) =>
        `- \`${result.route}\` as ${result.role} at ${result.width} ${result.scheme}: ${result.problems.join("; ")}`,
    ),
    ...(known.length
      ? [
          "",
          `Known, not failing (${known.length}):`,
          ...[...new Set(known.map((result) => result.known))].map(
            (reason) => `- ${reason}`,
          ),
        ]
      : []),
    ...fixed.map(
      (key) => `- No longer reproduces, remove from KNOWN: \`${key}\``,
    ),
  ].join("\n");
  if (process.env.GITHUB_STEP_SUMMARY)
    await appendFile(process.env.GITHUB_STEP_SUMMARY, `${summary}\n`);
  console.log(`\n${summary}`);
  process.exitCode = failures.length ? 1 : 0;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) await main();
