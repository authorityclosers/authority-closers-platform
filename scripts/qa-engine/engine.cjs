#!/usr/bin/env node
// Sales X-Ray test robot, engine (b). Dev only, sandbox organisations only, scripts only (no AI in the loop).
//
//   node engine.cjs rows   [--max N] [--sizes "390 px,1440"] [--batch 8]     run matrix rows (click destinations)
//   node engine.cjs sweep  <axe|visual|monkey|crawl> [--sizes ...] [--themes light,dark] [--routes /a,/b]
//                          [--role seller|owner] [--approve]
//   node engine.cjs daemon [--sizes ...]                                    rows and sweeps in turn, until STOP
//   node engine.cjs sim    [--workers 4] [--minutes N] [--sizes ...]         persona simulator: seeded walks, invariants, parallel
//   node engine.cjs sim --seed N --persona P05 --device "390 px" --theme dark --area Leads [--state normal]   replay one walk
//   node engine.cjs digest                                                  print the digest since the last one
//   node engine.cjs scope                                                   how many rows the click runner can claim
// It waits (lib/guard.cjs) while a release cut runs, a PAUSE file exists, or ac is under memory or CPU pressure;
// a STOP file ends it. Findings go to the app's bug reporter on dev with a picture, and to the matrix's Bugs tab.
const fs = require("fs");
const path = require("path");
const cfg = require("./lib/config.cjs");
const { headroom, snapshot, sleep } = require("./lib/guard.cjs");
const session = require("./lib/session.cjs");
const matrix = require("./lib/matrix.cjs");
const personas = require("./lib/personas.cjs");
const report = require("./lib/report.cjs");
const clickmap = require("./lib/clickmap.cjs");
const visual = require("./lib/visual.cjs");
const monkey = require("./lib/monkey.cjs");
const crawler = require("./lib/crawler.cjs");
const planned = require("./lib/plans.cjs");
const { rebuilding } = require("./lib/rebuild.cjs");
const { startLatencyProbe } = require("./lib/guard.cjs");
const inv = require("./lib/invariants.cjs");
const { axeFindings } = require("./lib/probe.cjs");
const sim = require("./lib/sim.cjs");
const attack = require("./lib/attack.cjs");
const { probe, routeOf } = require("./lib/probe.cjs");

const args = (() => {
  const out = { _: [] };
  const raw = process.argv.slice(2);
  for (let i = 0; i < raw.length; i++) {
    if (raw[i].startsWith("--")) {
      const key = raw[i].slice(2);
      out[key] = raw[i + 1] && !raw[i + 1].startsWith("--") ? raw[++i] : true;
    } else out._.push(raw[i]);
  }
  return out;
})();
const SIZES = (args.sizes || "390 px,360 px,1440,1920").split(",").map((s) => s.trim());
const log = (text) => console.log(`${new Date().toISOString().slice(11, 19)} ${text}`);
fs.mkdirSync(cfg.OUT, { recursive: true });
fs.mkdirSync(cfg.STATE, { recursive: true });

// ---- areas, routes ----------------------------------------------------------------------------------------------
function areaOfRoute(route) {
  const u = new URL(route, "http://x");
  const p = u.pathname;
  const q = u.searchParams;
  if (p.startsWith("/dashboard")) return "Home";
  if (p.startsWith("/leads")) {
    if (q.get("tab") === "tasks") return "Tasks";
    if (q.get("view") === "follow_ups" || q.get("tab") === "follow_ups") return "Follow-ups";
    if (q.get("lead") || p.startsWith("/leads/notes")) return "Prospect's Information";
    return "Leads";
  }
  if (p.startsWith("/performance")) return "Performance";
  if (p.startsWith("/reports") || p.startsWith("/analysis")) return "Reports";
  if (p.startsWith("/coaching")) return "Growth";
  if (p.startsWith("/organisation")) return "Owner controls";
  if (p.startsWith("/account") || p.startsWith("/settings") || p.startsWith("/plans")) return "Settings";
  if (p.startsWith("/login") || p.startsWith("/sign")) return "Sign-in";
  return "Home";
}

// Pages every person can open (seller) and the owner's. Direct loads, as a returning person's bookmark would.
const ROUTES = {
  seller: ["/dashboard", "/leads", "/leads?tab=all", "/leads?tab=tasks", "/leads?view=follow_ups", "/performance", "/reports", "/coaching", "/analysis/calls", "/account", "/chats"],
  owner: ["/dashboard", "/leads", "/performance", "/reports", "/coaching?view=team", "/organisation", "/organisation?tab=members", "/organisation/insights?range=all", "/account"],
};
const SINGLE_SIDE = new Set(["sneha", "neha", "aditya", "imran"]);
const SIDE_SELECTOR = new Set(["05", "06", "44", "45"]);
const probeCache = new Map();
const leadCache = new Map();

