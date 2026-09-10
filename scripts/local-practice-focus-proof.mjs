// Native-input acceptance of optional Focus, isolated to newly created local fixture attempts.
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { localPage } from "./local-page-cdp.mjs";
if (process.argv[2] !== "--run-local") {
  console.log(
    "Use --run-local: creates two synthetic learner attempts through native UI; never changes live environments.",
  );
  process.exit(0);
}
const repository = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);
const origin = "http://learner.localhost:3100";
const output = path.join(
  repository,
  "docs/evidence/screenshots",
  `practice-focus-${new Date().toISOString().replace(/[:.]/g, "-")}`,
);
const page = await localPage({
  pathname: "/practice?set=next-move",
  newTab: true,
});
const proof = {
  scope: "localhost synthetic learner, native UI mutations only",
  attempts: [],
  checks: [],
  screenshots: [],
  passed: false,
};
const check = (value, name) => {
  if (!value) throw Error(name);
  proof.checks.push(name);
};
const get = (route) =>
  page.evaluate(
    `(async()=>{if(location.origin!==${JSON.stringify(origin)})throw Error();const r=await fetch(${JSON.stringify(route)},{credentials:'same-origin',cache:'no-store',redirect:'error'});if(!r.ok)throw Error();return r.json();})()`,
  );
const guard = async () => {
  const me = await get("/v1/me");
  check(
    me.email === "learner@ac.localhost" &&
      me.selected_tenant_id === "65e76922-c033-5459-9101-3de86637246e",
    "synthetic tenant/session",
  );
};
const native = async (expression) => {
  await guard();
  await page.until(`!!(${expression}) && !(${expression}).disabled`);
  const point = await page.evaluate(
    `(()=>{const e=${expression};e.scrollIntoView({block:'nearest'});const r=e.getBoundingClientRect();return{x:r.x+r.width/2,y:r.y+r.height/2}})()`,
  );
  await page.send("Input.dispatchMouseEvent", {
    type: "mousePressed",
    button: "left",
    clickCount: 1,
    ...point,
  });
  await page.send("Input.dispatchMouseEvent", {
    type: "mouseReleased",
    button: "left",
    clickCount: 1,
    ...point,
  });
};
const button = (label) => native(page.button(label));
const summary =
  "[...document.querySelectorAll('details>summary')].find(e=>/Optional Focus|Focus run/.test(e.textContent))";
