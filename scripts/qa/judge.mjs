#!/usr/bin/env node
// The shared screen judge (QA system stage 1, step 2; owner, 18 Nov 2026: "Yes, start stage 1"). One narrow
// question about one small picture (or a before and an after), answered by a model in a FRESH session, so a
// builder's long working session never carries a screenshot (research 18 Nov, 4.6: about 4,900 tokens a picture in
// a fresh session, against hundreds of thousands when it rides in a long one).
//
//   node scripts/qa/judge.mjs --after after.png [--before before.png] --question "Is the primary action obvious?"
//        [--model haiku|sonnet|opus|fable|<model id>] [--crop x,y,w,h] [--max-edge 1568] [--out verdict.json]
//        [--cli claude] [--dry]
//
// - --model: sonnet by default (judge rounds); haiku for a first look at a diff crop; opus or fable only for a hard
//   call. Nothing here needs the top model.
// - Pictures are made small before any model sees them: cropped to --crop (CSS px of the picture), then scaled so
//   the long edge is at most --max-edge. Capture at 1x: a 363x735 phone screen is about 350 tokens at 1x and about
//   3,100 at 3x.
// - It never asks about overflow, overlap, cut text, tap size or contrast: scripts measure those exactly for zero
//   tokens (scripts/ci/wb_readability.mjs). A question about them is refused.
// - The answer is one JSON object: {verdict: "pass" | "fail" | "unsure", reasons: [...], where: [...]}; the script
//   prints a short table and exits 0 (pass), 1 (fail) or 2 (unsure or no answer). --dry prints the plan and the
//   token estimate and calls nothing.
// It uses the CLI's own sign-in (an included subscription); it never reads or takes an API key.
import { spawnSync } from "node:child_process";
import { copyFileSync, existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

export const MODELS = {
  haiku: "claude-haiku-5-5",
  sonnet: "claude-sonnet-5-5",
  opus: "claude-opus-5-5",
  fable: "claude-fable-5-2",
};
export const DEFAULT_MODEL = "sonnet";
export const MAX_EDGE = 1568;
// What a script measures better than any model (research 18 Nov, section 3: about 20% and 31% accuracy).
export const SCRIPT_JOBS = /\b(overflow|overlap|overlapping|clipp|cut[- ]off|truncat|contrast|tap (size|target))/i;

/** The model id for a flag value: a short name, or a full id passed through. */
export function modelOf(flag = DEFAULT_MODEL) {
  const value = String(flag).trim();
  if (MODELS[value.toLowerCase()]) return MODELS[value.toLowerCase()];
  if (/^claude-[a-z0-9-]+$/.test(value)) return value;
  throw new Error(`unknown model "${value}": use ${Object.keys(MODELS).join(", ")} or a full model id`);
}

/** About how many tokens a picture costs: one per 750 pixels. */
export const tokensOf = (width, height) => Math.ceil((width * height) / 750);

/** The size a picture is scaled to so its long edge fits (never scaled up). */
export function fitBox(width, height, maxEdge = MAX_EDGE) {
  const long = Math.max(width, height);
  if (long <= maxEdge) return { width, height };
  const k = maxEdge / long;
  return { width: Math.max(1, Math.round(width * k)), height: Math.max(1, Math.round(height * k)) };
}

/** "x,y,w,h" as numbers; null when not given. */
export function cropOf(text) {
  if (!text) return null;
  const parts = String(text).split(",").map((n) => Number(n.trim()));
  if (parts.length !== 4 || parts.some((n) => !Number.isFinite(n) || n < 0) || !parts[2] || !parts[3])
    throw new Error('--crop is "x,y,width,height" in pixels of the picture');
  return { left: parts[0], top: parts[1], width: parts[2], height: parts[3] };
}

export function parseArgs(argv) {
  const out = { model: DEFAULT_MODEL, maxEdge: MAX_EDGE, cli: "claude", dry: false };
  for (let i = 0; i < argv.length; i++) {
    const flag = argv[i];
    const value = () => {
      if (argv[i + 1] === undefined) throw new Error(`${flag} needs a value`);
      return argv[++i];
    };
    if (flag === "--after") out.after = value();
    else if (flag === "--before") out.before = value();
    else if (flag === "--question") out.question = value();
    else if (flag === "--model") out.model = value();
    else if (flag === "--crop") out.crop = cropOf(value());
    else if (flag === "--max-edge") out.maxEdge = Number(value());
    else if (flag === "--out") out.out = value();
    else if (flag === "--cli") out.cli = value();
    else if (flag === "--dry") out.dry = true;
    else throw new Error(`unknown flag ${flag}`);
  }
  if (!out.after) throw new Error("--after <picture> is required");
  if (!out.question || out.question.trim().length < 8) throw new Error("--question is required: one narrow question");
  if (SCRIPT_JOBS.test(out.question))
    throw new Error(
      "that is a script's job (overflow, overlap, cut text, contrast, tap size): run scripts/ci/wb_readability.mjs",
    );
  if (!(out.maxEdge >= 200 && out.maxEdge <= 2000)) throw new Error("--max-edge is 200 to 2000");
  out.modelId = modelOf(out.model);
  return out;
}

/** What the judge is told. The pictures are files beside it; it reads them itself. */
export function promptOf({ question, before }) {
  return [
    "You are judging one screen of a mobile-first sales app for a non-technical seller.",
    before
      ? "Read the two pictures in this folder with the Read tool: before.png (the approved state) and after.png (the new state). Judge only what changed."
      : "Read the picture after.png in this folder with the Read tool.",
    `Question: ${question.trim()}`,
    "Rules: answer only this question. Do not judge sideways overflow, overlapping text, cut-off text, tap size or colour contrast: a script measures those. Do not suggest redesigns.",
    'Answer with one JSON object and nothing else: {"verdict": "pass" | "fail" | "unsure", "reasons": [up to 4 short plain sentences], "where": [up to 4 short names of the part of the screen]}.',
  ].join("\n");
}

/** The verdict object out of the model's words; null when there is none. */
export function verdictOf(text) {
  const match = String(text ?? "").match(/\{[\s\S]*\}/);
  if (!match) return null;
  try {
    const data = JSON.parse(match[0]);
    if (!["pass", "fail", "unsure"].includes(data.verdict)) return null;
    const list = (value) =>
      (Array.isArray(value) ? value : []).map((item) => String(item).slice(0, 200)).slice(0, 4);
    return { verdict: data.verdict, reasons: list(data.reasons), where: list(data.where) };
  } catch {
    return null;
  }
}

export const exitOf = (verdict) => (verdict?.verdict === "pass" ? 0 : verdict?.verdict === "fail" ? 1 : 2);

/** sharp, from the web app's own dependencies (nothing is installed for the judge). */
function sharpOrNull() {
  try {
    const require = createRequire(import.meta.url);
    const next = createRequire(require.resolve("next/package.json", { paths: [resolve("apps/sales-xray-web")] }));
    return next("sharp");
  } catch {
    return null;
  }
}

/** A picture cropped and scaled into `to`; returns its final size. Without sharp it is copied as it is. */
async function prepare(sharp, from, to, crop, maxEdge) {
  if (!existsSync(from)) throw new Error(`no such picture: ${from}`);
  if (!sharp) {
    copyFileSync(from, to);
    return { width: null, height: null };
  }
  let image = sharp(readFileSync(from));
  const meta = await image.metadata();
  let { width, height } = meta;
  if (crop) {
    const box = {
      left: Math.min(crop.left, width - 1),
      top: Math.min(crop.top, height - 1),
      width: Math.min(crop.width, width - Math.min(crop.left, width - 1)),
      height: Math.min(crop.height, height - Math.min(crop.top, height - 1)),
    };
    image = image.extract(box);
    ({ width, height } = box);
  }
  const fit = fitBox(width, height, maxEdge);
  if (fit.width !== width) image = image.resize(fit.width, fit.height);
  await image.png().toFile(to);
  return fit;
}

async function main() {
  let args;
  try {
    args = parseArgs(process.argv.slice(2));
  } catch (error) {
    console.error(`judge: ${error.message}`);
    process.exit(2);
  }
  const sharp = sharpOrNull();
  const folder = mkdtempSync(join(tmpdir(), "ac-judge-"));
  try {
    const sizes = [];
    if (args.before) sizes.push(await prepare(sharp, resolve(args.before), join(folder, "before.png"), args.crop, args.maxEdge));
    sizes.push(await prepare(sharp, resolve(args.after), join(folder, "after.png"), args.crop, args.maxEdge));
    const tokens = sizes.reduce((sum, s) => sum + (s.width ? tokensOf(s.width, s.height) : 0), 0);
    const plan = {
      model: args.modelId,
      pictures: sizes.map((s) => (s.width ? `${s.width}x${s.height}` : "as given (sharp not found)")),
      picture_tokens_about: tokens || null,
    };
    if (args.dry) {
      console.log(JSON.stringify({ dry: true, ...plan, prompt: promptOf(args) }, null, 2));
      return 0;
    }
    const run = spawnSync(
      args.cli,
      ["-p", "--model", args.modelId, "--output-format", "json", "--allowedTools", "Read", "--max-turns", "6"],
      {
        cwd: folder,
        // The question goes in on stdin, so no shell ever parses it (Windows runs the CLI's .cmd through one).
        input: promptOf(args),
        shell: process.platform === "win32",
        encoding: "utf8",
        timeout: 240000,
        maxBuffer: 8 * 1024 * 1024,
      },
    );
    if (run.error || run.status !== 0) {
      console.error(`judge: the CLI did not answer (${run.error?.code ?? `exit ${run.status}`})`);
      return 2;
    }
    let said = run.stdout;
    let usage = null;
    try {
      const envelope = JSON.parse(run.stdout);
      said = envelope.result ?? run.stdout;
      usage = envelope.usage ?? null;
    } catch {
      /* plain text: read the verdict from it */
    }
    const verdict = verdictOf(said);
    const result = { ...plan, question: args.question.trim(), ...(verdict ?? { verdict: "unsure", reasons: ["no verdict in the answer"], where: [] }), usage };
    if (args.out) writeFileSync(resolve(args.out), JSON.stringify(result, null, 2));
    console.log(`| verdict | where | reason |\n| --- | --- | --- |`);
    const rows = Math.max(1, result.reasons.length);
    for (let i = 0; i < rows; i++)
      console.log(`| ${i ? "" : result.verdict.toUpperCase()} | ${result.where[i] ?? ""} | ${result.reasons[i] ?? ""} |`);
    console.log(`model ${args.modelId}; pictures ${plan.pictures.join(" and ")}; about ${tokens} picture tokens`);
    return exitOf(verdict);
  } finally {
    rmSync(folder, { recursive: true, force: true });
  }
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) process.exit(await main());