const SEV_BY_PRIORITY = { P0: "MAJOR", P1: "MAJOR", P2: "MINOR" };
const png = (name) => path.join(cfg.OUT, new Date().toISOString().slice(0, 10), name);

async function saveShot(tab, name) {
  const file = png(name);
  fs.mkdirSync(path.dirname(file), { recursive: true });
  await tab.page.screenshot({ path: file, type: "png", timeout: 15000 }).catch(() => null);
  return fs.existsSync(file) ? file : "";
}

// ---- one matrix row ---------------------------------------------------------------------------------------------
async function offlineCheck(tab, listed, lead) {
  const entry = clickmap.atSize(listed, tab.dev.phone);
  const page = tab.page;
  const start = entry.start.replace("{lead}", lead || "");
  const opened = await session.go(tab, start, { wait: 25000 });
  if (!opened.ok && /ERR_ABORTED|ERR_CONNECTION|ERR_NETWORK|Timeout|timed out/i.test(opened.error)) return { outcome: "skipped", reason: "the start page did not open: not judged" };
  if (!opened.ok) return { outcome: "fail", reason: `the page did not open: ${opened.error}`, route: routeOf(start), selector: "page load" };
  const mark = tab.mark();
  await tab.context.setOffline(true);
  try {
    const name = entry.control && entry.control.name;
    const found = name ? page.getByRole(entry.control.role, { name: entry.control.regex ? new RegExp(name) : name }).filter({ visible: true }) : null;
    if (found && (await found.count()) && entry.kind !== "present" && !entry.no_press) {
      await found.first().click({ timeout: 8000 }).catch(() => null);
    } else {
      await page.reload({ timeout: 15000 }).catch(() => null);
    }
    await sleep(3500);
    const text = (await page.evaluate(() => document.body.innerText || "").catch(() => "")).replace(/\s+/g, " ");
    const seen = tab.since(mark);
    const failed = seen.failed.length + seen.http.length;
    const honest = /offline|no (internet|connection)|can.?t (load|reach|connect)|cannot load|couldn.?t load|try again|retry|check your connection|not saved yet/i.test(text);
    const route = routeOf(start);
    const label = entry.control ? `${entry.control.role} "${entry.control.name}"` : "page";
    if (text.length < 25) return { outcome: "blocked", reason: "offline: the page went blank; the dev build loads each page on demand, so this needs staging to judge", route, selector: `offline ${label}` };
    if (seen.pageerrors.length && seen.pageerrors.every((e) => /Failed to load chunk|Loading chunk|dynamically imported module/i.test(e))) return { outcome: "blocked", reason: "offline: a page script was not loaded; the dev build loads them on demand, so this needs staging to judge", route, selector: `offline ${label}` };
    if (seen.pageerrors.length) return { outcome: "fail", reason: `offline: a script error was thrown (${seen.pageerrors[0].slice(0, 80)})`, route, selector: `offline ${label}`, severity: "MAJOR" };
    if (failed && !honest) return { outcome: "fail", reason: "offline: the screen says nothing about the lost connection", route, selector: `offline ${label}`, severity: "MINOR" };
    return { outcome: "pass", reason: honest ? "offline: an honest message is shown" : "offline: nothing failed and the page stays usable", route, selector: label };
  } finally {
    await tab.context.setOffline(false).catch(() => null);
  }
}

let current = null; // { key, tab }
async function tabFor(alias, row) {
  const key = `${alias}|${row.device}|${row.theme}|${row.state}`;
  if (current && current.key === key && !current.tab.page.isClosed()) return current.tab;
  if (current) await session.closeTab(current.tab).catch(() => null);
  const tab = await session.openTab({ alias, device: row.device, theme: row.theme, state: row.state });
  current = { key, tab };
  return tab;
}

