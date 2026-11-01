// Filing a finding: through the app's own bug reporter on dev (POST /v1/bug-reports, as the signed-in fictional
// person, with a picture), then a row in the matrix's Bugs tab. A fingerprint (area | screen | rule: selector)
// makes repeats collapse: the same fingerprint is counted ("+1"), never filed again inside the refile window,
// and a refile sends the same words so the app joins it to the same issue (it reopens a solved one).
const fs = require("fs");
const path = require("path");
const crypto = require("crypto");
const http = require("http");
const cfg = require("./config.cjs");
const matrix = require("./matrix.cjs");
const { cookieHeader } = require("./session.cjs");
const { normSelector } = require("./util.cjs");

fs.mkdirSync(cfg.STATE, { recursive: true });
const LEDGER = path.join(cfg.STATE, "ledger.json");
const STATS = path.join(cfg.STATE, "stats.json");

function load(file, fallback) {
  try {
    return JSON.parse(fs.readFileSync(file, "utf8"));
  } catch {
    return fallback;
  }
}
const ledger = load(LEDGER, {});
const stats = load(STATS, { since: new Date().toISOString(), rows: 0, pass: 0, fail: 0, blocked: 0, newBugs: {}, bugList: [], sweeps: {}, perPersonaHour: {}, walks: 0, steps: 0, writesHeld: 0, filedByCheck: {}, againByCheck: {}, filedByArea: {}, againByArea: {}, walkFindings: 0 });
for (const k of ['filedByCheck', 'againByCheck', 'filedByArea', 'againByArea']) stats[k] ||= {};
for (const k of ['walks', 'steps', 'writesHeld', 'walkFindings']) stats[k] ||= 0;
const save = () => {
  fs.writeFileSync(LEDGER, JSON.stringify(ledger, null, 1));
  fs.writeFileSync(STATS, JSON.stringify(stats, null, 1));
};

const slug = (text) => String(text).toLowerCase().replace(/[^a-z0-9/?=&:_.\-]+/g, "-").slice(0, 80);
const fingerprintOf = (area, finding) => `${slug(area)}|${slug(finding.route)}|${finding.rule}:${slug(normSelector(finding.selector))}`.slice(0, 220);

// The report's words. The first sentence is the same every time for one fingerprint; what changes between
// sightings is numbers and one-letter tags only, so the app's own grouping (route, area and the report's key
// words) puts repeats in one issue.
function wordsFor(fp, finding, ctx) {
  const known = ledger[fp];
  if (known && known.words) return `${known.words} [+1 #${known.seen + 1}]`;
  const where = `${ctx.persona} ${ctx.device.replace(" px", "px")} ${ctx.theme === "dark" ? "D" : "L"}`;
  const text = [
    `QA robot: ${finding.summary}.`,
    `Screen ${finding.route}${finding.selector ? `, control ${finding.selector}` : ""}.`,
    finding.detail ? `Detail: ${finding.detail}` : "",
    ctx.steps && ctx.steps.length ? `Steps: ${ctx.steps.join(" ")}` : "",
    `[${where}${ctx.workflow ? ` ${ctx.workflow}` : ""}${ctx.seed ? ` seed ${ctx.seed}` : ""}]`,
  ].filter(Boolean);
  return text.join(" ").slice(0, 3600);
}

async function picture(tab, finding, extraPng) {
  if (extraPng) return { type: "image/png", data: extraPng.toString("base64") };
  const page = tab.page;
  const targets = (finding.shotAll && finding.shotAll.length ? finding.shotAll : finding.shot ? [finding.shot] : []).slice(0, 40);
  const marked = [];
  for (const css of targets) {
    const ok = await page
      .locator(css)
      .first()
      .evaluate((el, first) => {
        if (first) el.scrollIntoView({ block: "center", behavior: "instant" });
        el.dataset.qaWas = `${el.style.outline}|${el.style.outlineOffset}`;
        el.style.outline = "3px solid #e5231b";
        el.style.outlineOffset = "2px";
        return true;
      }, marked.length === 0)
      .catch(() => false);
    if (ok) marked.push(css);
  }
  const whole = targets.length > 1;
  let buf = await page.screenshot({ type: "png", fullPage: whole, timeout: 30000 }).catch(() => null);
  for (const css of marked) {
    await page
      .locator(css)
      .first()
      .evaluate((el) => {
        const [o, f] = (el.dataset.qaWas || "|").split("|");
        el.style.outline = o;
        el.style.outlineOffset = f;
        delete el.dataset.qaWas;
      })
      .catch(() => null);
  }
  if (!buf) return null;
  let type = "image/png";
  if (buf.length > 3.6 * 1024 * 1024) {
    buf = await page.screenshot({ type: "jpeg", quality: 60, fullPage: whole, timeout: 30000 }).catch(() => buf);
    type = "image/jpeg";
  }
  if (buf.length > 3.9 * 1024 * 1024) buf = await page.screenshot({ type: "jpeg", quality: 45, timeout: 30000 }).catch(() => buf);
  return { type, data: buf.toString("base64"), raw: buf };
}