const viewport = async (width, height) => {
  await page.send("Emulation.setDeviceMetricsOverride", {
    width,
    height,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await page.delay(250);
};
const capture = async (name) => {
  const dimensions = await page.evaluate(
    `(()=>{const r=document.documentElement,d=document.querySelector('dialog[open]');return {width:r.clientWidth,scrollWidth:r.scrollWidth,height:innerHeight,dialog:d?{height:d.clientHeight,scrollHeight:d.scrollHeight,top:d.getBoundingClientRect().top}:null}})()`,
  );
  const image = await page.send("Page.captureScreenshot", {
    format: "png",
    captureBeyondViewport: false,
  });
  await writeFile(
    path.join(output, `${name}.png`),
    Buffer.from(image.data, "base64"),
  );
  proof.screenshots.push({ name, ...dimensions });
  check(
    dimensions.scrollWidth <= dimensions.width + 1,
    `${name}: no horizontal overflow`,
  );
  if (dimensions.dialog)
    check(
      dimensions.dialog.scrollHeight <= dimensions.dialog.height + 1,
      `${name}: dialog fits without scrolling`,
    );
};
const saved = () =>
  writeFile(path.join(output, "proof.json"), JSON.stringify(proof, null, 2));
const readAttempt = (id) => get(`/v1/practice/attempts/${id}`);
const wallet = async () => {
  const p = await get("/v1/practice/progress");
  return {
    credits: p.credits_balance,
    xp: p.xp_total,
    awards: p.recent_awards.map((a) => a.id).sort(),
  };
};
// Signed delivery fields rotate between reads; compare persisted avatar identity only.
const avatar = async () => {
  const p = await get("/v1/profile/avatar");
  return {
    asset: p.avatar?.asset_id ?? null,
    version: p.avatar?.version_id ?? null,
  };
};
const create = async () => {
  await page.until("!!document.querySelector('#practice-start-title')");
  await button("Start a new practice");
  await page.until(
    "!!new URL(location.href).searchParams.get('attempt') && !!document.querySelector('[id^=prompt-]')",
  );
  const id = await page.evaluate(
    "new URL(location.href).searchParams.get('attempt')",
  );
  proof.attempts.push(id);
  await saved();
  check(
    (await readAttempt(id)).revision === 0,
    "new owned revision-zero attempt",
  );
  await native(summary);
  await button("Enable Focus for this run");
  await page.until(
    "document.body.textContent.includes('Focus is on for this run.')",
  );
  check(
    (await get("/v1/practice/focus")).active_run?.attempt_id === id,
    "explicit Focus activation persisted",
  );
  await native(summary);
  return id;
};
const answer = async (id) => {
  check(proof.attempts.includes(id), "only own attempt answered");
  const before = await readAttempt(id);
  const item = before.set.items.find(
    (i) => !before.acknowledged_item_ids.includes(i.id),
  );
  await page.until(
    `!!document.getElementById(${JSON.stringify("prompt-" + item.id)})`,
  );
  await native("document.querySelector('input[type=radio]')?.closest('label')");
  await button("Check my response");
  const label =
    before.acknowledged_item_ids.length === before.set.items.length - 1
      ? "Finish this set"
      : "Next prompt";
  await page.until(`!!(${page.button(label)})`);
  await button(label);
  await page.until(
    `Number(document.querySelector('[aria-label="Prompts saved in this practice"]')?.getAttribute('aria-valuenow'))===${before.acknowledged_item_ids.length + 1} || !!document.querySelector('#practice-earned-title')`,
  );
  const after = await readAttempt(id);
  check(
    after.acknowledged_item_ids.length ===
      before.acknowledged_item_ids.length + 1,
    "response and feedback acknowledgment persisted",
  );
};
try {
  await mkdir(output, { recursive: true });
  await page.until(
    "location.origin==='http://learner.localhost:3100' && !!document.querySelector('#practice-start-title')",
    60000,
  );
  await guard();
  const initialFocus = await get("/v1/practice/focus");
  check(
    !initialFocus.active_run && initialFocus.charges === 3,
    "no user-owned Focus run disturbed",
  );
  const originalWallet = await wallet();
  const originalAvatar = await avatar();
  await viewport(1440, 1000);
  const first = await create();
  await answer(first);
  await button("Leave practice");
  await page.until("!!document.querySelector('dialog[open]')");
  for (const [name, w, h] of [
    ["desktop1440", 1440, 1000],
    ["mobile390", 390, 844],
    ["mobile320", 320, 740],
  ]) {
    await viewport(w, h);
    await capture(`${name}-focus-pause`);
  }
  check(
    (await get("/v1/practice/focus")).charges === 3,
    "opening exit does not charge",
  );
  await native(
    "[...document.querySelectorAll('dialog a')].find(e=>e.textContent.includes('Pause & save'))",
  );
  await page.until("location.pathname==='/practice' && !location.search");
  check(
    (await get("/v1/practice/focus")).charges === 3,
    "free pause does not charge",
  );
  await page.send("Page.navigate", {
    url: `${origin}/practice?set=next-move&attempt=${first}`,
  });
  await page.until(
    "!!document.querySelector('[id^=prompt-]') && document.querySelector('[aria-label=" +
      JSON.stringify("Prompts saved in this practice") +
      "]')?.getAttribute('aria-valuenow')==='1'",
  );
  await page.until(`(${summary})?.textContent.includes('Focus run')`);
  await button("Leave practice");
  await page.until("!!document.querySelector('dialog[open]')");
  await button("End Focus run · 1 charge");
  await page.until(
    "document.querySelector('dialog')?.textContent.includes('1 Focus charge used.')",
  );
  await capture("mobile320-focus-ended");
  const endedFocus = await get("/v1/practice/focus");
  check(
    endedFocus.charges === 2 && !endedFocus.active_run,
    "explicit acknowledged end costs exactly one",
  );
  check(
    JSON.stringify(await wallet()) === JSON.stringify(originalWallet),
    "Focus start/pause/end never changes earned wallet",
  );
  check(
    (await readAttempt(first)).acknowledged_item_ids.length === 1,
    "end preserves saved answers",
  );
  await button("Keep practising");
  await answer(first);
  await answer(first);
  check(
    (await get("/v1/practice/focus")).charges === 2,
    "standard completion after end does not restore Focus",
  );
  await page.send("Page.navigate", { url: `${origin}/practice?set=next-move` });
  await page.until("!!document.querySelector('#practice-start-title')");
  await viewport(1440, 1000);
  const second = await create();
  await answer(second);
  await answer(second);
  await answer(second);
  await page.until("!!document.querySelector('#practice-earned-title')");
  const completedFocus = await get("/v1/practice/focus");
  check(
    completedFocus.charges === 3 && !completedFocus.active_run,
    "Focus completion restores one capped charge",
  );
  await capture("desktop1440-completed");
  check(
    JSON.stringify(await avatar()) === JSON.stringify(originalAvatar),
    "existing portrait unchanged",
  );
  proof.passed = true;
  console.log(
    JSON.stringify({ output, passed: true, checks: proof.checks.length }),
  );
} catch (error) {
  proof.failure = error.message;
  await capture("failure-state").catch(() => {});
  console.log(
    JSON.stringify({ output, passed: false, failure: error.message }),
  );
  process.exitCode = 1;
} finally {
  await saved();
  await page.send("Emulation.clearDeviceMetricsOverride").catch(() => {});
  await page.close();
}