async function runRow(row) {
  const id = ((row.spec_ref || "").match(/item (\d{2})/) || [])[1];
  const listed = id && clickmap.byId.get(id);
  const plan = planned.plans[row.journey_id];
  if (!plan && (!listed || listed.kind === "todo")) {
    return { result: "held" }; // not scripted: leave the claim to run out so the AI walkers can take it
  }
  const alias = plan && plan.as ? plan.as : await personas.aliasFor(row.persona);
  const tab = await tabFor(alias, row);
  const filer = alias === "owner" ? "priya" : alias;
  const phoneSize = tab.dev.phone;
  const probes = [];
  const mark = tab.mark();
  let outcome;
  let subject;
  const ctx = { tab, alias, filer, persona: row.persona, device: row.device, theme: row.theme, workflow: row.workflow_id };
  if (plan) {
    subject = { rule: `plan:${row.journey_id}`, element: row.journey.slice(0, 80), destination: row.journey, notBuiltIsBlocked: true };
    if (!planned.applies(plan, tab, row)) {
      outcome = { outcome: "blocked", reason: `not applicable at ${row.device}, ${row.theme} (the plan is for ${plan.phoneOnly ? "phones" : plan.desktopOnly ? "computers" : plan.themeOnly + " mode"})`, route: plan.route };
    } else {
      try {
        const opened = await planned.open(tab, plan.route);
        outcome =
          opened ||
          (row.state === "offline"
            ? await offlinePlan(tab, plan)
            : await plan.run({ tab, alias, row, mark: tab.mark() }));
        if (!opened) {
          const key = `${alias}|${plan.route}|${row.device}|${row.theme}|${row.state}`;
          if (!(probeCache.has(key) && Date.now() - probeCache.get(key) < 30 * 60 * 1000)) {
            probeCache.set(key, Date.now());
            probes.push(...inv.rollup(await probe(tab, routeOf(plan.route), { mark }), tab.dev.key));
          }
        }
      } catch (error) {
        outcome = { outcome: "fail", reason: `error: ${String(error).split("\n")[0].slice(0, 160)}`, route: plan.route, selector: "robot", severity: "MINOR" };
      }
    }
  } else {
    subject = { rule: `click:${id}`, element: listed.element, destination: listed.destination, status: listed.status, id };
    if (!leadCache.has(alias)) {
      await session.go(tab, "/leads?view=all", { wait: 25000 });
      leadCache.set(alias, await clickmap.leadFor(tab, false));
    }
    const lead = leadCache.get(alias);
    const onOpened = async (route) => {
      const key = `${alias}|${route}|${row.device}|${row.theme}|${row.state}`;
      if (probeCache.has(key) && Date.now() - probeCache.get(key) < 30 * 60 * 1000) return;
      probeCache.set(key, Date.now());
      probes.push(...inv.rollup(await probe(tab, route, { skipAxe: false }), tab.dev.key));
    };
    try {
      outcome =
        row.state === "offline"
          ? await offlineCheck(tab, listed, lead)
          : await clickmap.check(tab, listed, { lead, owner: false, slow: row.state === "slow network", onOpened });
    } catch (error) {
      outcome = { outcome: "fail", reason: `error: ${String(error).split("\n")[0].slice(0, 160)}`, route: "/", selector: "robot" };
    }
    if (outcome.outcome === "skipped") return { result: "held" };
    if (outcome.outcome === "missing" && SINGLE_SIDE.has(alias) && SIDE_SELECTOR.has(id)) {
      outcome = { outcome: "pass", reason: "no side selector for a one-side seller, as the handoff says", route: outcome.route, selector: outcome.selector };
    }
  }
  // an offline-state row: console and API errors are the robot's own network cut, not findings
  if (row.state === "offline") probes.splice(0, probes.length, ...probes.filter((p) => !/^(page:|axe:|script:|api:)/.test(p.rule)));
  // the robot's own browser closed under the row (a restart): nothing to judge
  if (outcome.outcome === "fail" && /has been closed|Target closed|browser has been closed/i.test(String(outcome.reason))) return { result: "held" };
  // dev rebuilding (Next overlay, "compiling", a /_next error burst): a failure now says nothing about the app
  if ((outcome.outcome === "fail" || probes.some((p) => ["BLOCKER", "MAJOR"].includes(p.severity))) && (await rebuilding(tab))) {
    if (!row.retried) {
      row.retried = true;
      log(`  dev is rebuilding: ${row.workflow_id} held, judged again in 2 minutes`);
      await sleep(120000);
      return runRow(row);
    }
    await matrix.release(row.workflow_id);
    return { result: "held" };
  }
  const bugs = [];
  const fileOne = async (finding, area) => {
    const out = await report.file(finding, { ...ctx, area });
    if (out.bugId) bugs.push(out.bugId);
    log(`  bug ${out.action} ${out.bugId || ""} ${finding.rule} ${finding.route}${out.reason ? ` (${out.reason})` : ""}`);
  };
  let result = "pass";
  const notes = [plan ? `plan ${row.journey_id}` : `click-map ${id} ${listed.element}`, outcome.reason];
  if (outcome.outcome === "fail") {
    result = "fail";
    await fileOne(
      {
        rule: subject.rule,
        selector: outcome.selector,
        severity: outcome.severity || SEV_BY_PRIORITY[row.priority] || "MAJOR",
        summary: plan ? `${row.journey.slice(0, 110)}: it does not hold` : `Handoff item ${id} "${listed.element}" does not do what the handoff says`,
        detail: plan ? outcome.reason : `${outcome.reason}. Handoff: ${listed.destination}`,
        route: outcome.route || "/",
      },
      row.area,
    );
  } else if (outcome.outcome === "blocked") {
    result = "blocked";
    notes.push("not built the handoff's way yet, or not applicable here");
  } else if (outcome.outcome === "missing") {
    if (listed.status === "live" && !(listed.at && (listed.at[phoneSize ? "phone" : "desktop"] || {}).status === "expected-missing")) {
      result = "fail";
      await fileOne(
        {
          rule: `click:${id}:missing`,
          selector: outcome.selector,
          severity: "MAJOR",
          summary: `Handoff item ${id} "${listed.element}" is not on the page`,
          detail: `${outcome.reason}. Handoff: ${listed.destination}`,
          route: outcome.route || "/",
        },
        row.area,
      );
    } else {
      result = "blocked";
      notes.push("not built the handoff's way yet (expected-missing)");
    }
  }
  for (const finding of probes) {
    if (finding.internal) continue;
    await fileOne(finding, areaOfRoute(finding.route));
    if (["BLOCKER", "MAJOR"].includes(finding.severity) && result === "pass") result = "fail";
  }
  if (probes.length) notes.push(`${probes.length} page finding(s): ${[...new Set(probes.map((p) => p.rule))].join(", ")}`);
  const seen = tab.since(mark);
  if (seen.pageerrors.length && result === "pass") notes.push(`script error: ${seen.pageerrors[0].slice(0, 80)}`);
  const shot = result === "fail" ? await saveShot(tab, `${row.workflow_id}.png`) : "";
  await matrix.result({
    workflow: row.workflow_id,
    result,
    persona: row.persona,
    device: row.device,
    screenshot: shot,
    bugs: [...new Set(bugs)].join(","),
    notes: notes.join(" | ").slice(0, 480),
  });
  report.tally("rows");
  report.tally(result === "pass" ? "pass" : result === "fail" ? "fail" : "blocked");
  return { result };
}