// The app's own reporter endpoint, as the signed-in fictional person (the proxy gives the API the dev site's
// host and origin). Sent from here rather than from a page, so a read-only page can still report.
async function post(alias, body) {
  const cookie = await cookieHeader(alias);
  const payload = Buffer.from(JSON.stringify(body));
  const target = new URL(cfg.PROXY);
  return new Promise((resolve, reject) => {
    const req = http.request(
      {
        host: target.hostname,
        port: target.port,
        method: "POST",
        path: "/v1/bug-reports",
        headers: {
          accept: "application/json",
          "content-type": "application/json",
          "content-length": payload.length,
          cookie,
          origin: cfg.PROXY,
          referer: `${cfg.PROXY}/`,
        },
        timeout: 60000,
      },
      (res) => {
        const chunks = [];
        res.on("data", (c) => chunks.push(c));
        res.on("end", () => {
          const text = Buffer.concat(chunks).toString("utf8");
          let json = null;
          try {
            json = JSON.parse(text);
          } catch {
            /* not json */
          }
          resolve({ status: res.statusCode, json, text: text.slice(0, 160) });
        });
      },
    );
    req.on("timeout", () => req.destroy(new Error("reporter timed out")));
    req.on("error", reject);
    req.end(payload);
  });
}

const SELLERS = ["priya", "rohan", "farah", "karan", "pooja", "sneha", "imran", "neha"]; // not aditya or vikas: kept untouched
// Who files: the walker if they are a seller with budget left, else any seller with budget left.
function pickFiler(ctx) {
  const order = [ctx.filer, ctx.alias, ...SELLERS].filter((a, i, all) => a && a !== "owner" && all.indexOf(a) === i);
  for (const alias of order) if (hourBudget(alias).n < cfg.LIMITS.reportsPerPersonaPerHour) return alias;
  return null;
}

function hourBudget(alias) {
  const hour = new Date().toISOString().slice(0, 13);
  const slot = (stats.perPersonaHour[alias] ||= { hour, n: 0 });
  if (slot.hour !== hour) Object.assign(slot, { hour, n: 0 });
  return slot;
}

/**
 * ctx: { tab, alias, persona (P01), device (matrix name), theme, area (matrix area), workflow?, png? (a diff image) }
 * Returns { action: "filed" | "counted" | "held" | "failed", bugId?, fingerprint, reason? }.
 */
