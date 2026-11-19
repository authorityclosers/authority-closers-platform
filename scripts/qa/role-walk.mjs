// The role walk on dev (QA system stage 1, step 6; owner, 18 Nov 2026: "Yes, start stage 1"). Nobody opened the
// app as each role, so a seller's own home page could be a page they are refused (research 18 Nov, cause 7). This
// opens every menu item the app shows a role, as that role, on a phone and on a laptop, and fails on:
// a refusal page, an error page, a blank page, junk on screen, an uncaught error, a 5xx from the API, or a home
// page the role cannot open. No model, no tokens. Dev only; it reads and writes nothing (non-GET requests other
// than the app's own session calls are refused before they leave).
//
// The four roles are fictional people signed in through the persona proxy on ac (/__as/<alias>):
//   owner    qaowner    owns "TEST · QA Owner Desk"
//   admin    anjali     Admin of the AC Sales Sandbox (the owner-view person)
//   manager  qamanager  Manager in TEST · Sahyadri Homes
//   seller   qa         Member in TEST · Sahyadri Homes (the QA account's dev twin)
//
//   node scripts/qa/role-walk.mjs <output-dir> [--base http://127.0.0.1:3098] [--roles owner,seller]
//        [--sizes phone,laptop] [--most 40]
//
// Output: role-walk.json, report.md (the table), and one small picture per failed page. Exit 1 when a page failed.
import { mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { isJunk } from "../ci/wb_readability_lib.mjs";

export const ROLES = {
  owner: { alias: "qaowner", workspace: "TEST · QA Owner Desk" },
  admin: { alias: "anjali" },
  manager: { alias: "qamanager", workspace: "TEST · Sahyadri Homes" },
  seller: { alias: "qa", workspace: "TEST · Sahyadri Homes" },
};
export const SIZES = {
  phone: { width: 360, height: 780, isMobile: true, hasTouch: true },
  laptop: { width: 1280, height: 800, isMobile: false, hasTouch: false },
};
export const HOME = "/dashboard";
// Where a role's menu lives beyond Home's own links.
export const HUBS = [HOME, "/settings", "/organisation"];
const CHROME =
  process.env.SX_CHROME ||
  "/home/acdev/.cache/ms-playwright/chromium_headless_shell-1208/chrome-headless-shell-linux64/chrome-headless-shell";

export const REFUSED =
  /you don.t have (access|permission)|not allowed to (see|open|view)|ask (your|an) (owner|admin)|only (the )?(owners?|admins?) can (see|open|view)|access denied|\b403\b/i;
export const TERMS = /accept our terms to continue|updated our terms/i;
export const BROKEN =
  /something went wrong|application error|this page could not be found|\b404\b.*not found|didn.t load\b/i;
const DEV_NOISE = /webpack-hmr|__nextjs|hot-update|\[HMR\]|\[Fast Refresh\]|React DevTools|hydrat/i;

/** A link the walk follows: inside the app, a page (not a file, sign-out, or another site). */
export function walkable(href) {
  if (typeof href !== "string" || !href.startsWith("/") || href.startsWith("//")) return null;
  const path = href.split("#")[0];
  if (!path || /^\/(__as|v1|_next|api)\b/.test(path)) return null;
  if (/sign-?out|log-?out|\/delete|\.(png|jpg|svg|pdf|csv|apk|ico|json|txt)$/i.test(path)) return null;
  return path;
}

/** The pages to open, in the order found: Home first, no repeats, a detail page only once per list. */
export function plan(hrefs, most = 40) {
  const out = [HOME];
  const kinds = new Set([HOME]);
  for (const href of hrefs) {
    const path = walkable(href);
    if (!path) continue;
    // One of each kind: /leads/<id> and /leads/<other id> are the same page to a role walk.
    const kind = path.replace(/[0-9a-f]{8}-[0-9a-f-]{27}/g, ":id").replace(/([?&](lead|id|call)=)[^&]+/g, "$1:id");
    if (kinds.has(kind)) continue;
    kinds.add(kind);
    out.push(path);
    if (out.length >= most) break;
  }
  return out;
}

/** What is wrong with a page, or null. `home` makes a refusal the worst kind. */
export function judge({ text, errors, serverErrors, status, home }) {
  const words = String(text ?? "").replace(/\s+/g, " ").trim();
  if (status >= 400) return `HTTP ${status}`;
  if (TERMS.test(words)) return "the terms box covers the page";
  if (REFUSED.test(words)) return home ? "the role's own home page is refused" : "a refusal page";
  if (BROKEN.test(words)) return "an error page";
  if (words.length < 20) return "a blank page";
  if (String(text ?? "").split("\n").some((line) => isJunk(line))) return "junk on screen";
  if (errors.length) return `uncaught error: ${errors[0]}`;
  if (serverErrors.length) return `API ${serverErrors[0]}`;
  return null;
}

export function reportMarkdown(rows) {
  const failed = rows.filter((row) => row.note);
  const lines = ["## Role walk on dev", ""];
  const cells = new Map();
  for (const row of rows) {
    const key = `${row.role} | ${row.size}`;
    const cell = cells.get(key) ?? { pages: 0, failed: 0 };
    cell.pages += 1;
    if (row.note) cell.failed += 1;
    cells.set(key, cell);
  }
  lines.push("| role | size | pages opened | failed |", "| --- | --- | --- | --- |");
  for (const [key, cell] of cells) lines.push(`| ${key.replace(" | ", " | ")} | ${cell.pages} | ${cell.failed} |`);
  lines.push("");
  if (!failed.length) lines.push("Every page each role is shown opened for that role.", "");
  else {
    lines.push("### Failed", "", "| role | size | page | what |", "| --- | --- | --- | --- |");
    for (const row of failed) lines.push(`| ${row.role} | ${row.size} | \`${row.path}\` | ${row.note} |`);
    lines.push("");
  }
  return lines.join("\n");
}

function argument(name) {
  const at = process.argv.indexOf(name);
  return at > 0 ? process.argv[at + 1] : undefined;
}

async function main() {
  const output = resolve(process.argv[2] ?? "role-walk");
  mkdirSync(output, { recursive: true });
  const base = argument("--base") ?? "http://127.0.0.1:3098";
  const roles = (argument("--roles") ?? Object.keys(ROLES).join(",")).split(",").filter((r) => ROLES[r]);
  const sizes = (argument("--sizes") ?? "phone,laptop").split(",").filter((s) => SIZES[s]);
  const most = Number(argument("--most") ?? 40);
  let chromium;
  try {
    ({ chromium } = await import("playwright-core"));
  } catch {
    ({ chromium } = await import("playwright"));
  }
  const browser = await chromium.launch({ executablePath: CHROME, args: ["--no-sandbox"] });
  const rows = [];
  try {
    for (const role of roles)
      for (const size of sizes) {
        const { width, height, isMobile, hasTouch } = SIZES[size];
        const context = await browser.newContext({ viewport: { width, height }, isMobile, hasTouch });
        // Reads only: the app's own session calls (its workspace choice) are the one exception.
        await context.route("**/*", (route) => {
          const request = route.request();
          const url = new URL(request.url());
          if (url.origin !== base) return route.abort();
          if (!["GET", "HEAD", "OPTIONS"].includes(request.method()) && url.pathname !== "/v1/context")
            return route.abort();
          return route.continue();
        });
        const page = await context.newPage();
        const errors = [];
        const serverErrors = [];
        page.on("pageerror", (error) => {
          const text = String(error.message).split("\n")[0].slice(0, 100);
          if (!DEV_NOISE.test(text)) errors.push(text);
        });
        page.on("response", (response) => {
          const url = new URL(response.url());
          if (response.status() >= 500 && url.pathname.startsWith("/v1/"))
            serverErrors.push(`${response.status()} on ${url.pathname.replace(/[0-9a-f-]{36}/g, ":id")}`);
        });
        const read = () => page.locator("body").innerText({ timeout: 5000 }).catch(() => "");
        const settle = async () => {
          // The dev server compiles a page the first time it is asked for: give it time, then read what stays.
          // Settled is the same amount of text two seconds running (a clock or a counter may still tick).
          let size = -1;
          for (let i = 0; i < 40; i++) {
            await page.waitForTimeout(1000);
            const now = (await read()).trim().length;
            if (now >= 20 && Math.abs(now - size) <= 3) break;
            size = now;
          }
          return read();
        };
        const signIn = await page
          .goto(`${base}/__as/${ROLES[role].alias}?next=${HOME}`, { waitUntil: "domcontentloaded", timeout: 90000 })
          .catch(() => null);
        if (!signIn || signIn.status() >= 400) {
          rows.push({ role, size, path: HOME, note: `no sign-in as ${ROLES[role].alias} (HTTP ${signIn?.status() ?? "none"})` });
          await context.close();
          continue;
        }
        // The role's own workspace, chosen as the app chooses it (a person with two picks one in the switcher).
        if (ROLES[role].workspace) {
          const chosen = await page
            .evaluate(async (name) => {
              const list = await (await fetch("/v1/me/workspaces", { credentials: "include" })).json();
              const found = (list.workspaces ?? []).find((w) => w.name === name);
              if (!found) return "not a member";
              if (list.selected_tenant_id === found.tenant_id) return "ok";
              const answer = await fetch("/v1/context", {
                method: "POST",
                credentials: "same-origin",
                headers: { "content-type": "application/json", accept: "application/json" },
                body: JSON.stringify({ tenant_id: found.tenant_id }),
              });
              return answer.ok ? "ok" : `HTTP ${answer.status}`;
            }, ROLES[role].workspace)
            .catch((error) => String(error.message).slice(0, 80));
          if (chosen !== "ok") {
            rows.push({ role, size, path: HOME, note: `could not open ${ROLES[role].workspace} (${chosen})` });
            await context.close();
            continue;
          }
          await page.goto(base + HOME, { waitUntil: "domcontentloaded", timeout: 90000 }).catch(() => null);
        }
        // The menu: every in-app link on Home and the hubs, as this role sees them.
        const hrefs = [];
        for (const hub of HUBS) {
          if (hub !== HOME)
            await page.goto(base + hub, { waitUntil: "domcontentloaded", timeout: 90000 }).catch(() => null);
          await settle();
          hrefs.push(hub, ...(await page.$$eval("a[href]", (links) => links.map((a) => a.getAttribute("href"))).catch(() => [])));
        }
        for (const path of plan(hrefs, most)) {
          let note;
          // The dev server compiles a page on first ask and can answer 502 or run out of time while it does: a
          // page that fails that way is opened once more before it counts.
          for (let attempt = 1; attempt <= 2; attempt++) {
            errors.length = 0;
            serverErrors.length = 0;
            try {
              const response = await page.goto(base + path, { waitUntil: "domcontentloaded", timeout: 90000 });
              const text = await settle();
              note = judge({
                text,
                errors: [...errors],
                serverErrors: [...serverErrors],
                status: response?.status() ?? 0,
                home: path === HOME,
              });
            } catch (error) {
              note = String(error.message).split("\n")[0].slice(0, 120);
            }
            if (!note || !/Timeout|HTTP 50\d|API 50\d|a blank page/.test(note)) break;
            await page.waitForTimeout(5000);
          }
          rows.push({ role, size, path, ...(note ? { note } : {}) });
          process.stdout.write(`${role} ${size} ${path}: ${note ?? "ok"}\n`);
          if (note)
            await page
              .screenshot({
                path: resolve(output, `${role}-${size}-${path.replace(/[^a-z0-9]+/gi, "-").slice(0, 60)}.jpg`),
                type: "jpeg",
                quality: 50,
                scale: "css",
              })
              .catch(() => undefined);
        }
        await context.close();
      }
  } finally {
    await browser.close().catch(() => undefined);
  }
  const report = reportMarkdown(rows);
  writeFileSync(resolve(output, "role-walk.json"), JSON.stringify(rows, null, 1));
  writeFileSync(resolve(output, "report.md"), report);
  console.log(report);
  return rows.some((row) => row.note) ? 1 : 0;
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) process.exit(await main());