// Offline for a plan: load the page, lose the connection, reload; the page must not go blank or break silently.
async function offlinePlan(tab, plan) {
  const page = tab.page;
  const mark = tab.mark();
  await tab.context.setOffline(true);
  try {
    await page.reload({ timeout: 15000 }).catch(() => null);
    await sleep(3000);
    const text = (await page.evaluate(() => document.body.innerText || "").catch(() => "")).replace(/\s+/g, " ");
    const honest = /offline|no (internet|connection)|can.?t (load|reach|connect)|cannot load|couldn.?t load|try again|retry|check your connection/i.test(text);
    const route = routeOf(plan.route);
    if (text.length < 25) return { outcome: "blocked", reason: "offline: the page went blank; the dev build loads each page on demand, so this needs staging to judge", route, selector: "offline page" };
    if (tab.since(mark).pageerrors.length) return { outcome: "fail", reason: "offline: a script error was thrown", route, selector: "offline page", severity: "MAJOR" };
    return honest ? { outcome: "pass", reason: "offline: an honest message is shown", route, selector: "offline page" } : { outcome: "blocked", reason: "offline: the browser's own offline page or cached page was shown; no app wording to judge", route, selector: "offline page" };
  } finally {
    await tab.context.setOffline(false).catch(() => null);
  }
}

// ---- rows loop -------------------------------------------------------------------------------------------------
async function scriptedJourneys() {
  const clicks = clickmap.manifest.destinations.filter((e) => e.kind !== "todo").map((e) => `J${e.id.padStart(3, "0")}`);
  return [...new Set([...clicks, ...Object.keys(planned.plans)])];
}

async function rowsLoop({ max = Infinity, batch = 8 } = {}) {
  const sellers = await personas.sellerIds();
  const journeys = (await scriptedJourneys()).join(",");
  let done = 0;
  while (done < max) {
    if ((await headroom(log)) === "stop") return { done, why: "stop" };
    const rows = await matrix.claim({ journeys, devices: SIZES.join(","), states: "normal,slow network,offline", persona: sellers.join(","), n: Math.min(batch, max - done), hold: 25 });
    if (!rows.length) return { done, why: "no rows left" };
    rows.sort((a, b) => `${a.persona}${a.device}${a.theme}${a.state}`.localeCompare(`${b.persona}${b.device}${b.theme}${b.state}`));
    for (const row of rows) {
      if ((await headroom(log)) === "stop") {
        await matrix.release(row.workflow_id);
        continue;
      }
      const t0 = Date.now();
      try {
        const out = await runRow(row);
        log(`${row.workflow_id} ${row.journey_id} ${row.persona} ${row.device} ${row.theme} ${row.state}: ${out.result} (${Math.round((Date.now() - t0) / 1000)} s)`);
        if (out.result !== "held") done++;
      } catch (error) {
        log(`${row.workflow_id} failed in the robot: ${String(error).split("\n")[0].slice(0, 160)}`);
        await matrix.release(row.workflow_id).catch(() => null);
        if (/Target closed|browser has been closed|disconnected/i.test(String(error))) current = null;
      }
    }
  }
  return { done, why: "max reached" };
}