async function file(finding, ctx) {
  const area = ctx.area;
  const fp = fingerprintOf(area, finding);
  // nothing is filed while dev's pages do not compile: that is someone's edit, not the app
  if (!require("./guard.cjs").snapshot().devOk) return { action: "held", fingerprint: fp, reason: "dev pages are not compiling" };
  const known = ledger[fp];
  const windowMs = cfg.LIMITS.refileHours * 3600 * 1000;
  // Routing (orchestrator, 31 Oct 2026): header controls covered at phone size belong to ux-audit's notice-centre
  // fix; tap-target and overlap findings on Home go to seller-home-calls; the rest by area.
  const headerCovered = /(^|:)(focus-)?covered$/.test(finding.rule) && /px/.test(ctx.device || "") && /account|workspace|add a lead|search|notification|report a problem|bell/i.test(`${finding.selector || ""} ${finding.detail || ""}`);
  const captureSetup = /app-uploads|capture-setup|call-ai\/capture/i.test(`${finding.selector} ${finding.detail}`);
  const builder = captureSetup ? "required-call-capture-se" : headerCovered ? "ux-audit" : cfg.REPORT_AREAS[area] || "shell";
  const common = {
    area,
    builder,
    route: finding.route,
    persona: ctx.persona,
    device: ctx.device,
    fingerprint: fp,
    severity: finding.severity,
    description: `${finding.summary}${finding.selector ? ` (${finding.selector})` : ""}: ${finding.detail || ""}`.slice(0, 600),
  };
  if (known && Date.now() - known.last < windowMs) {
    known.seen += 1;
    stats.againByCheck[finding.rule] = (stats.againByCheck[finding.rule] || 0) + 1;
    stats.againByArea[area] = (stats.againByArea[area] || 0) + 1;
    await matrix.bug({ ...common, id: known.bugId }).catch((error) => console.log(`  matrix Bugs row failed for ${known.bugId}: ${error.message}`));
    save();
    return { action: "counted", bugId: known.bugId, fingerprint: fp };
  }
  const filerAlias = pickFiler(ctx);
  if (!filerAlias) return { action: "held", fingerprint: fp, reason: "hourly report budget used by every seller" };
  const budget = hourBudget(filerAlias);
  const shot = await picture(ctx.tab, finding, ctx.png);
  const words = wordsFor(fp, finding, ctx);
  const device = ctx.tab.dev;
  const body = {
    command_id: crypto.randomUUID(),
    words,
    blocks_work: finding.severity === "BLOCKER",
    route: finding.route,
    context: {
      app: { page: "qa-robot" },
      device: { platform: "web", browser: "Chromium (QA robot)", viewport: `${device.viewport.width}x${device.viewport.height}` },
    },
    client_errors: [],
    screenshot: shot ? { content_type: shot.type, data: shot.data, source: "auto" } : null,
  };
  // the dev API or proxy may be restarting or busy: three tries, a little apart, before giving up on this sighting
  let answer = null;
  for (let attempt = 0; attempt < 3; attempt++) {
    answer = await post(filerAlias, body).catch((error) => ({ status: 0, text: String(error.message || error).slice(0, 160) }));
    if (answer.status !== 0 && answer.status < 500) break;
    await new Promise((resolve) => setTimeout(resolve, 4000 * (attempt + 1)));
  }
  if (!(answer.status === 201 || answer.status === 200) || !answer.json || !answer.json.bug_id) {
    return { action: "failed", fingerprint: fp, reason: `reporter answered ${answer.status} ${answer.text}` };
  }
  budget.n += 1;
  const full = answer.json.bug_id;
  const bugId = full.slice(0, 8);
  const first = !known;
  ledger[fp] = { bugId, full, words: known ? known.words : words.replace(/ \[[^\]]*\]$/, ""), first: known ? known.first : Date.now(), last: Date.now(), seen: known ? known.seen + 1 : 1, rule: finding.rule, area, route: finding.route, device: ctx.device, selector: finding.selector };
  await matrix
    .bug({
      ...common,
      id: known ? known.bugId : bugId,
      full,
    })
    .catch((error) => console.log(`  matrix Bugs row failed for ${bugId}: ${error.message}`));
  stats.filedByCheck[finding.rule] = (stats.filedByCheck[finding.rule] || 0) + 1;
  stats.filedByArea[area] = (stats.filedByArea[area] || 0) + 1;
  if (first) {
    stats.newBugs[builder] = (stats.newBugs[builder] || 0) + 1;
    stats.bugList.push({ bugId, severity: finding.severity, area, builder, route: finding.route, rule: finding.rule, summary: finding.summary, seen: 1 });
  }
  save();
  return { action: "filed", bugId, fingerprint: fp, picture: answer.json.screenshot };
}

function simTally(out, row) {
  stats.walks += 1;
  stats.steps += out.steps || 0;
  stats.writesHeld += out.writes || 0;
  stats.walkFindings += out.found || 0;
  save();
}

function tally(kind, n = 1) {
  stats[kind] = (stats[kind] || 0) + n;
  save();
}
function sweepTally(kind, key) {
  const s = (stats.sweeps[kind] ||= { runs: 0, findings: 0 });
  s[key] += 1;
  save();
}

module.exports = { file, fingerprintOf, ledger, stats, save, tally, sweepTally, simTally };