// ---- sweeps ----------------------------------------------------------------------------------------------------
async function sweep(kind, { role = "seller", sizes = SIZES, themes = ["light", "dark"], routes = null, approve = false } = {}) {
  const alias = role === "owner" ? "owner" : "priya";
  const filer = "priya";
  const persona = role === "owner" ? "P16" : "P01";
  const list = routes || ROUTES[role];
  const summary = {};
  for (const size of sizes) {
    const unit = { routes: 0, findings: 0, filed: 0, counted: 0, held: 0, failed: 0, baselines: 0, same: 0, diffs: 0 };
    const bugs = [];
    for (const theme of themes) {
      if ((await headroom(log)) === "stop") return summary;
      let tab;
      try {
        tab = await session.openTab({ alias, device: size, theme, state: "normal" });
      } catch (error) {
        log(`sweep ${kind} ${size} ${theme}: cannot open (${String(error).split("\n")[0].slice(0, 120)})`);
        continue;
      }
      for (const route of list) {
        if ((await headroom(log)) === "stop") break;
        const mark = tab.mark();
        let findings = [];
        let extraPng = null;
        try {
          if (kind === "crawl") {
            const res = await crawler.crawl(tab, route, { limit: 70 });
            fs.mkdirSync(path.join(cfg.OUT, "crawl"), { recursive: true });
            fs.writeFileSync(path.join(cfg.OUT, "crawl", `${role}-${tab.dev.key}-${routeOf(route).replace(/[^a-z0-9]+/gi, "_")}.json`), JSON.stringify(res, null, 1));
            findings = res.findings;
            log(`crawl ${role} ${size} ${route}: ${res.found} controls, ${res.pressed} pressed, ${findings.length} broken`);
          } else if (kind === "monkey") {
            const seed = Number(process.env.QA_SEED || Date.now() % 100000);
            const res = await monkey.monkeyRoute(tab, route, seed);
            await monkey.releaseReadOnly(tab);
            findings = res.findings;
            log(`monkey ${role} ${size} ${theme} ${route}: ${res.outcome}, ${findings.length} finding(s)`);
          } else {
            const opened = await session.go(tab, route, { wait: 25000 });
            if (!opened.ok) {
              findings = [{ rule: "page:load", selector: "", severity: "MAJOR", summary: "The page did not open", detail: opened.error, route: routeOf(route) }];
            } else if (kind === "axe") {
              findings = await probe(tab, routeOf(route), { mark });
            } else if (kind === "visual") {
              const res = await visual.compare(tab, routeOf(route), theme, { approve });
              if (res.status === "baseline") unit.baselines++;
              else if (res.status === "same") unit.same++;
              else {
                unit.diffs++;
                findings = [visual.findingFor(res, routeOf(route), theme, tab.dev.key)];
                extraPng = res.png;
              }
            }
          }
        } catch (error) {
          log(`sweep ${kind} ${size} ${theme} ${route}: ${String(error).split("\n")[0].slice(0, 140)}`);
          if (/Target closed|browser has been closed|disconnected/i.test(String(error))) break;
          continue;
        }
        unit.routes++;
        for (const finding of findings) {
          if (finding.internal) continue;
          unit.findings++;
          const out = await report.file(finding, { tab, alias, filer, persona, device: size, theme, area: areaOfRoute(finding.route), png: extraPng });
          unit[out.action === "failed" ? "failed" : out.action]++;
          if (out.bugId) bugs.push(out.bugId);
          log(`  ${out.action} ${out.bugId || ""} ${finding.rule} ${finding.route} ${finding.selector}${out.reason ? ` (${out.reason})` : ""}`);
        }
      }
      await session.closeTab(tab);
    }
    summary[size] = unit;
    report.sweepTally(kind, "runs");
    const note = `${kind} sweep as ${role}: ${unit.routes} page views, ${unit.findings} findings (${unit.filed} filed, ${unit.counted} counted again, ${unit.held} held)${kind === "visual" ? `, ${unit.baselines} baselines made, ${unit.same} same, ${unit.diffs} differ` : ""}`;
    await matrix
      .sweep({ persona, device: size, result: unit.findings ? "fail" : "pass", bugs: [...new Set(bugs)].join(","), notes: note })
      .catch((error) => log(`could not write the Runs row: ${error.message}`));
    log(note);
  }
  return summary;
}

// ---- daemon ---------------------------------------------------------------------------------------------------
async function daemon() {
  const turns = [
    () => rowsLoop({ max: 40, batch: 8 }),
    () => sweep("axe", { sizes: [SIZES[0], SIZES[2] || SIZES[0]], themes: ["light", "dark"] }),
    () => rowsLoop({ max: 40, batch: 8 }),
    () => sweep("visual", { sizes: SIZES, themes: ["light", "dark"] }),
    () => rowsLoop({ max: 40, batch: 8 }),
    () => sweep("monkey", { sizes: ["390 px", "1440"], themes: ["light"], routes: ["/dashboard", "/leads", "/leads?tab=tasks"] }),
    () => rowsLoop({ max: 40, batch: 8 }),
    () => sweep("crawl", { sizes: ["390 px", "1440"], themes: ["light"], routes: ["/dashboard", "/leads"] }),
  ];
  let i = 0;
  let idle = 0;
  for (;;) {
    if ((await headroom(log)) === "stop") break;
    const t0 = Date.now();
    let out = null;
    try {
      out = await turns[i % turns.length]();
    } catch (error) {
      log(`turn ${i % turns.length} failed: ${String(error).split("\n")[0].slice(0, 160)}`);
      current = null;
      await session.shutdown().catch(() => null);
    }
    if (out && out.why === "no rows left") idle++;
    i++;
    // let the box breathe between turns; a turn that did nothing waits longer
    await sleep(Math.max(20000, Math.min(180000, (Date.now() - t0) / 4)));
    if (idle > turns.length * 2) {
      log("nothing left for the click runner; sweeps only now");
      idle = 0;
    }
  }
  await session.shutdown();
}

// ---- mixed: one worker, scripted rows and a persona walk in turn ----------------------------------------------------
async function mixed() {
  startLatencyProbe(() => session.cookieHeader("priya"), () => {});
  for (;;) {
    if ((await headroom(log)) === "stop") break;
    try {
      const rows = await rowsLoop({ max: 6, batch: 6 });
      if (current) {
        await session.closeTab(current.tab).catch(() => null);
        current = null;
      }
      const walk = await sim.runOne(SIZES);
      // state attacks: a few cells after each walk (QA_ATTACK_PER_TURN, default 3)
      let attacked = 0;
      for (let i = 0; i < Number(process.env.QA_ATTACK_PER_TURN || 6); i++) {
        if ((await headroom(log)) === "stop") break;
        const a = await attack.runOne({});
        if (!a || a.stopped) break;
        attacked++;
      }
      log(`mixed turn: rows ${rows.done} (${rows.why}), walk ${walk ? (walk.error ? "broke" : "done") : "none"}, attacks ${attacked}`);
    } catch (error) {
      log(`mixed turn failed: ${String(error).split("\n")[0].slice(0, 160)}`);
      current = null;
      await session.shutdown().catch(() => null);
      await sleep(30000);
    }
    await sleep(15000);
  }
  await session.shutdown();
}

// ---- rejudge: which of the robot's own reports still show on a fresh load today -------------------------------------
async function rejudge() {
  const entries = Object.entries(report.ledger).filter(([, v]) => v.route && v.rule && !v.rule.startsWith("sim:") && !v.rule.startsWith("monkey:"));
  const groups = new Map();
  for (const [key, v] of entries) {
    for (const size of v.device && cfg.DEVICES[v.device] ? [v.device] : ["390 px", "1440"]) {
      const k = `${size}|${v.area}|${v.route}`;
      if (!groups.has(k)) groups.set(k, { size, area: v.area, route: v.route, keys: [] });
      groups.get(k).keys.push([key, v]);
    }
  }
  const state = {};
  for (const [, g] of groups) {
    if ((await headroom(log)) === "stop") break;
    const owner = ["Owner controls", "Reports", "Stage editor", "Lead import"].includes(g.area);
    let tab;
    try {
      tab = await session.openTab({ alias: owner ? "owner" : "priya", device: g.size, theme: "light", state: "normal" });
      const opened = await session.go(tab, g.route, { wait: 30000 });
      if (!opened.ok) continue;
      const phone = tab.dev.phone;
      const s = await tab.page.evaluate(inv.scan, phone).catch(() => null);
      const found = s ? inv.rollup(inv.findingsFrom(s, { route: routeOf(tab.page.url()), phone }), tab.dev.key) : [];
      if (g.keys.some(([, v]) => v.rule.startsWith("axe:"))) found.push(...(await axeFindings(tab, routeOf(tab.page.url()))));
      const now = new Set(found.map((f) => report.fingerprintOf(g.area, f)));
      for (const [key] of g.keys) state[key] = state[key] === "still" || now.has(key) ? "still" : "gone";
    } catch (error) {
      log(`rejudge ${g.route}: ${String(error).split("\n")[0].slice(0, 100)}`);
    } finally {
      if (tab) await session.closeTab(tab).catch(() => null);
    }
  }
  const byRule = {};
  for (const [key, v] of entries) {
    if (!state[key]) continue;
    const r = (byRule[v.rule] ||= { still: 0, gone: 0, gone_ids: [] });
    if (state[key] === "still") r.still++;
    else {
      r.gone++;
      r.gone_ids.push(v.bugId);
    }
  }
  fs.writeFileSync(path.join(cfg.STATE, "rejudge.json"), JSON.stringify({ at: new Date().toISOString(), byRule, state }, null, 1));
  for (const [rule, r] of Object.entries(byRule)) log(`rejudge ${rule}: ${r.still} still show, ${r.gone} not on a fresh load${r.gone ? ` (${r.gone_ids.slice(0, 12).join(" ")})` : ""}`);
  await session.shutdown();
}

// ---- rollup-existing: one report per page, rule and viewport for what was filed element by element --------------------
async function foldExisting() {
  const entries = Object.entries(report.ledger).filter(([, v]) => inv.ROLLED[v.rule] && !v.dupOf && v.route);
  const groups = new Map();
  for (const [key, v] of entries) {
    for (const size of v.device && cfg.DEVICES[v.device] ? [v.device] : ["390 px", "1440"]) {
      const k = `${size}|${v.area}|${v.route}`;
      if (!groups.has(k)) groups.set(k, { size, area: v.area, route: v.route, entries: [] });
      groups.get(k).entries.push([key, v]);
    }
  }
  log(`rollup-existing: ${entries.length} per-element reports in ${groups.size} page and viewport groups`);
  let rolled = 0;
  let folded = 0;
  for (const [, g] of groups) {
    if ((await headroom(log)) === "stop") break;
    const owner = ["Owner controls", "Reports", "Stage editor", "Lead import"].includes(g.area);
    let tab;
    try {
      tab = await session.openTab({ alias: owner ? "owner" : "priya", device: g.size, theme: "light", state: "normal" });
      const opened = await session.go(tab, g.route, { wait: 30000 });
      if (!opened.ok) continue;
      const route = routeOf(tab.page.url());
      const phone = tab.dev.phone;
      const s = await tab.page.evaluate(inv.scan, phone).catch(() => null);
      if (!s) continue;
      const roll = inv.rollup(inv.findingsFrom(s, { route, phone }), tab.dev.key).filter((f) => f.rolled);
      for (const f of roll) {
        const ctx = { tab, alias: owner ? "owner" : "priya", filer: "priya", persona: owner ? "P16" : "P01", device: g.size, theme: "light", area: g.area };
        const res = await report.file(f, ctx);
        if (!res.bugId) {
          log(`  roll-up not filed for ${f.summary}: ${res.action} ${res.reason || ""}`);
          continue;
        }
        rolled++;
        log(`  roll-up ${res.action} ${res.bugId}: ${f.summary}`);
        for (const [key, v] of g.entries.filter(([, e]) => e.rule === f.rule)) {
          if (report.ledger[key].dupOf) continue;
          report.ledger[key].dupOf = res.bugId;
          folded++;
          await matrix.annotate({ id: v.bugId, prefix: `DUPLICATE of ${res.bugId} (rolled up: ${f.summary.slice(0, 80)})` }).catch(() => null);
        }
        report.save();
      }
    } catch (error) {
      log(`rollup-existing ${g.route}: ${String(error).split("\n")[0].slice(0, 100)}`);
    } finally {
      if (tab) await session.closeTab(tab).catch(() => null);
    }
  }
  report.save();
  log(`rollup-existing done: ${rolled} roll-ups, ${folded} per-element reports marked as duplicates`);
  await session.shutdown();
}

// ---- digest -----------------------------------------------------------------------------------------------------
function digest() {
  const file = path.join(cfg.STATE, "digest-marker.json");
  let marker = { rows: 0, pass: 0, fail: 0, blocked: 0, bugs: 0, at: report.stats.since };
  try {
    marker = JSON.parse(fs.readFileSync(file, "utf8"));
  } catch {
    /* first digest */
  }
  const s = report.stats;
  const d = { rows: s.rows - marker.rows, pass: s.pass - marker.pass, fail: s.fail - marker.fail, blocked: s.blocked - marker.blocked, walks: s.walks - (marker.walks || 0), steps: s.steps - (marker.steps || 0), found: s.walkFindings - (marker.walkFindings || 0), held: s.writesHeld - (marker.writesHeld || 0) };
  const delta = (now, then) => Object.entries(now).map(([k, v]) => [k, v - ((then || {})[k] || 0)]).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1]);
  const fmt = (list, n = 8) => list.slice(0, n).map(([k, v]) => `${k} ${v}`).join(", ") || "none";
  const filedByCheck = delta(s.filedByCheck, marker.filedByCheck);
  const filedByArea = delta(s.filedByArea, marker.filedByArea);
  const againByCheck = delta(s.againByCheck, marker.againByCheck);
  const newBugs = s.bugList.slice(marker.bugs);
  const byBuilder = {};
  for (const b of newBugs) byBuilder[b.builder] = (byBuilder[b.builder] || 0) + 1;
  const ledgerTop = Object.values(report.ledger).sort((a, b) => b.seen - a.seen).slice(0, 5);
  const sweeps = Object.entries(s.sweeps).map(([k, v]) => `${k} ${v.runs}`).join(", ") || "none yet";
  const g = snapshot();
  const text = [
    `Engine (b) digest, ${new Date().toISOString().slice(0, 16)}Z (since ${marker.at.slice(0, 16)}Z)`,
    `Persona walks completed: ${d.walks} (${d.steps} steps, ${d.found} violations seen, ${d.held} writes held and refused); all time ${s.walks} walks, ${s.steps} steps.`,
    `Reports filed (new, through the app's reporter): ${filedByCheck.reduce((a, [, v]) => a + v, 0)}. By check: ${fmt(filedByCheck)}. By area: ${fmt(filedByArea)}.`,
    `Seen again, counted +1 and not re-filed: ${againByCheck.reduce((a, [, v]) => a + v, 0)}${againByCheck.length ? ` (${fmt(againByCheck, 5)})` : ""}.`,
    `Scripted rows run: ${d.rows} (pass ${d.pass}, fail ${d.fail}, blocked ${d.blocked}); all time ${s.rows} rows, pass ${s.pass}, fail ${s.fail}, blocked ${s.blocked}.`,
    `Sweeps run (all time): ${sweeps}.`,
    attack.digestLine(marker.at),
    `New bugs: ${newBugs.length}${newBugs.length ? ` by builder: ${Object.entries(byBuilder).map(([k, v]) => `${k} ${v}`).join(", ")}` : ""}.`,
    `Top 5 by sightings: ${ledgerTop.map((b) => `${b.bugId} x${b.seen} ${b.area} ${b.route} [${b.rule}]`).join("; ") || "none yet"}.`,
    `Box: load ${g.load1}, cpu psi ${g.cpuPsi}, mem psi ${g.memPsi}, mem free ${g.memAvailableMb} MB${g.cut ? ", a release cut is running (the robot keeps going unless the box is tight)" : ""}${g.pause ? ", PAUSE file" : ""}.`,
  ].join("\n");
  fs.writeFileSync(file, JSON.stringify({ rows: s.rows, pass: s.pass, fail: s.fail, blocked: s.blocked, bugs: s.bugList.length, walks: s.walks, steps: s.steps, walkFindings: s.walkFindings, writesHeld: s.writesHeld, filedByCheck: s.filedByCheck, filedByArea: s.filedByArea, againByCheck: s.againByCheck, at: new Date().toISOString() }));
  return text;
}

(async () => {
  const cmd = args._[0] || "rows";
  try {
    if (cmd === "digest") {
      console.log(digest());
    } else if (cmd === "scope") {
      console.log(JSON.stringify(await matrix.scope({ journeys: (await scriptedJourneys()).join(","), devices: SIZES.join(","), states: "normal,slow network,offline", persona: (await personas.sellerIds()).join(",") })));
    } else if (cmd === "rows") {
      log(JSON.stringify(await rowsLoop({ max: Number(args.max || Infinity), batch: Number(args.batch || 8) })));
    } else if (cmd === "sweep") {
      const kind = args._[1];
      if (!["axe", "visual", "monkey", "crawl"].includes(kind)) throw new Error("sweep needs axe, visual, monkey or crawl");
      const out = await sweep(kind, {
        role: args.role || "seller",
        sizes: args.sizes ? SIZES : undefined,
        themes: args.themes ? args.themes.split(",") : undefined,
        routes: args.routes ? args.routes.split(",") : null,
        approve: !!args.approve,
      });
      log(JSON.stringify(out));
    } else if (cmd === "sim") {
      if (args.seed) {
        const row = { workflow_id: args.workflow || "W00000", journey_id: "J000", area: args.area || "Home", persona: args.persona || "P01", device: args.device || "390 px", theme: args.theme || "light", state: args.state || "normal", priority: "P1", journey: args.journey || "" };
        log(JSON.stringify(await sim.oneWalk(row, Number(args.seed))));
      } else {
        await sim.pool({ max: Number(args.workers || 4), sizes: SIZES, minutes: Number(args.minutes || Infinity) });
      }
    } else if (cmd === "attack") {
      startLatencyProbe(() => session.cookieHeader("priya"), () => {});
      const filter = { family: args.family, page: args.page, size: args.size, role: args.role };
      for (let i = 0; i < Number(args.n || 1); i++) log(JSON.stringify(await attack.runOne({ filter, dry: !!args.dry, verbose: !!args.verbose })));
    } else if (cmd === "mixed") {
      await mixed();
    } else if (cmd === "rollup-existing") {
      startLatencyProbe(() => session.cookieHeader("priya"), () => {});
      await foldExisting();
    } else if (cmd === "rejudge") {
      startLatencyProbe(() => session.cookieHeader("priya"), () => {});
      await rejudge();
    } else if (cmd === "daemon") {
      await daemon();
    } else {
      throw new Error(`unknown command ${cmd}`);
    }
  } catch (error) {
    log(`failed: ${String(error && error.stack ? error.stack : error).split("\n").slice(0, 4).join(" / ")}`);
    process.exitCode = 2;
  } finally {
    await session.shutdown().catch(() => null);
  }
})();
